# MLC Import

> Implements Pattern B (denormalized wide-row) per `design.md`. Five metric
> prefixes with the full 4-tuple column structure, plus three non-conforming
> columns handled separately.

## Requirements

### R1: METRICS dict (5 prefixes + STRING_COLS)

The system SHALL extract each metric via a static `METRICS` dict. Each prefix
has the standard 4-tuple: `{P}_Result_Value_Value`, `{P}_Result_Verdict`,
`{P}_AcceptanceCriterion_Tolerances_Warn_Value`,
`{P}_AcceptanceCriterion_Tolerances_Fail_Value`.

| Prefix | Test slug |
|---|---|
| `FailingPeaks` | `myqa_mlc_failing_peaks` |
| `MaximumDeviation` | `myqa_mlc_max_deviation` |
| `InterstripRatio` | `myqa_mlc_interstrip_ratio` |
| `StandardDeviation` | `myqa_mlc_standard_deviation` |
| `IsocenterToStripDistance` | `myqa_mlc_isocenter_to_strip_distance` |

Non-conforming columns (separate `STRING_COLS` handling):

| Column | Test slug | Handling |
|---|---|---|
| `TestResult` | (none) | verdict-only → logged, no TestInstance emitted |
| `TotalPeaks` | `myqa_mlc_total_peaks` | value-only (no tolerance) |
| `LeavesThatFailed` | `myqa_mlc_leaves_that_failed` | nvarchar → stored as `string_value` |

`LineDistanceAcceptanceCriterion_*` and `LineSlopeAcceptanceCriterion_*` are
excluded (tolerance-only orphans, no paired `_Result_Value_Value`; O1). Add at
implementation time if a paired result column is found.

### R2: JOIN path (extra hop, filter te.TaskExecutionId)

The system SHALL use the MLC-specific JOIN chain with the extra hop through
`MQA_MDL_MlcQA_TestExecutions`, and filter on `te.TaskExecutionId`:

```sql
SELECT r.<metric cols>, r.TestResult, r.TotalPeaks, r.LeavesThatFailed
FROM MQA_MDL_MlcQA_Results r
JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

This replaces the existing broken path via `MQA_MDL_MlcQA_QueueItemExecutions`
(`myqa_import.py:446-448`), which is not in the verified schema.

### R3: Setup creates Test + UTI for every emitted slug (per D2)

Setup SHALL create a Test (and UnitTestInfo per unit) for **every slug the
importer emits** — not just the tolerance-bearing prefixes. The engine silently
drops TestInstances for slugs lacking a Test (`myqa_import.py:209-211`).
Specifically setup creates:
- 5 prefix Tests (`myqa_mlc_failing_peaks`, etc.) — each with Tolerance where
  `warn_col`/`fail_col` are present, via `get_or_create_tolerance(warn, fail,
  is_relative=False, limit_tendency=0)`
- `myqa_mlc_total_peaks` — type=`numerical`, value-only, no Tolerance
- `myqa_mlc_leaves_that_failed` — type=`string`, no Tolerance

No discovery query (no `Name` column on `MQA_MDL_MlcQA_Results`). The Test.type
matters: the engine uses `isinstance(val, str)` (`myqa_import.py:219-220`) to
route to `string_value` vs `value`, so `LeavesThatFailed` MUST be `string`.

## Scenarios

**Scenario: MLC metric extraction (happy path)**

- GIVEN an MLC execution with FailingPeaks_Result_Value_Value=3,
  MaximumDeviation_Result_Value_Value=0.42,
  FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value=5,
  FailingPeaks_AcceptanceCriterion_Tolerances_Fail_Value=10
- WHEN imported
- THEN `myqa_mlc_failing_peaks` SHALL have value=3
- AND `myqa_mlc_max_deviation` SHALL have value=0.42
- AND pass_fail SHALL be `no_tol` for both (D4 verdict storage deferred)

**Scenario: LeavesThatFailed stored as string**

- GIVEN an MLC execution with LeavesThatFailed=`A1, A2, B15`
- WHEN imported
- THEN `myqa_mlc_leaves_that_failed` SHALL be created with
  string_value=`A1, A2, B15` (via `myqa_import.py:220` isinstance branch)

**Scenario: NULL metric value**

- GIVEN an MLC execution where MaximumDeviation_Result_Value_Value IS NULL
- WHEN imported
- THEN `myqa_mlc_max_deviation` SHALL be created with value=None
- AND no exception SHALL be raised

**Scenario: Missing tolerance column in setup**

- GIVEN setup is processing MLC and a metric prefix lacks
  `_AcceptanceCriterion_Tolerances_Warn_Value` (column absent or NULL)
- WHEN setup creates the Test
- THEN the Test SHALL be created with no Tolerance (Tolerance is optional)

**Scenario: TestResult verdict-only**

- GIVEN an MLC execution with TestResult=40 (Pass per verdict encoding)
- WHEN imported
- THEN no TestInstance SHALL be emitted for TestResult (verdict-only, logged)
- AND the value 40 MAY be written to the import log for diagnostics

**Scenario: Empty result set**

- GIVEN an execution_id with no row in `MQA_MDL_MlcQA_Results`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances
