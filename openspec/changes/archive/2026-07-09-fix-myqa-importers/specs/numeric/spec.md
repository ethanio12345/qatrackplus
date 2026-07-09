# Numeric (Daily QA) Import

> Implements Pattern A (dynamic row-per-condition) per `design.md`. Three
> importers share `MyqaNumericImportBase`; each targets one list per D1.

## Requirements

### R1: Direct table query, per-execution

The system SHALL query `MQA_Numeric_TestConditionExecutions` directly (not via
the non-existent `MQA_TestConditions` table). The query SHALL JOIN through
`MQA_TestImplementationExecutions` and `MQA_TestExecutions`, and filter on
`te.TaskExecutionId = %s` (the execution_id passed by the engine — NOT `te.Id`).

```sql
SELECT tcne.Name, tcne.Actual
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

### R2: Column mapping

The system SHALL read these columns. **Import** reads only `Name` and `Actual`.
**Setup** additionally reads the tolerance columns.

| myQA column | Used in | Purpose |
|---|---|---|
| `Name` | import + setup | Test name → slug via `slugify_name(list_slug, Name)` |
| `Actual` | import | Test value |
| `WarnOn` | setup only | Tolerance warning level |
| `FailOn` | setup only | Tolerance action level |
| `LimitTendency` | setup only | 0=two-sided, 1=lower-only, 2=upper-only |
| `BoundingType` | setup only | Read but unused by `get_or_create_tolerance` (forward-compat) |
| `IsRelative` | setup only | True=percent, False=absolute |

### R3: Three-way list split (per D1)

The system SHALL route Numeric executions to three existing main-spec lists
based on task name. Each importer subclass sets one `task_name_pattern` (full
string, applied via `LIKE`):

| Importer | list_slug | task_name_pattern | Frequency |
|---|---|---|---|
| `MyqaNumericConstancyImport` | `myqa_daily_constancy` | `5.Tmt.Linac.D - myQA Daily Constancy Check` | daily |
| `MyqaNumericPhysicsImport` | `myqa_daily_physics` | `5.Tmt.Linac.D2 - Daily QA (Physics)` | daily |
| `MyqaNumericDxrImport` | `myqa_dxr_daily` | `5.Tmt.DXR.D - myQA Daily Constancy Check` | daily |

Full strings (not `.D%` prefixes) are used because `5.Tmt.Linac.D%` matches
both `.D` and `.D2` (the `%` swallows the `2 - Daily QA (Physics)` suffix).
The previously-proposed `myqa_numeric` slug SHALL NOT be created.

### R4: Setup discovery (per D2)

Setup SHALL discover test names via the corrected query (replaces the
triple-broken `setup_myqa_tests.py:77-87`):

```sql
SELECT DISTINCT tcne.Name, tcne.WarnOn, tcne.FailOn,
                tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName LIKE %s
```

Run once per `task_name_pattern`, writing into the respective list. Tolerance
via `get_or_create_tolerance` (unchanged helper).

## Scenarios

**Scenario: Numeric daily QA import (happy path)**

- GIVEN a Numeric execution with Name `1.05 18MV Output`, Actual=0.03
- WHEN imported into `myqa_daily_physics`
- THEN a TestInstance SHALL be created with slug
  `myqa_daily_physics_1.05_18mv_output` and value=0.03
- AND pass_fail SHALL be `no_tol` (engine default; D4 verdict storage deferred)

**Scenario: Setup creates tolerance from WarnOn/FailOn**

- GIVEN a Numeric condition with Name `1.01 6MV Output`, WarnOn=0.015,
  FailOn=0.02, LimitTendency=0, IsRelative=False
- WHEN setup runs for `myqa_daily_physics`
- THEN a Tolerance SHALL be created with type=absolute, tol_low=-0.015,
  tol_high=0.015, act_low=-0.02, act_high=0.02

**Scenario: NULL Actual value**

- GIVEN a Numeric condition row where Actual IS NULL
- WHEN imported
- THEN the engine SHALL store value=None (TestInstance with value=NULL)
- AND no exception SHALL be raised

**Scenario: Empty result set**

- GIVEN an execution_id with no rows in `MQA_Numeric_TestConditionExecutions`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances

**Scenario: LimitTendency out of range**

- GIVEN a Numeric condition with LimitTendency=9 (not 0/1/2)
- WHEN setup processes it
- THEN `get_or_create_tolerance` SHALL return None (per `setup_myqa_tests.py:56-57`)
- AND the Test SHALL be created with no Tolerance

**Scenario: Same Name across two lists**

- GIVEN a Numeric condition with Name `Output` exists under both
  `5.Tmt.Linac.D` and `5.Tmt.Linac.D2`
- WHEN setup runs for both lists
- THEN two distinct Tests SHALL be created: `myqa_daily_constancy_output` and
  `myqa_daily_physics_output` (slug prefix includes list_slug, so no collision)
