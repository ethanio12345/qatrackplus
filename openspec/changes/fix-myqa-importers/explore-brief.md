# myQA Schema Reference (Verified)

> Database: SQL Server (not Sybase). Verified via `pymssql` against production myQA DB.

## Table Inventory

### Execution-Type Tables

| Type | Table | FK/Result Link |
|------|-------|----------------|
| **Numeric** | `MQA_Numeric_TestConditionExecutions` | `NumericTestExecution_Id` -> `MQA_TestImplementationExecutions.Id` |
| **PassFail** | `MQA_PassFail_TestExecutions` | `Id` -> `MQA_TestImplementationExecutions.Id` |
| **Profile** | `MQA_Dosimetry_Profile_Results` | `ProfileQueueItemExecution_Id` -> `MQA_Dosimetry_Profile_QueueItemExecutions.Id` |
| **Energy** | `MQA_Dosimetry_Energy_TestExecutions` | `Id` -> `MQA_TestImplementationExecutions.Id` |
| **Wedge** | `MQA_Dosimetry_Wedge_TestExecutions` | `Id` -> `MQA_TestImplementationExecutions.Id` |
| **Output** | `MQA_Dosimetry_Output_TestExecutions` | `Id` -> `MQA_TestImplementationExecutions.Id` |
| **MLC** | `MQA_MDL_MlcQA_Results` | `MlcQATestExecutionBase_Id` -> `MQA_MDL_MlcQA_TestExecutions.Id` |
| **CBCT** | `MQA_MDL_Cbct_Results` | `Id` -> `MQA_MDL_Cbct_TestExecutions.Id` (same UUID) |
| **Planar** | `MQA_MDL_Planar_Results` | `Id` -> `MQA_MDL_Planar_TestExecutions.Id` (same UUID) |
| **VMAT** | `MQA_MDL_VmatDmlc_Results` | `Id` -> `MQA_MDL_VmatDmlc_TestExecutions.Id` (same UUID) |
| **WinstonLutz** | `MQA_IsoCheck_WinstonLutz_TestExecutions` | `Id` -> `MQA_TestImplementationExecutions.Id` |

### Common Tables

| Table | Purpose |
|-------|---------|
| `MQA_TestImplementationExecutions` | Bridge: all type-specific execution tables join here |
| `MQA_TestExecutions` | Root execution metadata (TaskName, FinishingDate, etc.) |
| `MQA_TaskExecutions` | Task-level metadata |
| `MQA_DefinitionsRoots` | Schema root |
| `MQA_ProtocolDefinitions` | Protocol definition |
| `UST_Units` | Unit settings (serialized JSON) |

## Join Paths

### Standard Pattern (most types)
```
<Type>_TestExecutions/Results
  JOIN MQA_TestImplementationExecutions tie ON <type>.Id = tie.Id
  JOIN MQA_TestExecutions te ON tie.Id = te.Id
```

### Numeric
```
MQA_Numeric_TestConditionExecutions tcne
  JOIN MQA_TestImplementationExecutions tie ON tcne.NumericTestExecution_Id = tie.Id
  JOIN MQA_TestExecutions te ON tie.Id = te.Id
```

### Profile (multi-table path)
```
MQA_Dosimetry_Profile_Results pr
  JOIN MQA_Dosimetry_Profile_QueueItemExecutions qie ON pr.ProfileQueueItemExecution_Id = qie.Id
  JOIN MQA_Dosimetry_Profile_TestExecutions pte ON qie.Id = pte.ProfileQueueItem_Id
  JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
  JOIN MQA_TestExecutions te ON tie.Id = te.Id
```

### MLC
```
MQA_MDL_MlcQA_Results r
  JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
  JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
  JOIN MQA_TestExecutions te ON tie.Id = te.Id
```

## Column Schemas

### MQA_Numeric_TestConditionExecutions
```
Id          uniqueidentifier PK
WarnOn      float   -- tolerance warning threshold
FailOn      float   -- tolerance error threshold
Actual      float   -- measured value
Expected    float   -- reference value
Name        nvarchar  -- condition name (e.g. "Field Width (crossline)")
NumericTestExecution_Id uniqueidentifier FK -> MQA_TestImplementationExecutions
LimitTendency, BoundingType, IsRelative, Dimension, State, RowVersion, TestConditionTemplateId
```

### MQA_PassFail_TestExecutions
```
Id                uniqueidentifier PK (also FK -> TIE)
AcceptanceCriteria nvarchar  -- text description, may be NULL
```

### MQA_Dosimetry_Profile_Results
```
Id                           uniqueidentifier PK
ProfileQueueItemExecution_Id uniqueidentifier FK -> MQA_Dosimetry_Profile_QueueItemExecutions
DisplayName                  nvarchar  -- metric name
Actual                       float
Expected                     float
Warn                         float  -- tolerance warning
Fail                         float  -- tolerance error
State, Dimension, ProfileDirection, RowVersion
```

### MQA_Dosimetry_Energy_TestExecutions
```
Id               uniqueidentifier PK (also FK -> TIE)
RadiationDeviceId uniqueidentifier
WarningTolerance  float  -- note: WarningTolerance, NOT WarnOn
ErrorTolerance    float  -- note: ErrorTolerance, NOT FailOn
InlineFieldSize, CrosslineFieldSize, IsAbsolute, GantryAngle
```

### MQA_Dosimetry_Output_TestExecutions
```
Id               uniqueidentifier PK (also FK -> TIE)
RadiationDeviceId uniqueidentifier
WarningTolerance  float
ErrorTolerance    float
InlineFieldSize, CrosslineFieldSize, IsAbsolute, GantryAngle
```

### MQA_Dosimetry_Wedge_TestExecutions
```
Id               uniqueidentifier PK (also FK -> TIE)
Tolerance_Warn    float  -- note: Tolerance_Warn, WarningTolerance, or WarnOn
Tolerance_Fail    float  -- note: Tolerance_Fail
Tolerance_Dimension, InlineFieldSize, CrosslineFieldSize, RadiationDeviceId
BeamQuality_EnergyValue, BeamQuality_EnergyDimension, GantryAngle
```

### MQA_MDL_MlcQA_Results
```
Id uniqueidentifier PK
MlcQATestExecutionBase_Id uniqueidentifier FK -> MQA_MDL_MlcQA_TestExecutions
FailingPeaks_Result_Value_Value                         float  -- failing leaf count
FailingPeaks_Result_Verdict                             int    -- pass/fail status
FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value  float  -- warn threshold
FailingPeaks_AcceptanceCriterion_Tolerances_Fail_Value  float  -- fail threshold
MaximumDeviation_Result_Value_Value                     float  -- max deviation in mm
MaximumDeviation_Result_Verdict                         int
MaximumDeviation_AcceptanceCriterion_Tolerances_Warn_Value  float
MaximumDeviation_AcceptanceCriterion_Tolerances_Fail_Value  float
TestResult                  int    -- overall test result
TotalPeaks                  float
LeavesThatFailed            nvarchar
MlcTolerance_Value, MlcTolerance_Dimension, GantryAngle_Value
InterstripRatio_* (same structure as FailingPeaks)
StandardDeviation_* (same structure)
IsocenterToStripDistance_* (same structure)
LineDistanceAcceptanceCriterion_* (warn/fail values)
LineSlopeAcceptanceCriterion_* (warn/fail values)
AreStripeNumbersMissmatched
```

### MQA_MDL_Cbct_Results
```
Id  uniqueidentifier PK (same UUID as MQA_MDL_Cbct_TestExecutions.Id)
ScalingDiscrepancy_Result_Value_Value  float
ScalingDiscrepancy_Result_Verdict      int
ScalingDiscrepancy_AcceptanceCriterion_Tolerances_Warn_Value  float
ScalingDiscrepancy_AcceptanceCriterion_Tolerances_Fail_Value  float
GeometricDistortion_* (same structure)
SpatialResolution_* (same structure)
OverallUniformity_* (same structure)
MinimumUniformity_* (same structure)
Contrast_* (same structure)
CNR_* (same structure)
MaxHuDeviation_* (same structure)
MeasuredSliceWidth_* (same structure)
SliceWidthDifference_Value, SliceWidthDifference_Dimension
MaxHuDeviationRoi, MinUniformityRoi, TestResult, EnergyType, EnergyValue
```

### MQA_MDL_Planar_Results
```
Id  uniqueidentifier PK (same UUID as MQA_MDL_Planar_TestExecutions.Id)
ScalingDiscrepancy_* (same structure as CBCT)
SpatialResolution_* (same structure)
MinimumUniformity_* (same structure)
Contrast_* (same structure)
CNR_* (same structure)
XOffset_Result_Value_Value, XOffset_Result_Verdict, XOffset_AcceptanceCriterion_Tolerances_Warn/Fail_Value
YOffset_Result_Value_Value, YOffset_Result_Verdict, YOffset_AcceptanceCriterion_Tolerances_Warn/Fail_Value
MinUniformityRoi, TestResult, EnergyType, EnergyValue
```

### MQA_MDL_VmatDmlc_Results
```
Id  uniqueidentifier PK (same UUID as MQA_MDL_VmatDmlc_TestExecutions.Id)
TestResult                          int
NormalizationValueResult_Verdict    int
NormalizationValueAcceptanceCriterion_ExpectedValue_Value  float
NormalizationValueAcceptanceCriterion_Tolerances_Warn_Value  float
NormalizationValueAcceptanceCriterion_Tolerances_Fail_Value  float
NormalizationValueResult_Value_Value   float
RoiMeanAcceptanceCriterion_Tolerances_Warn_Value   float
RoiMeanAcceptanceCriterion_Tolerances_Fail_Value   float
RoiStandardDeviationAcceptanceCriterion_Tolerances_Warn_Value  float
RoiStandardDeviationAcceptanceCriterion_Tolerances_Fail_Value  float
```

### MQA_IsoCheck_WinstonLutz_TestExecutions
```
Id                uniqueidentifier PK (also FK -> TIE)
MaximumDeviation2D float
Deviation3D        float
Tolerance_Warn     float
Tolerance_Fail     float
Tolerance_Dimension, SourceDetectorDistance, SourceAxisDistance, DotsPerInch, Expected
```

### MQA_TestExecutions (selected columns)
```
Id               uniqueidentifier PK
TaskName         nvarchar  -- fully qualified task name
FinishingDate    datetime  -- when test was performed
RadiationDeviceName, RadiationDeviceVendor, RadiationDeviceModel
ClinicName, ProtocolName, ProtocolTag, FinishingUser
Description, State, OriginalState, Name, TestImplementationExecutionType
TaskExecutionId   uniqueidentifier FK -> MQA_TaskExecutions
RadiationDeviceId uniqueidentifier
ReferenceDate     datetime
IsDeleted         bit
```

## Key Findings vs Current Code

1. **`MQA_TestConditions` does NOT exist** — `Name` is directly on `MQA_Numeric_TestConditionExecutions`
2. **`MQA_Numeric_TestConditionExecutions` uses `WarnOn`/`FailOn`** (not `WarningTolerance`/`ErrorTolerance`)
3. **`MQA_PassFail_TestExecutions` has only `Id, AcceptanceCriteria`** — no `PassStatus` column
4. **Profile table is `MQA_Dosimetry_Profile_Results`** (not `MQA_Profiler_TestExecutions`)
5. **Energy table is `MQA_Dosimetry_Energy_TestExecutions`** with `WarningTolerance`/`ErrorTolerance`
6. **Output table is `MQA_Dosimetry_Output_TestExecutions`** with `WarningTolerance`/`ErrorTolerance`
7. **Wedge table is `MQA_Dosimetry_Wedge_TestExecutions`** with `Tolerance_Warn`/`Tolerance_Fail`
8. **MLC: `MQA_MDL_MlcQA_Results`** — `MlcQATestExecutionBase_Id` FK to `MQA_MDL_MlcQA_TestExecutions`
9. **MLC uses denormalized metric columns** (`FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value` etc.)
10. **CBCT/Planar/VMAT: Results.Id = TestExecution.Id** (same UUID, no separate FK)
11. **WinstonLutz: `MaximumDeviation2D` and `Deviation3D`** (direct columns, not nested)
12. **Units table is `UST_Units`** (not `MQA_Units` or `MQA_TestUnits`)
13. **Protocol table is `MQA_ProtocolDefinitions`** (not `MQA_TestProtocols`)

## Additional Findings

### VMAT RoiResults Sub-table
Measured values for RoiMean/RoiStandardDeviation live in a **child table** `MQA_MDL_VmatDmlc_RoiResults`, linked via `VmatDmlcResult_Id`. Columns:
```
Id                             uniqueidentifier PK
VmatDmlcResult_Id              uniqueidentifier FK -> MQA_MDL_VmatDmlc_Results.Id
ROIId                          nvarchar
Name                           nvarchar  -- e.g. "[2.0 cm/s]" or "[111 MU/min]"
Rank                           int
Mean_Value_Value               float  -- actual measured mean
Mean_Value_Dimension           int
Mean_Verdict                   int
StandardDeviation_Value_Value  float  -- actual measured std dev
StandardDeviation_Value_Dimension int
StandardDeviation_Verdict      int
```

### Verdict Encoding
Consistent across all myQA tables:
| Value | Meaning |
|-------|---------|
| `0`   | Unknown / untested |
| `10`  | Queued |
| `30`  | Running |
| `40`  | Pass |
| `50`  | Warning / tolerance exceeded |
| `60`  | Fail |

`TestResult` and individual metric `*_Verdict` columns all follow this pattern.

### Profile QIE Trailing Spaces
Two column names in `MQA_Dosimetry_Profile_QueueItemExecutions` have a literal trailing space (confirmed via hex dump):
- `ReferencePointInnerPercentageOfHalfFieldWidth ` (note space before closing backtick)
- `ReferencePointOuterPercentageOfHalfFieldWidth `

Must be quoted in SQL: `[ReferencePointInnerPercentageOfHalfFieldWidth ]`

### Numeric Daily QA Task Name Pattern
Confirmed from actual data (Step 5.1 query):
- `5.Tmt.Linac.D - myQA Daily Constancy Check` — `.D` suffix
- `5.Tmt.DXR.D - myQA Daily Constancy Check` — `.D` suffix
- `5.Tmt.Linac.D2 - Daily QA (Physics)` — `.D2` suffix (separate task)
- `5.Tmt.Linac.D` matches the proposed spec's `.D%` prefix filter
- `5.Tmt.Linac.D2` would need `.D2%` or would be caught by `.D%` (`.` is wildcard in LIKE)
