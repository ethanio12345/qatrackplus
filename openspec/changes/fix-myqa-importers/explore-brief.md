# Explore Brief — fix-myqa-importers

> Verified schema lives in `schema-reference.md`. This brief captures the design
> commitments, mapping tables, rejected alternatives, data flow, and open
> questions that the proposal/design/specs/tasks must be checked against.

## Decisions (authoritative for downstream artifacts)

- **D1 — Numeric list strategy = SPLIT (option b).** Numeric executions live
  under both `.D` (Constancy) and `.D2` (Physics) task names. They map to the
  **existing** main-spec lists, not a new `myqa_numeric` slug:
  - `5.Tmt.Linac.D` + `5.Tmt.DXR.D` → `myqa_daily_constancy`
  - `5.Tmt.Linac.D2` → `myqa_daily_physics`
  - The proposed `myqa_numeric` slug is **deleted** from all artifacts. This
    resolves the Round 1 slug conflict with the frozen main spec.
  - *Override: if the user wants (a) one combined list or (c) only one task,
    unfreeze from proposal downward.*
- **D2 — Setup is rewritten, not extended.** `setup_myqa_tests.py` currently
  has a triple-broken Numeric query (`MQA_TestConditions` doesn't exist;
  `WarningTolerance`/`ErrorTolerance` should be `WarnOn`/`FailOn`;
  `TestCondition_Id`/`TestImplementationExecution_Id` should be
  `NumericTestExecution_Id`) and explicitly `SKIP`s every non-Numeric type
  (`setup_myqa_tests.py:148-150`). The proposal's "extend" framing is wrong:
  Numeric needs a fix, the other 6 types need new code paths.
- **D3 — PassFail stores `AcceptanceCriteria` text.** No `PassStatus` column
  exists (Key Finding #3). The only data is `AcceptanceCriteria` nvarchar →
  stored as `string_value`. No tolerance. This is a real semantic change from
  the current code's intent (boolean) and must be acknowledged in the proposal.
- **D4 — Use `*_Verdict` directly, don't recompute pass/fail.** Verdict encoding
  is consistent across all myQA tables (0/10/30/40/50/60). Importers should
  read the source `*_Verdict` rather than re-deriving pass/fail from tolerance
  comparison.

## The four data-model patterns

| Pattern | Types | Row shape | Slug strategy | Setup strategy |
|---|---|---|---|---|
| **A. Dynamic row-per-condition** | Numeric | 1 exec → N rows | dynamic, from `Name` | `SELECT DISTINCT tcne.Name` + corrected cols |
| **B. Fixed denormalized wide-row** | MLC, CBCT, Planar | 1 exec → 1 wide row | static `METRICS` dict | iterate `METRICS` (no discovery query — no `Name` col) |
| **C. Child-table fan-out (hybrid)** | VMAT | 1 exec → 1 parent + N child rows | parent static; child dynamic from ROI `Name` | static parent + `SELECT DISTINCT Name` from child |
| **D. Direct simple columns** | WinstonLutz, PassFail | 1 exec → 1 row | static fixed list | hardcoded list |

## Per-type mapping tables

### Numeric (Pattern A) — two lists per D1

| Item | Value |
|---|---|
| Lists | `myqa_daily_constancy` (task patterns `5.Tmt.Linac.D`, `5.Tmt.DXR.D`); `myqa_daily_physics` (`5.Tmt.Linac.D2`) |
| Test slug | dynamic: `slugify_name(list_slug, tcne.Name)` |
| Value | `tcne.Actual` |
| Reference | `tcne.Expected` |
| Warn / Fail tol | `tcne.WarnOn`, `tcne.FailOn` |
| Tendency / Bounding / Relative | `tcne.LimitTendency`, `tcne.BoundingType`, `tcne.IsRelative` |
| JOIN | `tcne.NumericTestExecution_Id = tie.Id = te.Id` |
| Setup query | `SELECT DISTINCT tcne.Name, tcne.WarnOn, tcne.FailOn, tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency FROM MQA_Numeric_TestConditionExecutions tcne JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id JOIN MQA_TestExecutions te ON tie.Id = te.Id WHERE te.TaskName LIKE %s` |
| Importer `extract_results(execution_id)` | per-execution: `WHERE tcne.NumericTestExecution_Id = %s` (NOT a bulk `TaskName LIKE` — see rejected alt A1) |

### WinstonLutz (Pattern D)

| Item | Value |
|---|---|
| List | `myqa_winston_lutz` (new) |
| Static slugs | `myqa_winston_lutz_max_deviation_2d`, `myqa_winston_lutz_deviation_3d` |
| Values | `MaximumDeviation2D`, `Deviation3D` |
| Warn / Fail tol (shared) | `Tolerance_Warn`, `Tolerance_Fail` |
| JOIN | standard: `Id = tie.Id = te.Id` |
| Setup | hardcoded 2-test list, shared tolerance |

### MLC (Pattern B)

| Item | Value |
|---|---|
| List | `myqa_mlc` (new) |
| Static metric prefixes | `FailingPeaks`, `MaximumDeviation`, `InterstripRatio`, `StandardDeviation`, `IsocenterToStripDistance` (each has `_Result_Value_Value`, `_Result_Verdict`, `_AcceptanceCriterion_Tolerances_Warn_Value`, `_Fail_Value`) |
| Loose columns (own slugs) | `TestResult` (verdict-only), `TotalPeaks`, `LeavesThatFailed` (string) |
| JOIN | `r.MlcQATestExecutionBase_Id = mte.Id → tie.Id = te.Id` (extra hop through `MQA_MDL_MlcQA_TestExecutions`) |
| Setup | iterate `METRICS` dict; for each prefix, read the 4-tuple columns |

### CBCT (Pattern B)

| Item | Value |
|---|---|
| List | `myqa_cbct` (new) |
| Static metric prefixes (9) | `ScalingDiscrepancy`, `GeometricDistortion`, `SpatialResolution`, `OverallUniformity`, `MinimumUniformity`, `Contrast`, `CNR`, `MaxHuDeviation`, `MeasuredSliceWidth` |
| Non-conforming | `SliceWidthDifference_Value` / `_Dimension` (own slug, no verdict/tol); `MaxHuDeviationRoi`, `MinUniformityRoi` (metadata, no slug); `EnergyType`, `EnergyValue`, `TestResult` (metadata) |
| JOIN | same-UUID: `r.Id = tie.Id = te.Id` |
| Setup | iterate `METRICS` + special-case `SliceWidthDifference` |

### Planar (Pattern B)

| Item | Value |
|---|---|
| List | `myqa_planar` (new) |
| Static metric prefixes (7) | `ScalingDiscrepancy`, `SpatialResolution`, `MinimumUniformity`, `Contrast`, `CNR`, `XOffset`, `YOffset` |
| Non-conforming | `MinUniformityRoi`, `TestResult`, `EnergyType`, `EnergyValue` (metadata, no slug) |
| JOIN | same-UUID: `r.Id = tie.Id = te.Id` |
| Setup | iterate `METRICS` |

### VMAT (Pattern C — hybrid)

| Item | Value |
|---|---|
| List | `myqa_vmat` (new) |
| Parent metric (static) | `NormalizationValue` — value `NormalizationValueResult_Value_Value`, verdict `_Verdict`, warn/fail `NormalizationValueAcceptanceCriterion_Tolerances_Warn/Fail_Value`, expected `NormalizationValueAcceptanceCriterion_ExpectedValue_Value` |
| Child metrics (dynamic per ROI) | from `MQA_MDL_VmatDmlc_RoiResults`: `Mean_Value_Value`, `Mean_Verdict`, `StandardDeviation_Value_Value`, `StandardDeviation_Verdict`; tolerances from parent table `RoiMeanAcceptanceCriterion_Tolerances_Warn/Fail_Value`, `RoiStandardDeviationAcceptanceCriterion_Tolerances_Warn/Fail_Value` |
| ROI slug derivation | `slugify_name(list_slug, rr.Name)` — strip brackets from `[2.0 cm/s]` first |
| JOIN parent | same-UUID: `r.Id = tie.Id = te.Id` |
| JOIN child | `rr.VmatDmlcResult_Id = r.Id` |
| Setup | static for `NormalizationValue`; `SELECT DISTINCT rr.Name` from child table for ROI metrics |

### PassFail (Pattern D, degenerate)

| Item | Value |
|---|---|
| List | `myqa_passfail` (new) |
| Static slug | `myqa_passfail_acceptance_criteria` |
| Value | `AcceptanceCriteria` (nvarchar → `string_value`) |
| Tolerance | none (no numeric value, no tolerance columns) |
| JOIN | standard: `Id = tie.Id = te.Id` |
| Setup | hardcoded 1-test list, no tolerance |

## Rejected alternatives

- **A1 — Bulk `WHERE TaskName LIKE` in `extract_results`.** Rejected: the engine
  calls `extract_results(execution_id)` once per session and constrains by
  `TaskExecutionId`/`NumericTestExecution_Id`. A bulk query returns the wrong
  row cardinality. Task-name filtering belongs in `query_new_sessions`, not
  `extract_results`. (This was the design.md error.)
- **A2 — Dynamic `DisplayName` scan for all types.** Rejected: only Numeric has
  a `Name` column. MLC/CBCT/Planar metric names exist only as column-name
  prefixes, not row values. There is nothing to `SELECT DISTINCT`.
- **A3 — Uniform denormalized `METRICS` for all denormalized types.** Rejected:
  VMAT has a child-table fan-out that breaks the wide-row assumption; CBCT and
  Planar have non-conforming columns (`SliceWidthDifference`, `*Roi`) that need
  special handling. Each Pattern-B type needs its own `METRICS` dict + edge cases.
- **A4 — Single `myqa_numeric` list.** Rejected per D1: conflicts with the
  frozen main spec's `myqa_daily_physics` / `myqa_daily_constancy` and would
  merge Constancy + Physics data into one list.
- **A5 — Store PassFail as boolean.** Rejected per D3: `PassStatus` column
  doesn't exist; only `AcceptanceCriteria` text is available.
- **A6 — Extend `setup_myqa_tests.py`.** Rejected per D2: the Numeric path is
  triple-broken and non-Numeric is stub-skipped. Needs rewrite + new code paths.

## Cross-module data flow

```
[one-shot setup]
setup_myqa_tests.py
  ├─ Numeric:  SELECT DISTINCT tcne.Name + tolerance cols (corrected query)
  ├─ Pattern B (MLC/CBCT/Planar): iterate static METRICS dict
  ├─ Pattern C (VMAT): static parent + SELECT DISTINCT child.Name
  ├─ Pattern D (WL/PassFail): hardcoded slug list
  └─ creates: TestList, Test, Tolerance (where applicable), TestListMembership, UnitTestCollection

[per-import run]
myqa_import.py engine
  ├─ query_new_sessions(task_name_patterns, device)  → list of execution_ids
  │     (this is where TaskName LIKE + RadiationDevice filtering happens)
  ├─ for each execution_id:
  │     extract_results(execution_id)  → list of (test_slug, value, verdict, tolerance?)
  └─ engine writes TestListInstance + TestInstance rows keyed by slug
```

Key invariant: **task-name and device filtering happens in `query_new_sessions`,
NOT in `extract_results`.** `extract_results` is always scoped to one
`execution_id`. Design/specs that show `TaskName LIKE` inside `extract_results`
are wrong.

## Open questions

1. **MLC `LineDistanceAcceptanceCriterion_*` / `LineSlopeAcceptanceCriterion_*`
   (schema-reference.md:145-146)** — listed as warn/fail values with no
   corresponding `_Result_Value_Value`. Are these tolerance-only (no metric), or
   is there a paired result column not captured? Needs confirmation before MLC
   `METRICS` is finalized.
2. **CBCT/Planar non-conforming columns** (`SliceWidthDifference_Value`,
   `MaxHuDeviationRoi`, `MinUniformityRoi`, `EnergyType`, `EnergyValue`) —
   confirm which get their own test slug vs. which are pure metadata. Current
   assumption above: only `SliceWidthDifference` gets a slug; rest are metadata.
3. **VMAT ROI `Name` slugification** — values like `[2.0 cm/s]`, `[111 MU/min]`
   contain brackets, slashes, units. Confirm slugify rules (strip brackets?
   replace `/`? keep units?).
4. **`IsDeleted` flag** on `MQA_TestExecutions` — should importers filter
   `WHERE IsDeleted = 0`? Current engine does not. Silent inclusion risk.
5. **Profile QIE trailing-space columns** (schema-reference.md "Profile QIE
   Trailing Spaces") — confirm the working Profile importer already bracket-quotes
   them. Out of scope but worth a one-line check.
6. **Energy/Wedge/Output** — out of scope per proposal, but their tolerance
   columns differ (`WarningTolerance`/`ErrorTolerance` for Energy/Output;
   `Tolerance_Warn`/`Tolerance_Fail` for Wedge, unverified). If the change
   touches the shared `get_or_create_tolerance` helper, ensure no regression.

## Status

- This brief is the baseline for Round 2 proposal revision.
- Frozen artifacts: **none**.
- Next: revise `proposal.md` (per D1–D4), then send to `@openspec-reviewer`.
