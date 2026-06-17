# Explore Brief: Full myQA Sync

> Written retroactively after the first review round to serve as the
> completeness checklist for the proposal/design/specs/tasks artifacts.
> All decisions below are RESOLVED (confirmed by the maintainer on
> 2026-06-17) and are binding on every artifact in this change.

## Context

This change extends an existing, proven import pattern — `qatrack/matrix_import.py`
(class `MatrixResultImporter`, fn `import_matrix_results`) — which imports monthly
dosimetry matrix data from myQA (MSSQL, read-only) into QATrack+. The extension
covers every remaining myQA task type × frequency for all linacs and the DXR unit.

The plan was originally generated against the production myQA DB, so all myQA table
names, field names, and the unit/linac inventory stated in the proposal are treated
as authoritative. The QATrack+ side, by contrast, must conform to the actual ORM
models and evaluation logic (verified against `qatrack/qa/models.py`).

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Write to myQA DB | Never. All myQA access is strictly read-only. |
| Real-time / sub-daily import | Out of scope. Daily batch is sufficient. |
| Per-list de-dup key (`myqa_{list_slug}_taskid`) | Adds ~20 hidden Test objects for no benefit; diverges from the proven single-slug pattern. Use one shared slug instead. |
| Stateful "last successful import" tracker | Adds a table + failure-mode complexity. Stateless `--days N` + idempotent de-dup is simpler and tolerates a missed day. |
| Keep `import_myqa_results(META)` UI entry point | Orphaned (no view wiring). The django-q admin "Run" button already covers manual triggering per the spec. |
| Rewriting `matrix_import.py` from scratch | Too risky. Consolidation is limited to routing the monthly matrix task type through the new engine + deprecating its standalone command. |
| Removing existing manual test lists | Non-goal. New automated lists live alongside them. |

## Verified QATrack+ model facts (binding)

- **myQA connection library**: `pymssql` (NOT pyodbc). Existing usage at
  `matrix_import.py:16,130-135`.
- **myQA connection settings**: `MYQA_DB_SERVER`, `MYQA_DB_NAME`,
  `MYQA_DB_USERNAME`, `MYQA_DB_PASSWORD` — defined externally as env vars
  (NOT in `settings.py`). Both old and new importers rely on them.
- **Existing importer class**: `MatrixResultImporter` (`matrix_import.py:34`),
  entry point `import_matrix_results(META)` (`matrix_import.py:532`). There is
  NO `MyqaSessionCollector` class anywhere — that name was a fabrication in the
  original design.md.
- **Tolerance model** (`qa/models.py:674-743`): fields are `type`, `act_low`,
  `tol_low`, `tol_high`, `act_high` (plus `mc_*` and `bool_warning_only` for
  non-numeric types). There are NO `*_cmp` operator fields and NO
  `tol_lower`/`tol_upper` fields.
- **`TOL_TYPE_CHOICES`** (`models.py:85-89`): `"absolute"`, `"percent"`,
  `"multchoice"`. (A 4th `"boolean"` type exists in data but is not form-creatable
  and irrelevant here.)
- **Pass/fail evaluation** (`TestInstance.float_pass_fail`, `models.py:2137-2157`):
  tolerance values are **offsets from the reference value**. The engine stores
  TWO bands:
  - `OK` (pass) when `tol_low <= diff <= tol_high`
  - `TOLERANCE` (warn) when inside action band but outside tolerance band
  - `ACTION` (fail) when outside action band
  - `diff = value - reference` (absolute) or `100*(value-ref)/ref` (percent).
  - Unset bounds default to ±1E99 (inclusive comparison with float `almost_equal`).
- **Percent base** = `TestInstance.reference.value` (the `Reference` FK's value).
- **`PASS_FAIL_CHOICES`** (`models.py:98-122`): `not_done`, `ok`, `tolerance`,
  `action`, `no_tol`. The existing importer sets `pass_fail='no_tol'` because it
  does not attach a reference/tolerance at import time.
- **Frequency** (`qa/models.py:373`, fixture `fixtures/defaults/qa/frequencies.json`):
  model-based, keyed by slug. Relevant slugs: `daily`, `weekly`, `monthly`,
  `semi-annual`, `annual`.
- **Unit numbering** (`units/models.py:234`): `Unit.number` PositiveIntegerField,
  unique. Existing map (proposal treats this as authoritative on production):
  8 linac units + 1 DXR unit = 9 units total. (Static code snapshot shows 7 linac
  numbers `1,2,3,4,5,7,8` + DXR `50`; the 8th linac is a production-data fact
  resolved at apply time.)
- **TestList #133**: hardcoded in `tasks.py:49` as the existing monthly matrix
  test list. Name per proposal: "Monthly Matrix Dosimetry Import".

## Resolved design decisions (binding)

| # | Decision | Value |
|---|---|---|
| D1 | De-dup key | Single shared QATrack+ `Test` slug `mtx_taskid` (existing) generalized to `myqa_taskid` for non-matrix task types. Value stored in `TestInstance.string_value` = the myQA `TaskExecutionId` (an integer, cast to `str`). NOT a UUID. |
| D2 | Slug dot handling | Strip dots. Regex `[^a-z0-9]+` → `_`. So `1.01 6MV Output` → `myqa_daily_physics_1_01_6mv_output`. |
| D3 | Main spec vs delta | `openspec/specs/myqa-sync/spec.md` describes **current** behavior only (monthly matrix import). All forward-looking content lives in the change delta. |
| D4 | Incremental tracking | Stateless. Daily cron uses `--days 2` default (idempotent + de-dup tolerates overlap). `--days` is the only lookback control. |
| D5 | Timezone | Schedule at 18:00 in `Australia/Sydney` (django-q handles AEST/AEDT DST). |
| D6 | Percent base | myQA `IsRelative=1` → `type="percent"`, base = the `Reference.value` attached to each `TestInstance`. |
| D7 | UI entry point | Drop `import_myqa_results(META)`. Manual trigger = django-q admin "Run" button only. |
| D8 | Tolerance mapping | `WarnOn → tol_*`, `FailOn → act_*`. See full table below. |
| D9 | myQA library | `pymssql` |
| D10 | myQA tables | All 11 referenced tables assumed correct (generated from production). |

## Tolerance mapping table (D8)

myQA fields: `WarnOn` (W), `FailOn` (F), `IsRelative`, `LimitTendency`
(0=two-sided, 1=lower-only, 2=upper-only). QATrack+ offsets are relative to the
reference value; a positive offset means the value may rise that much above
reference and still pass.

| `IsRelative` | `LimitTendency` | `type` | `tol_low` | `tol_high` | `act_low` | `act_high` |
|---|---|---|---|---|---|---|
| 0 | 0 (two-sided) | `absolute` | `-W` | `+W` | `-F` | `+F` |
| 0 | 1 (lower-only) | `absolute` | `-W` | `None` | `-F` | `None` |
| 0 | 2 (upper-only) | `absolute` | `None` | `+W` | `None` | `+F` |
| 1 | 0 (two-sided) | `percent` | `-W` | `+W` | `-F` | `+F` |
| 1 | 1 (lower-only) | `percent` | `-W` | `None` | `-F` | `None` |
| 1 | 2 (upper-only) | `percent` | `None` | `+W` | `None` | `+F` |

Evaluation (QATrack+ engine, automatic): `diff = value - reference` (absolute) or
`100*(value-ref)/ref` (percent); `OK` if inside tol band, `TOLERANCE` if inside act
band but outside tol band, `ACTION` if outside act band. Unset bounds = ±1E99.

## Cross-module data flow

```
django-q Schedule (18:00 Australia/Sydney, DAILY)
        │  or: `manage.py import_myqa --task <t> --unit <u> --days <d>`
        ▼
import_myqa_all(days=2)             [qatrack/qa/tasks.py]   (cron entry point)
  OR: `manage.py import_myqa ...`     [management command, Task 7]
        │
        ▼
MyqaImportBase subclass (per execution type)   [qatrack/myqa_import.py]
        │
        ├─ pymssql.connect(MYQA_DB_*)  ── read-only query ──► myQA MSSQL
        │      header:  MQA_TestExecutions  (date-bounded, device-name filter,
        │                                    NOT EXISTS de-dup subquery)
        │      detail:  per-handler table (11 variants)
        │
        ├─ unit_number → device-name map   (mirror matrix_import.py:386-400)
        │
        ├─ duplicate_check(): lookup TestInstance where
        │      unit_test_info__test__slug = 'myqa_taskid' (or 'mtx_taskid')
        │      AND unit_test_info__unit__number = <unit>
        │      AND string_value = str(TaskExecutionId)
        │
        └─ import_session(): per-session transaction.atomic()
               ├─ create TestListInstance (unit_test_collection, test_list, day)
               ├─ bulk_create TestInstance[]  (pass_fail='no_tol' — no ref/tol at import)
               └─ create one de-dup TestInstance (string_value = TaskExecutionId)

QATrack+ ORM  [qatrack/qa/models.py]
   Test / TestList / TestListMembership / Tolerance / UnitTestCollection /
   UnitTestInfo / TestListInstance / TestInstance / Frequency / Reference
```

Setup (one-time) flow, separate from import:

```
manage.py setup_myqa_tests --dry-run   [qatrack/qa/management/commands/setup_myqa_tests.py]
        │
        ├─ query myQA DISTINCT test names per task type
        ├─ myqa_name_to_slug(list_slug, name)  → Test.slug ('myqa_'-prefixed)
        ├─ myqa_to_qatrack_tolerance(...)      → Tolerance (table D8)
        ├─ create Test + TestList + TestListMembership
        ├─ create UnitTestCollection per (unit, frequency)
        └─ create the single de-dup Test (slug 'myqa_taskid' / reuse 'mtx_taskid')
```

## Task-to-handler registry (11 execution types)

Each maps a myQA task-name pattern → handler class → detail table. Per D10 these
table names are authoritative.

| Execution type | Handler class | Detail table |
|---|---|---|
| Numeric | `MyqaNumericImport` | `MQA_Numeric_TestConditionExecutions` |
| PassFail | `MyqaPassFailImport` | `MQA_PassFail_TestExecutions` |
| Profile | `MyqaProfileImport` | `MQA_Dosimetry_Profile_Results` |
| Energy | `MyqaEnergyImport` | `MQA_Dosimetry_Energy_ChamberExecutions` |
| Wedge | `MyqaWedgeImport` | `MQA_Dosimetry_Wedge_QueueItemExecutions` |
| Output | `MyqaOutputImport` | `MQA_Dosimetry_Output_QueueItemExecutions` |
| MLC | `MyqaMlcImport` | `MQA_MDL_MlcQA_Results` |
| CBCT | `MyqaCbctImport` | `MQA_MDL_Cbct_Results` |
| Planar | `MyqaPlanarImport` | `MQA_MDL_Planar_Results` |
| VMAT | `MyqaVmatImport` | `MQA_MDL_VmatDmlc_Results` |
| WinstonLutz | `MyqaWinstonLutzImport` | `MQA_IsoCheck_WinstonLutz_TestExecutions` |

## Open questions

None. All blocking questions resolved with the maintainer on 2026-06-17.
