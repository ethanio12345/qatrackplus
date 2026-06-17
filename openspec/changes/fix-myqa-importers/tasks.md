# Tasks: Fix myQA Importers

## Phase 1: Numeric (Daily QA) — 3,670 sessions

- [ ] **Task 1.1: Fix MyqaNumericImport query**
  Remove JOIN to non-existent `MQA_TestConditions`. Read `Name`, `Actual`,
  `WarnOn`, `FailOn`, `LimitTendency`, `IsRelative` directly from
  `MQA_Numeric_TestConditionExecutions`. JOIN via `NumericTestExecution_Id`.
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run python manage.py import_myqa --task myqa_numeric --dry-run`

- [ ] **Task 1.2: Extend setup_myqa_tests for Numeric**
  Query DISTINCT Name + WarnOn/FailOn from Numeric table. Create
  TestList `myqa_numeric`, Test objects with `myqa_numeric_` slugs,
  Tolerance objects, UTCs per unit with daily frequency.
  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`

- [ ] **Task 1.3: Backfill numeric data**
  `uv run python manage.py setup_myqa_tests --force`
  `uv run python manage.py import_myqa --task myqa_numeric --days 365`
  **Verify:** Check admin for imported TLIs, run again to confirm 0 new

## Phase 2: Winston Lutz — 400 sessions

- [ ] **Task 2.1: Fix MyqaWinstonLutzImport**
  Map `MaximumDeviation2D` → `myqa_winston_lutz_max_deviation_2d`
  Map `Deviation3D` → `myqa_winston_lutz_deviation_3d`
  Use `Tolerance_Warn`/`Tolerance_Fail` directly.
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run python manage.py import_myqa --task myqa_winston_lutz --dry-run`

- [ ] **Task 2.2: Backfill Winston Lutz data**
  Create test list and UTCs, then `import_myqa --task myqa_winston_lutz --days 365`

## Phase 3: MLC + VMAT — ~500 sessions

- [ ] **Task 3.1: Fix MyqaMlcImport**
  Rewrite to extract:
  - `TestResult`, `TotalPeaks`, `LeavesThatFailed` (simple)
  - `FailingPeaks_Result_Value_Value` + Warn/Fail
  - `MaximumDeviation_Result_Value_Value` + Warn/Fail
  - `InterstripRatio_Result_Value_Value` + Warn/Fail
  - `StandardDeviation_Result_Value_Value` + Warn/Fail
  - `IsocenterToStripDistance_Result_Value_Value` + Warn/Fail
  Use `MlcQATestExecutionBase_Id` for JOIN.
  **Files:** `qatrack/myqa_import.py`

- [ ] **Task 3.2: Fix MyqaVmatImport**
  Map `NormalizationValueResult_Value_Value`, `RoiMean..._ExpectedValue_Value`,
  `RoiStandardDeviation..._ExpectedValue_Value` with Warn/Fail.
  **Files:** `qatrack/myqa_import.py`

- [ ] **Task 3.3: Backfill MLC + VMAT**
  Create test lists + UTCs, then import for each type.

## Phase 4: CBCT + Planar + PassFail — ~50 sessions

- [ ] **Task 4.1: Fix MyqaCbctImport**
  Map all 10+ metric columns to individual tests.
  Metrics: ScalingDiscrepancy, GeometricDistortion, SpatialResolution,
  OverallUniformity, MinimumUniformity, Contrast, CNR, MaxHuDeviation,
  MeasuredSliceWidth, SliceWidthDifference.
  **Files:** `qatrack/myqa_import.py`

- [ ] **Task 4.2: Fix MyqaPlanarImport**
  Map 7 metrics: ScalingDiscrepancy, SpatialResolution, MinimumUniformity,
  Contrast, CNR, XOffset, YOffset.
  **Files:** `qatrack/myqa_import.py`

- [ ] **Task 4.3: Fix MyqaPassFailImport**
  Store `AcceptanceCriteria` text as string_value. Simple.
  **Files:** `qatrack/myqa_import.py`

- [ ] **Task 4.4: Backfill CBCT + Planar + PassFail**

## Phase 5: Consolidate setup command

- [ ] **Task 5.1: Extend setup_myqa_tests for all types**
  Add setup logic for WinstonLutz, MLC, VMAT, CBCT, Planar.
  Each type needs its own test name discovery query.
  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`
