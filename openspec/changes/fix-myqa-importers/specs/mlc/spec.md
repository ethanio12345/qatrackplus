# MLC Import

## Requirements

### R1: Denormalized metric mapping

The system SHALL extract each metric column from `MQA_MDL_MlcQA_Results` as a
separate test. Use the `_AcceptanceCriterion_Tolerances_Warn/Fail_Value` columns
for tolerance setup.

| Metric column | Test slug |
|---|---|
| `TestResult` | `myqa_mlc_test_result` |
| `TotalPeaks` | `myqa_mlc_total_peaks` |
| `LeavesThatFailed` | `myqa_mlc_leaves_failed` |
| `FailingPeaks_Result_Value_Value` | `myqa_mlc_failing_peaks` |
| `MaximumDeviation_Result_Value_Value` | `myqa_mlc_max_deviation` |
| `InterstripRatio_Result_Value_Value` | `myqa_mlc_interstrip_ratio` |
| `StandardDeviation_Result_Value_Value` | `myqa_mlc_standard_deviation` |
| `IsocenterToStripDistance_Result_Value_Value` | `myqa_mlc_isocenter_to_strip` |

### R2: JOIN path

The system SHALL use the JOIN path:
`MlcQATestExecutionBase_Id → MQA_TestImplementationExecutions.Id → MQA_TestExecutions.Id`

## Scenarios

**Scenario: MLC metric extraction**

GIVEN a row with FailingPeaks_Result_Value_Value=3,
MaximumDeviation_Result_Value_Value=0.42
WHEN imported
THEN `myqa_mlc_failing_peaks` SHALL have value=3
AND `myqa_mlc_max_deviation` SHALL have value=0.42
