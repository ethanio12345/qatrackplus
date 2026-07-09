# Design: Fix myQA Importers

> Expansion of the frozen `proposal.md` into concrete queries, metric dicts,
> and setup strategy. Verified schema in `schema-reference.md`; commitment
> baseline in `explore-brief.md`.

## Engine contract (out of scope per proposal Non-goal — for reference)

The shared engine in `myqa_import.py` is **not refactored** by this change.
Designers/implementers must honour the existing contract:

- `query_new_sessions` (`myqa_import.py:109-148`) selects `te.TaskExecutionId`
  and returns sessions as dicts with key `task_execution_id`.
- `import_session` (`myqa_import.py:161-228`) extracts `execution_id =
  session['task_execution_id']`, calls `self.extract_results(execution_id)`,
  iterates the result as `Dict[str, Any]` (`{slug: value}`), and writes one
  `TestInstance` per entry with `value`/`string_value` and **`pass_fail='no_tol'`
  hardcoded** (`myqa_import.py:226`).
- Each importer also appends a dedup key (`{list_slug}_taskid` or `mtx_taskid`)
  to the results dict for `duplicate_check`.

**Consequences for this design:**
1. **Every `extract_results` query must `JOIN` through `MQA_TestExecutions te`
   and filter `WHERE te.TaskExecutionId = %s`** — never filter on a type-table
   `Id` directly. The execution_id passed in is `te.TaskExecutionId`, which is a
   distinct column from `te.Id` (FK → `MQA_TaskExecutions`,
   `schema-reference.md:215`). Filtering on `te.Id` would return zero rows.
2. **`extract_results` returns `Dict[str, Any]`** (`{slug: value}`), not tuples.
3. **D4 restated (soft-freeze, see `proposal.md`):** the engine hardcodes
   `pass_fail='no_tol'`. Importers READ source `*_Verdict` for diagnostic
   logging only; **verdict storage is deferred** to a future engine enhancement
   and is out of scope. Storing verdicts would require modifying `import_session`
   (the write path) — that is not part of this change.

### Existing importers are broken in two ways

1. **Wrong JOIN path.** The existing MLC/CBCT/Planar/VMAT importers JOIN through
   `*_QueueItemExecutions` tables (e.g. `myqa_import.py:446-448` references
   `MQA_MDL_MlcQA_QueueItemExecutions`). Those tables are **not in the verified
   schema** — the verified path is the same-UUID link
   (`schema-reference.md:18-20`) or the MLC extra hop through
   `MQA_MDL_MlcQA_TestExecutions` (`schema-reference.md:17,59-65`).
2. **Wrong columns.** Existing importers read `DisplayName` / `Actual` /
   `PassStatus` / `tc.Name`-via-`MQA_TestConditions` — none of which exist on
   the verified tables. The redesign reads the verified columns directly.

### TASK_TYPE_REGISTRY changes

| Entry | list_slug | task_name_patterns (from source) | Class |
|---|---|---|---|
| `numeric_constancy` | `myqa_daily_constancy` | `5.Tmt.Linac.D - myQA Daily Constancy Check` | `MyqaNumericConstancyImport` |
| `numeric_physics` | `myqa_daily_physics` | `5.Tmt.Linac.D2 - Daily QA (Physics)` | `MyqaNumericPhysicsImport` |
| `numeric_dxr` | `myqa_dxr_daily` | `5.Tmt.DXR.D - myQA Daily Constancy Check` | `MyqaNumericDxrImport` |
| `myqa_mlc` | `myqa_mlc` | `5.Tmt.Linac.M%MLC%`, `5.Tmt.DXR.M%MLC%` | `MyqaMlcImport` (rewritten) |
| `myqa_cbct` | `myqa_cbct` | `5.Tmt.Linac.M%CBCT%`, `5.Tmt.DXR.M%CBCT%` | `MyqaCbctImport` (rewritten) |
| `myqa_planar` | `myqa_planar` | `5.Tmt.Linac.M%Planar%`, `5.Tmt.DXR.M%Planar%` | `MyqaPlanarImport` (rewritten) |
| `myqa_vmat` | `myqa_vmat` | `5.Tmt.Linac.M%VMAT%`, `5.Tmt.DXR.M%VMAT%` | `MyqaVmatImport` (rewritten) |
| `myqa_winston_lutz` | `myqa_winston_lutz` | `5.Tmt.Linac.M%Winston%`, `5.Tmt.DXR.M%Winston%` | `MyqaWinstonLutzImport` (rewritten) |
| `myqa_passfail` | `myqa_passfail` | confirm from source `MyqaPassFailImport.task_name_patterns` (~line 275) | `MyqaPassFailImport` (rewritten) |

Numeric task-name patterns use **full task name strings** from the frozen main
spec (`openspec/specs/myqa-sync/spec.md:15-16,30`), not short prefixes — this
avoids the `.D%` ambiguity. The original `'myqa_numeric'` registry entry is
removed (per D1); the `MyqaNumericImport` class is replaced by a shared
`MyqaNumericImportBase` + 3 subclasses that set only `list_slug`,
`task_name_patterns`, and `frequency`.

The `import_myqa_results` default (`myqa_import.py:583`: `task_type='myqa_numeric'`)
is updated to `numeric_constancy`. The three Numeric lists are each invoked
explicitly by their own django-q `Schedule` entries (one per list); there is no
aggregate key (an aggregate would require engine fan-out logic outside this
change's Non-goal on engine refactor). Existing django-q `Schedule` rows passing
`'myqa_numeric'` must be migrated to the three new keys — documented as a setup
task in `tasks.md`.

---

## Pattern A — Numeric (3 importers, shared extract)

### `extract_results(execution_id)` → `Dict[str, Any]`

```sql
SELECT tcne.Name, tcne.Actual
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Per row: `results[slugify_name(self.list_slug, tcne.Name)] = tcne.Actual`.
Plus the dedup key `results[f'{self.list_slug}_taskid'] = execution_id`.

**No tolerance emitted in the import path** (S3 fix — tolerances are setup-only;
`import_session` does not process them). `tcne.Expected`, `tcne.WarnOn`,
`tcne.FailOn`, `tcne.LimitTendency`, `tcne.BoundingType`, `tcne.IsRelative` are
**not selected during import** — they are read during setup only (below).

### Setup (per D2 — rewrite, discovery-based)

```sql
SELECT DISTINCT tcne.Name, tcne.WarnOn, tcne.FailOn,
                tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName LIKE %s
```

Run **three times** — once per `task_name_pattern` — writing into each
respective list. Replaces the current triple-broken query
(`setup_myqa_tests.py:77-87`). Tolerance via `get_or_create_tolerance`
(unchanged helper, `setup_myqa_tests.py:29-70`). `BoundingType` is read but not
acted on (forward-compat; O6 ensures no regression for Energy/Wedge/Output).

---

## Pattern D — WinstonLutz

### `extract_results(execution_id)` → `Dict[str, Any]`

```sql
SELECT wl.MaximumDeviation2D, wl.Deviation3D,
       wl.Tolerance_Warn, wl.Tolerance_Fail
FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Single row. Emits:
- `results[slugify_name(list_slug, 'Maximum Deviation 2D')] = MaximumDeviation2D`
- `results[slugify_name(list_slug, 'Deviation 3D')] = Deviation3D`
- `results[f'{list_slug}_taskid'] = execution_id`

`Tolerance_Warn` / `Tolerance_Fail` are read during **setup** only (shared
two-sided absolute tolerance; WL has no `LimitTendency` column → assume `0`).
`pass_fail` is `no_tol` per engine reality (D4 deferred).

### Setup

Hardcoded 2-test list, 1 shared tolerance. No discovery query.

---

## Pattern B — MLC, CBCT, Planar (denormalized wide-row)

### Common shape

Each Pattern B importer:
1. `extract_results` JOINs through `te` (filtering `te.TaskExecutionId`),
   SELECTs the metric columns, iterates a static `METRICS` dict to emit one
   entry per metric.
2. Verdict columns (`*_Result_Verdict`) are available for diagnostic logging
   but not stored (D4 deferred — engine hardcodes `pass_fail='no_tol'`).

### METRICS dict schema

```python
METRICS = {
    '<metric_slug_suffix>': {
        'value_col': '<prefix>_Result_Value_Value',     # required
        'verdict_col': '<prefix>_Result_Verdict',        # for logging only
        'warn_col':   '<prefix>_AcceptanceCriterion_Tolerances_Warn_Value',  # setup only
        'fail_col':   '<prefix>_AcceptanceCriterion_Tolerances_Fail_Value',  # setup only
    },
    # value-only entries use verdict_col=None, warn_col=None, fail_col=None
    # string-value entries are listed separately in STRING_COLS (see MLC)
}
```

Slug = `slugify_name(list_slug, '<metric_slug_suffix>')`.

### MLC

```sql
SELECT r.<metric cols>, r.TestResult, r.TotalPeaks, r.LeavesThatFailed
FROM MQA_MDL_MlcQA_Results r
JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

`METRICS` prefixes (5, each full 4-tuple): `FailingPeaks`,
`MaximumDeviation`, `InterstripRatio`, `StandardDeviation`,
`IsocenterToStripDistance`. Plus a separate `STRING_COLS` list for non-conforming
entries:
- `TestResult` — verdict-only, no value → **logged, no slug emitted**
- `TotalPeaks` — value-only → slug `myqa_mlc_total_peaks` (value entry)
- `LeavesThatFailed` — string → slug `myqa_mlc_leaves_that_failed`
  (engine stores as `string_value` via the `isinstance(val, str)` branch at
  `myqa_import.py:220`)

**Open question O1 resolution (verify at impl):** `LineDistanceAcceptanceCriterion_*`
and `LineSlopeAcceptanceCriterion_*` are listed in the schema as warn/fail values
with no paired `_Result_Value_Value`. Treated as **tolerance-only orphans →
excluded from METRICS**. If a paired result column is found at impl, add them.

### CBCT

```sql
SELECT r.<metric cols>, r.SliceWidthDifference_Value, r.TestResult
FROM MQA_MDL_Cbct_Results r
JOIN MQA_MDL_Cbct_TestExecutions cte ON r.Id = cte.Id
JOIN MQA_TestImplementationExecutions tie ON cte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

`METRICS` prefixes (9, each full 4-tuple): `ScalingDiscrepancy`,
`GeometricDistortion`, `SpatialResolution`, `OverallUniformity`,
`MinimumUniformity`, `Contrast`, `CNR`, `MaxHuDeviation`, `MeasuredSliceWidth`.

**O2 resolution:** non-conforming columns:
- `SliceWidthDifference_Value` — value-only → slug
  `myqa_cbct_slice_width_difference` (value entry; `_Dimension` is metadata, not stored)
- `MaxHuDeviationRoi`, `MinUniformityRoi`, `EnergyType`, `EnergyValue`,
  `TestResult` — metadata → **no slug, not emitted**

### Planar

```sql
SELECT r.<metric cols>, r.TestResult
FROM MQA_MDL_Planar_Results r
JOIN MQA_MDL_Planar_TestExecutions pte ON r.Id = pte.Id
JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

`METRICS` prefixes (7, each full 4-tuple): `ScalingDiscrepancy`,
`SpatialResolution`, `MinimumUniformity`, `Contrast`, `CNR`, `XOffset`,
`YOffset`. Non-conforming (`MinUniformityRoi`, `EnergyType`, `EnergyValue`,
`TestResult`) → metadata, no slug.

### Pattern B setup (per D2 — rewrite, hardcoded METRICS)

No `Name` column → no discovery query. Setup iterates the same `METRICS` dict
the importer uses, creating one `Test` per entry. For metrics with
`warn_col`/`fail_col`, also `get_or_create_tolerance(warn, fail,
is_relative=False, limit_tendency=0)`.

---

## Pattern C — VMAT (hybrid: parent wide-row + child fan-out)

### Parent query (one row)

```sql
SELECT r.NormalizationValueResult_Value_Value
FROM MQA_MDL_VmatDmlc_Results r
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Emits `results[slugify_name(list_slug, 'Normalization Value')] =
r.NormalizationValueResult_Value_Value`. The
`NormalizationValueAcceptanceCriterion_Tolerances_Warn/Fail_Value` columns are
read during **setup only** (see Pattern C setup below) — not selected during
import.

### Child query (iterate ROI rows)

```sql
SELECT rr.Name, rr.Mean_Value_Value, rr.StandardDeviation_Value_Value, rr.Rank
FROM MQA_MDL_VmatDmlc_RoiResults rr
JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
ORDER BY rr.Rank
```

Per child row, emit two entries:
- `results[slugify_name(list_slug, f'{clean(rr.Name)} mean')] = rr.Mean_Value_Value`
- `results[slugify_name(list_slug, f'{clean(rr.Name)} std dev')] = rr.StandardDeviation_Value_Value`

### Shared tolerance query (setup only)

`RoiMeanAcceptanceCriterion_Tolerances_Warn/Fail_Value` and
`RoiStandardDeviationAcceptanceCriterion_Tolerances_Warn/Fail_Value` live on
the parent table and are read during setup (one tolerance per metric type,
shared across all ROI rows of that type).

### O3 resolution — ROI slugification

`rr.Name` looks like `[2.0 cm/s]`. Slug rule:
1. `clean()` strips leading/trailing brackets `[` `]`.
2. `slugify_name(list_slug, f'{cleaned} mean')` — note `slugify_name`
   (`myqa_import.py:40`) **preserves periods** in its regex, so `2.0` stays
   `2.0` → slug like `myqa_vmat_2.0_cm_s_mean`. Implementer must confirm period
   in slugs is acceptable to QATrack+ URL routing, or pre-strip periods in
   `clean()`.

### Pattern C setup

Static parent test (`Normalization Value`) + discovery query over the child
table for ROI tests (one Mean + one StdDev test per distinct `rr.Name`). Shared
tolerances from parent table.

---

## Pattern D — PassFail (degenerate, per D3)

### `extract_results(execution_id)` → `Dict[str, Any]`

```sql
SELECT pfte.AcceptanceCriteria
FROM MQA_PassFail_TestExecutions pfte
JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Single row. Emits `results[slugify_name(list_slug, 'Acceptance Criteria')] =
pfte.AcceptanceCriteria` (nvarchar → engine stores as `string_value`).
Plus dedup key. No tolerance, no verdict.

### Setup

Hardcoded 1-test list, no tolerance, no discovery. The existing
`MQA_TestConditions` JOIN (`myqa_import.py:284`) and `pfte.PassStatus` read
(`myqa_import.py:282`) are removed — neither exists per verified schema.

---

## Setup rewrite summary (per D2)

The current `setup_myqa_tests.py:148-150` SKIPs every non-Numeric type. The
rewrite replaces the body of `handle()` with a per-type dispatch:

| Type | Setup strategy |
|---|---|
| Numeric (3 lists) | Discovery query (corrected) per `task_name_pattern`, per list |
| WinstonLutz | Hardcoded 2-test list, 1 shared tolerance |
| MLC / CBCT / Planar | Iterate static `METRICS` dict; one Test + Tolerance per metric with `warn_col`/`fail_col` |
| VMAT | Static parent test + discovery query over ROI child table for ROI tests |
| PassFail | Hardcoded 1-test list, no tolerance |

`get_or_create_tolerance`, `Frequency` lookup, `TestList` /
`TestListMembership` / `UnitTestCollection` creation, and `--dry-run` /
`--force` flags are reused unchanged.

### Per-type unit scoping (M8 fix)

The current UTC loop (`setup_myqa_tests.py:232`) iterates all `LINAC_MAP`
units for every list. The rewrite applies the main-spec unit scoping:
- Linac lists (`myqa_daily_constancy`, `myqa_daily_physics`, `myqa_mlc`, etc.)
  → units 1,2,3,4,5,7,8
- DXR list (`myqa_dxr_daily`) → unit 50
- A `UNITS_PER_LIST` mapping (per `openspec/specs/myqa-sync/spec.md:13-34`)
  drives this; spurious UTCs are not created.

### `--force` safety (M1 fix)

`--force` deletes `TestListMembership` rows for the TestList and `Test` rows
whose slug starts with `{list_slug}_`. **Per-list risk:**

| List slug | Risk on `--force` |
|---|---|
| `myqa_daily_constancy`, `myqa_daily_physics` | **Main-spec lists** (`spec.md:15-16`). `--force` WILL delete existing Tests/TestListMemberships. Verify no production TestListInstances reference these slugs before running. |
| `myqa_dxr_daily` | **Main-spec list** (`spec.md:30`). Same risk. |
| `myqa_mlc`, `myqa_cbct`, `myqa_planar`, `myqa_vmat`, `myqa_winston_lutz`, `myqa_passfail` | New lists — no existing data, safe to `--force`. |
| `myqa_monthly_*`, `myqa_annual_*`, `myqa_quarterly_*`, `myqa_6monthly` | **Not touched** by this change (not in registry). |

Slug prefixes are unique per list (no cross-list collisions). The proposal's
"verify in production before `--force`" caveat (`proposal.md:99`) applies
specifically to the three main-spec daily lists.

---

## Open question resolutions (consolidated)

| ID | Question | Resolution |
|---|---|---|
| O1 | MLC tolerance-only columns (`LineDistance*`, `LineSlope*`) | Excluded from METRICS (no paired result column). Verify at impl; add if paired column found. |
| O2 | CBCT/Planar non-conforming columns | `SliceWidthDifference` gets a value-only slug; `*Roi` / `EnergyType` / `EnergyValue` / `TestResult` are metadata, no slug. |
| O3 | VMAT ROI slugification | Strip brackets, slugify `{name} mean` / `{name} std dev`. `slugify_name` preserves periods — verify URL safety at impl. |
| O4 | `IsDeleted` filter | Deferred per proposal Non-goals. |
| O5 | Profile trailing-space columns | Out of scope; documented in `schema-reference.md`. |
| O6 | Energy/Wedge/Output tolerance helper regression | Out of scope; `get_or_create_tolerance` reused unchanged. |

---

## Backfill plan (per type, setup-before-import)

For each type, in priority order (Numeric first per `proposal.md:31`):
1. `setup_myqa_tests --dry-run` for the type → review discovered tests
2. `setup_myqa_tests --force` for the type → creates TestList/Test/Tolerance/UTC
3. `import_myqa_results --task <type> --days 365` → backfills
4. Re-run import → assert 0 new (dedup verification)

This per-type setup-then-backfill ordering replaces the original `tasks.md`
Phase 5 "extend setup for all types" (the Round 1 dependency-order fix).
