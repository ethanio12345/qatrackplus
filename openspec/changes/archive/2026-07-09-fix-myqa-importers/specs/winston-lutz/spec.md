# Winston Lutz Import

> Implements Pattern D (direct simple columns) per `design.md`. Two fixed
> metrics from direct columns; the 2-metric set is exhaustive (direct columns,
> not denormalized).

## Requirements

### R1: Column mapping

The system SHALL read from `MQA_IsoCheck_WinstonLutz_TestExecutions`:

| myQA column | Test slug |
|---|---|
| `MaximumDeviation2D` | `myqa_winston_lutz_max_deviation_2d` |
| `Deviation3D` | `myqa_winston_lutz_deviation_3d` |

These two are exhaustive — they are direct columns on the table (not
denormalized via a `Name`/`DisplayName` row scan, which the existing broken
code at `myqa_import.py:547` assumed).

### R2: JOIN path (standard, filter te.TaskExecutionId)

```sql
SELECT wl.MaximumDeviation2D, wl.Deviation3D,
       wl.Tolerance_Warn, wl.Tolerance_Fail
FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

### R3: Tolerance (two-sided, shared)

The system SHALL create ONE shared Tolerance from `Tolerance_Warn` /
`Tolerance_Fail` applied to both metrics. WL has no `LimitTendency` column →
assume `LimitTendency=0` (two-sided absolute). Tolerance is created during
setup only; `pass_fail` on TestInstance is `no_tol` (D4 deferred).

## Scenarios

**Scenario: Winston Lutz import (happy path)**

- GIVEN a WinstonLutz execution with MaximumDeviation2D=0.52,
  Deviation3D=0.61, Tolerance_Warn=1.0, Tolerance_Fail=2.0
- WHEN imported
- THEN `myqa_winston_lutz_max_deviation_2d` SHALL have value=0.52
- AND `myqa_winston_lutz_deviation_3d` SHALL have value=0.61
- AND pass_fail SHALL be `no_tol` for both

**Scenario: Setup creates shared tolerance**

- GIVEN Tolerance_Warn=1.0, Tolerance_Fail=2.0
- WHEN setup runs
- THEN a Tolerance SHALL be created with type=absolute, tol_low=-1.0,
  tol_high=1.0, act_low=-2.0, act_high=2.0
- AND both WL Tests SHALL reference it

**Scenario: NULL deviation value**

- GIVEN a WinstonLutz execution where Deviation3D IS NULL
- WHEN imported
- THEN `myqa_winston_lutz_deviation_3d` SHALL be created with value=None
- AND `myqa_winston_lutz_max_deviation_2d` SHALL still be created with its value

**Scenario: Empty result set**

- GIVEN an execution_id with no row in `MQA_IsoCheck_WinstonLutz_TestExecutions`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances

**Scenario: NULL tolerance in setup**

- GIVEN a WinstonLutz setup where both Tolerance_Warn IS NULL and
  Tolerance_Fail IS NULL
- WHEN setup creates the Tests
- THEN `get_or_create_tolerance` SHALL return None (per `setup_myqa_tests.py:36-37`)
- AND both WL Tests SHALL be created with no Tolerance
