# Fix myQA Importers — Change Plan

**Change name:** `fix-myqa-importers`
**Schema:** spec-driven

---

## Proposal

Correct SQL queries and column mappings in `myqa_import.py` based on the actual myQA database schema, then extend `setup_myqa_tests.py` and backfill all available data for 1 year.

## Data Volumes

| Type | Sessions | Priority |
|---|---|---|
| Numeric (daily QA) | 3,670 | High |
| Profile (matrix) | 534 | Already working |
| Winston Lutz | 400 | Medium |
| MLC | 252 | Medium |
| VMAT | 247 | Medium |
| CBCT | 46 | Low |
| Planar | 4 | Low |

## Schema Discrepancies

### Numeric (Phase 1)
| Assumed | Actual |
|---|---|
| `MQA_TestConditions` table exists | Table does not exist |
| JOIN via `TestCondition_Id` | `Name` is directly on `MQA_Numeric_TestConditionExecutions` |
| `WarnOn`/`FailOn` via separate table | Same table, direct columns |

**Columns on `MQA_Numeric_TestConditionExecutions`:**
`Id, LimitTendency, Name, BoundingType, IsRelative, Dimension, State, Actual, Expected, WarnOn, FailOn, RowVersion, NumericTestExecution_Id, TestConditionTemplateId`

**JOIN path:** `NumericTestExecution_Id` → `MQA_TestImplementationExecutions.Id` → `MQA_TestExecutions.Id`

### WinstonLutz (Phase 2)
| Assumed | Actual |
|---|---|
| `DisplayName` column | `MaximumDeviation2D`, `Deviation3D` directly |

**Columns on `MQA_IsoCheck_WinstonLutz_TestExecutions`:**
`Id, MaximumDeviation2D, Deviation3D, Tolerance_Warn, Tolerance_Dimension, Tolerance_Fail, SourceDetectorDistance, SourceAxisDistance, DotsPerInch, Expected`

### MLC (Phase 3)
| Assumed | Actual |
|---|---|
| `DisplayName` + simple value | 6 denormalized metric columns |
| `MQA_MDL_MlcQA_QueueItemExecutions` table | Table does not exist |

**Metrics on `MQA_MDL_MlcQA_Results`:**
- `TestResult` (overall score)
- `TotalPeaks` / `LeavesThatFailed`
- `FailingPeaks_Result_Value_Value` (with Warn/Fail)
- `MaximumDeviation_Result_Value_Value` (with Warn/Fail)
- `InterstripRatio_Result_Value_Value` (with Warn/Fail)
- `StandardDeviation_Result_Value_Value` (with Warn/Fail)
- `IsocenterToStripDistance_Result_Value_Value` (with Warn/Fail)
- `LineDistanceAcceptanceCriterion_...` + `LineSlopeAcceptanceCriterion_...`

**JOIN path:** `MlcQATestExecutionBase_Id` → `MQA_TestImplementationExecutions.Id` → `MQA_TestExecutions.Id`

### VMAT (Phase 3)
| Assumed | Actual |
|---|---|
| `DisplayName` + simple value | 3 metric groups |

**Metrics on `MQA_MDL_VmatDmlc_Results`:**
- `TestResult`
- `NormalizationValueResult_Value_Value` (with Warn/Fail, Verdict)
- `RoiMeanAcceptanceCriterion_ExpectedValue_Value` (with Warn/Fail)
- `RoiStandardDeviationAcceptanceCriterion_ExpectedValue_Value` (with Warn/Fail)

### CBCT (Phase 4)
| Assumed | Actual |
|---|---|
| `DisplayName` + simple value | 10+ metric columns |

**Metrics on `MQA_MDL_Cbct_Results`:**
`ScalingDiscrepancy`, `GeometricDistortion`, `SpatialResolution`, `OverallUniformity`, `MinimumUniformity`, `Contrast`, `CNR`, `MaxHuDeviation`, `MeasuredSliceWidth`, `SliceWidthDifference`
+ `EnergyType`, `EnergyValue`

Each metric has `_Result_Value_Value` + `_Result_Verdict` + `_AcceptanceCriterion_Tolerances_Warn/Fail_Value` columns.

### Planar (Phase 4)
Same pattern as CBCT, with: `ScalingDiscrepancy`, `SpatialResolution`, `MinimumUniformity`, `Contrast`, `CNR`, `XOffset`, `YOffset`

### PassFail (Phase 4)
Just `Id` + `AcceptanceCriteria` (text). Store criteria text as string value.

## Tasks

### Phase 1: Fix Numeric + backfill
- [ ] **Task 1.1: Fix MyqaNumericImport query**
  *Remove MQA_TestConditions JOIN, read Name/Actual/WarnOn/FailOn directly*
  **File:** `qatrack/myqa_import.py`
  **Verify:** `uv run python manage.py import_myqa --task myqa_numeric --dry-run`

- [ ] **Task 1.2: Extend setup_myqa_tests for Numeric type**
  *Query distinct test names from MQA_Numeric_TestConditionExecutions, create Test/TestList/UTC*
  **File:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`

- [ ] **Task 1.3: Create test infrastructure + backfill numeric data**
  `uv run python manage.py setup_myqa_tests --force`
  `uv run python manage.py import_myqa --task myqa_numeric --days 365`

### Phase 2: Fix WinstonLutz + backfill
- [ ] **Task 2.1: Fix MyqaWinstonLutzImport query**
  *Map MaximumDeviation2D, Deviation3D as named tests*
  **File:** `qatrack/myqa_import.py`
  **Verify:** `uv run python manage.py import_myqa --task myqa_winston_lutz --dry-run`

- [ ] **Task 2.2: Create test infra + backfill winston lutz data**
  `uv run python manage.py setup_myqa_tests --force`
  `uv run python manage.py import_myqa --task myqa_winston_lutz --days 365`

### Phase 3: Fix MLC + VMAT + backfill
- [ ] **Task 3.1: Fix MyqaMlcImport query**
  *Extract each metric (FailingPeaks, MaxDeviation, etc.) as individual test*
  **File:** `qatrack/myqa_import.py`

- [ ] **Task 3.2: Fix MyqaVmatImport query**
  *Map NormalizationValue, RoiMean, RoiStdDev as named tests*
  **File:** `qatrack/myqa_import.py`

- [ ] **Task 3.3: Create infra + backfill MLC + VMAT**
  `setup_myqa_tests --force && import_myqa --task myqa_mlc --days 365`
  `import_myqa --task myqa_vmat --days 365`

### Phase 4: Fix CBCT + Planar + PassFail + backfill
- [ ] **Task 4.1: Fix MyqaCbctImport query**
  *Map all 10+ metric columns to individual tests*
  **File:** `qatrack/myqa_import.py`

- [ ] **Task 4.2: Fix MyqaPlanarImport query**
  *Map 7 metric columns to individual tests*
  **File:** `qatrack/myqa_import.py`

- [ ] **Task 4.3: Fix MyqaPassFailImport query**
  *Store AcceptanceCriteria as string value*
  **File:** `qatrack/myqa_import.py`

- [ ] **Task 4.4: Create infra + backfill**
  `setup_myqa_tests --force && import_myqa --days 365`

### Phase 5: Consolidate setup command
- [ ] **Task 5.1: Extend setup_myqa_tests for all execution types**
  *Add query+create logic for each non-Numeric type (WinstonLutz, MLC, VMAT, CBCT, Planar)*
  **File:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`

## Key Design Decisions

1. **MLC/CBCT/Planar/VMAT**: Each metric column becomes a separate Test with a descriptive slug like `myqa_mlc_failing_peaks`, `myqa_cbct_scaling_discrepancy`, etc. Use the `_AcceptanceCriterion_Tolerances_Warn/Fail_Value` columns to set up Tolerance objects.

2. **Numeric**: Use the same `slugify_name` helper. Slug example: `myqa_daily_physics_1_05_18mv_output` from Name `1.05 18MV Output`.

3. **Duplication**: Each importer uses `{list_slug}_taskid` for de-dup, stored as string_value.

4. **Tolerance mapping**: `WarnOn` → `tol_low`/`tol_high`, `FailOn` → `act_low`/`act_high`. Use `LimitTendency` (0=two-sided, 1=lower, 2=upper) and `IsRelative` (percent vs absolute).
