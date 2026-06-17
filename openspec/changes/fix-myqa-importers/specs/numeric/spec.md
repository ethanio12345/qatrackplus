# Numeric (Daily QA) Import

## Requirements

### R1: Direct table query

The system SHALL query `MQA_Numeric_TestConditionExecutions` directly (not via
the non-existent `MQA_TestConditions` table) using the JOIN path:
`NumericTestExecution_Id → MQA_TestImplementationExecutions.Id → MQA_TestExecutions.Id`

### R2: Column mapping

The system SHALL read these columns directly:

| myQA column | Purpose |
|---|---|
| `Name` | Test name → slug via `slugify_name` |
| `Actual` | Test value |
| `WarnOn` | Tolerance warning level |
| `FailOn` | Tolerance action level |
| `LimitTendency` | 0=two-sided, 1=lower-only, 2=upper-only |
| `IsRelative` | True=percent tolerance, False=absolute |

### R3: Task name patterns

The system SHALL filter by task names matching `5.Tmt.Linac.D%` and
`5.Tmt.DXR.D%` for daily constancy checks.

## Scenarios

**Scenario: Numeric daily QA import**

GIVEN a Numeric execution with Name `1.05 18MV Output`, Actual=0.03,
WarnOn=0.015, FailOn=0.02, LimitTendency=0, IsRelative=False
WHEN imported
THEN a TestInstance SHALL be created with value=0.03
AND a Tolerance SHALL be created with type=absolute, tol_low=-0.015, tol_high=0.015
