# Proposal: Fix myQA Importers

Correct the broken SQL importers in `myqa_import.py` against the verified myQA
database schema (see `schema-reference.md`), and rewrite `setup_myqa_tests.py`
to backfill test lists, tests, tolerances, and unit collections for all
previously-broken execution types.

## Background

The `full-myqa-sync` change shipped a generic import engine but assumed table
and column names that do not match the actual production myQA database. Only
the Profile (matrix dosimetry) importer works. A verified schema dump
(`schema-reference.md`) confirms that every other importer and the shared setup
command query non-existent tables and columns:

- `MQA_TestConditions` does not exist; `Name` lives directly on
  `MQA_Numeric_TestConditionExecutions`.
- Numeric tolerances are `WarnOn` / `FailOn`, not the `WarningTolerance` /
  `ErrorTolerance` the setup command reads.
- MLC's foreign key goes through `MQA_MDL_MlcQA_TestExecutions`, not directly
  to the bridge table.
- CBCT/Planar/VMAT share their `Id` UUID with their parent execution (no
  separate FK column).
- VMAT measured values for ROI metrics live in a child table,
  `MQA_MDL_VmatDmlc_RoiResults`, not on the parent wide row.
- PassFail has only `AcceptanceCriteria` text; there is no `PassStatus` column.
- `setup_myqa_tests.py:148-150` explicitly `SKIP`s every non-Numeric type, so
  there is no extension surface — setup must be rewritten per type.

## Data Volumes

| Type | Sessions | Priority | Status |
|---|---|---|---|
| Numeric (daily QA) | 3,670 | High | Broken — wrong task-name pattern + triple-broken setup query |
| Winston Lutz | 400 | Medium | Broken — assumed wrong JOIN shape |
| MLC | 252 | Medium | Broken — wrong FK chain |
| VMAT | 247 | Medium | Broken — child-table fan-out not modelled |
| CBCT | 46 | Low | Broken — table/column names unverified, now known |
| Planar | 4 | Low | Broken — table/column names unverified, now known |
| PassFail | (n/a) | Low | Broken — `PassStatus` column does not exist |
| Profile (matrix) | 534 | — | Working — out of scope |
| Energy / Wedge / Output | — | — | Out of scope — not re-verified in this change (their QueueItem/Chamber tables aren't in `schema-reference.md`) |

## Decisions (from `explore-brief.md`)

- **D1 — Numeric split (3-way).** Numeric executions live under three daily
  task names that map to the existing main-spec lists:
  - `5.Tmt.Linac.D` (Constancy) → `myqa_daily_constancy` (Linac units 1–8)
  - `5.Tmt.Linac.D2` (Physics) → `myqa_daily_physics` (Linac units 1–8)
  - `5.Tmt.DXR.D` (DXR Constancy) → `myqa_dxr_daily` (DXR unit 50)

  The previously-proposed `myqa_numeric` slug is removed; this resolves the
  slug conflict with the frozen `myqa-sync` main spec and reconciles the DXR
  mapping that the 2-way version of D1 missed.
- **D2 — Setup rewrite.** The current Numeric setup query
  (`setup_myqa_tests.py:77-87`) is broken in three places and the command
  explicitly `SKIP`s every non-Numeric type (`:148-150`). The setup command is
  rewritten per type, not extended.
- **D3 — PassFail.** Only `AcceptanceCriteria` text is available; stored as
  `string_value`. There is no boolean pass/fail to import.
- **D4 — Verdict.** Importers read the source `*_Verdict` columns
  (encoding 0/10/30/40/50/60) for diagnostic logging during import. The current
  engine hardcodes `pass_fail='no_tol'` (`myqa_import.py:226`) and has no field
  to store source verdicts; verdict **storage** is deferred to a future engine
  enhancement and is out of scope for this change. *(Soft-freeze amendment: D4
  originally said "read verdict directly"; clarified after source review showed
  the engine cannot store verdicts without a write-path modification that is
  not part of this change.)*

## Scope

### Files Affected

| File | Action |
|---|---|
| `qatrack/myqa_import.py` | Rewrite SQL in 7 importers against the verified schema |
| `qatrack/qa/management/commands/setup_myqa_tests.py` | Rewrite per-type setup paths (Numeric fix + 6 new) |

### In scope (7 importers)

| Importer | Pattern (per `explore-brief.md`) |
|---|---|
| Numeric | A — dynamic row-per-condition, split into 3 existing lists (constancy/physics/dxr) |
| WinstonLutz | D — direct columns, 2 fixed metrics |
| MLC | B — denormalized wide-row, 5 metric prefixes |
| CBCT | B — denormalized wide-row, 9 metric prefixes |
| Planar | B — denormalized wide-row, 7 metric prefixes |
| VMAT | C — hybrid: parent wide-row + child-table fan-out |
| PassFail | D — single text field, no tolerance |

### Non-goals

- Profile, Energy, Wedge, Output importers — already working, untouched.
- Refactoring the shared import engine (`query_new_sessions`,
  `extract_results` base class).
- Backfilling historical data beyond what the engine's incremental
  `query_new_sessions` already supports.
- Filtering by the `IsDeleted` flag on `MQA_TestExecutions` — tracked as open
  question O4 in `explore-brief.md`, deferred.
- Cleanup of data created by the broken `full-myqa-sync` engine — setup never
  successfully created the `myqa_numeric` TestList (its query was triple-broken),
  so the engine's `TestList.objects.get(slug=...)` (`myqa_import.py:174`) would
  have raised `DoesNotExist`; no TestListInstance/TestInstance data is expected
  to exist. Verify in production before running `setup_myqa_tests --force`.

## Open questions (deferred to design / specs)

The six open questions in `explore-brief.md` (MLC tolerance-only columns,
CBCT/Planar non-conforming columns, VMAT ROI slugification, `IsDeleted`,
Profile trailing-space quirk, Energy/Wedge tolerance regression risk) are
answered or referenced in `design.md` and the per-type spec files.
