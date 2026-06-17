# Design: Fix myQA Importers

## Architecture

The fix is entirely within the existing import engine. No new classes or
entry points needed — only query rewrites and metric-to-test mappings.

```
┌─────────────────────────────┐
│    myqa_import.py           │
│                             │
│  MyqaNumericImport          │── Fix query (remove bad JOIN)
│  MyqaPassFailImport         │── Read AcceptanceCriteria
│  MyqaProfileImport          │── Already OK (enhance Warn/Fail)
│  MyqaEnergyImport           │── Already OK
│  MyqaWedgeImport            │── Already OK
│  MyqaOutputImport           │── Already OK
│  MyqaMlcImport              │── Rewrite: 6 metrics from denormalized columns
│  MyqaCbctImport             │── Rewrite: 10+ metrics
│  MyqaPlanarImport           │── Rewrite: 7 metrics
│  MyqaVmatImport             │── Rewrite: 3 metrics
│  MyqaWinstonLutzImport      │── Rewrite: 2 metrics directly
└─────────────────────────────┘
```

## Numeric Fix

### Current (broken)
```python
cursor.execute("""
    SELECT tc.Name, tcne.Actual, tcne.WarningTolerance, ...
    FROM MQA_Numeric_TestConditionExecutions tcne
    JOIN MQA_TestConditions tc ON tcne.TestCondition_Id = tc.Id  -- TABLE MISSING
    ...
""")
```

### Fixed
```python
cursor.execute("""
    SELECT tcne.Name, tcne.Actual, tcne.WarnOn, tcne.FailOn,
           tcne.LimitTendency, tcne.IsRelative
    FROM MQA_Numeric_TestConditionExecutions tcne
    JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
    JOIN MQA_TestExecutions te ON tie.Id = te.Id
    WHERE te.TaskName LIKE %s AND te.RadiationDeviceName = %s
""")
```

## Denormalized Metric Extraction

For MLC, CBCT, Planar, VMAT: iterate known metric prefix columns and
dynamically extract value + tolerance pairs.

```python
METRICS = {
    'myqa_mlc': {
        'test_result': ('TestResult', None, None),
        'failing_peaks': ('FailingPeaks_Result_Value_Value',
                          'FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value',
                          'FailingPeaks_AcceptanceCriterion_Tolerances_Fail_Value'),
        ...
    }
}
```

## Tolerance Handling

All types use the same `get_or_create_tolerance` helper from setup command:

```python
def get_or_create_tolerance(warn_on, fail_on, is_relative, limit_tendency):
    if limit_tendency == 0:  # two-sided
        tol_low = -warn_on; tol_high = +warn_on
        act_low = -fail_on; act_high = +fail_on
    elif limit_tendency == 1:  # lower-only
        tol_low = -fail_on; tol_high = None
    elif limit_tendency == 2:  # upper-only
        tol_low = None; tol_high = fail_on
```

## Backfill Plan

After each importer is fixed:

1. `setup_myqa_tests --force` (creates TestList/Test/UTC/Tolerance)
2. `import_myqa --task <type> --days 365`
3. Run a second time to verify dedup (0 new imports)
