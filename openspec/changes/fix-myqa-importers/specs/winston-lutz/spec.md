# Winston Lutz Import

## Requirements

### R1: Column mapping

The system SHALL read from `MQA_IsoCheck_WinstonLutz_TestExecutions`:

| myQA column | Test slug |
|---|---|
| `MaximumDeviation2D` | `myqa_winston_lutz_max_deviation_2d` |
| `Deviation3D` | `myqa_winston_lutz_deviation_3d` |

### R2: Tolerance columns

The system SHALL use `Tolerance_Warn` and `Tolerance_Fail` columns
directly from the table for tolerance creation.

## Scenarios

**Scenario: Winston Lutz import**

GIVEN a WinstonLutz execution with MaximumDeviation2D=0.52, Deviation3D=0.61,
Tolerance_Warn=1.0, Tolerance_Fail=2.0
WHEN imported
THEN two TestInstances SHALL be created with the respective values
AND a Tolerance SHALL be created with tol_low=-1.0, tol_high=1.0,
act_low=-2.0, act_high=2.0
