# myQA SQL Reference

Complete documentation of every SQL query used by the QATrack+ myQA import
system to extract data from the myQA SQL Server database.

All queries are in `qatrack/myqa_import.py`. Parameters use pymssql `%s`
placeholders. Connection is via `pymssql.connect()` (read-only access).

---

## Table of Contents

1. [myQA Database Schema](#1-mya-database-schema)
2. [Discovery Queries (TaskName-level)](#2-discovery-queries-taskname-level)
3. [Extraction Queries (Session-level)](#3-extraction-queries-session-level)
4. [Multi-Flag Queries](#4-multi-flag-queries)
5. [Session Querying](#5-session-querying)

---

## 1. myQA Database Schema

The myQA database (SQL Server) stores QA test executions for radiation therapy
equipment. Data is organized as:

```
MQA_TestExecutions (top-level: TaskName, device, dates, state)
  └── MQA_TestImplementationExecutions (polymorphic link to typed execution)
        ├── MQA_Numeric_TestConditionExecutions (row-per-condition numeric tests)
        ├── MQA_PassFail_TestExecutions (pass/fail with acceptance criteria text)
        ├── MQA_Dosimetry_Profile_* (beam profile scans)
        ├── MQA_Dosimetry_Wedge_* (wedge constancy measurements)
        ├── MQA_Dosimetry_Output_* (output constancy per energy)
        ├── MQA_Dosimetry_Energy_* (energy constancy per chamber)
        ├── MQA_MDL_MlcQA_* (MLC QA — denormalized wide rows)
        ├── MQA_MDL_Cbct_* (CBCT image quality)
        ├── MQA_MDL_Planar_* (planar imaging QA)
        ├── MQA_MDL_VmatDmlc_* (VMAT/DMLC QA with ROI results)
        └── MQA_IsoCheck_WinstonLutz_* (Winston-Lutz isocenter accuracy)
```

### Tables (25 total)

| Table | Purpose |
|-------|---------|
| `MQA_TestExecutions` | Top-level execution record. Contains `TaskName`, `TaskExecutionId` (UUID), `RadiationDeviceName`, `ReferenceDate`, `FinishingDate`, `State`, `Name` (test step label), `ProtocolName`, `Description`, `Category`. |
| `MQA_TestImplementationExecutions` | Polymorphic join table linking `MQA_TestExecutions` to typed execution tables (Numeric, PassFail, Profile, etc.). Shares the same `Id` as the typed execution. |
| `MQA_Numeric_TestConditionExecutions` | Row-per-condition numeric measurements. Columns: `Name` (condition name), `Actual` (measured value), `Expected`, `WarnOn`, `FailOn`, `IsRelative`. |
| `MQA_PassFail_TestExecutions` | Pass/fail tests. Columns: `AcceptanceCriteria` (text result). |
| `MQA_Dosimetry_Profile_Results` | Beam profile measurements. Columns: `DisplayName`, `Actual`, `Expected`, `Warn`, `Fail`, `ProfileDirection` (1=crossline, 2=inline). |
| `MQA_Dosimetry_Profile_QueueItemExecutions` | Queue items linking profile results to test executions. |
| `MQA_Dosimetry_Profile_TestExecutions` | Profile test execution records. |
| `MQA_Dosimetry_Wedge_QueueItemExecutions` | Wedge constancy measurements. Columns: `ActualValue`, `ExpectedValue`, `Tolerance_Warn`, `Tolerance_Fail`. |
| `MQA_Dosimetry_Wedge_TestExecutions` | Wedge test execution. Columns: `BeamQuality_EnergyValue` (e.g. 6, 10, 18). |
| `MQA_Dosimetry_Output_QueueItemExecutions` | Output constancy measurements. Columns: `Actual`, `Expected`, `WarningTolerance`, `ErrorTolerance`. |
| `MQA_Dosimetry_Common_QueueItemExecutions` | Shared metadata for dosimetry queue items. Columns: `BeamQuality_EnergyValue`, `BeamQuality_IsFlatteningFilterFree`. |
| `MQA_Dosimetry_Output_TestExecutions` | Output test execution. |
| `MQA_Dosimetry_Energy_ChamberExecutions` | Per-chamber energy measurements. Columns: `Actual`, `Expected`, `WarningTolerance`, `ErrorTolerance`, `ChamberNumber`. |
| `MQA_Dosimetry_Energy_QueueItemExecutions` | Energy queue items. |
| `MQA_Dosimetry_Energy_TestExecutions` | Energy test execution. |
| `MQA_MDL_MlcQA_Results` | MLC QA denormalized wide-row results. Columns: `FailingPeaks_Result_Value_Value`, `MaximumDeviation_Result_Value_Value`, `InterstripRatio_Result_Value_Value`, `StandardDeviation_Result_Value_Value`, `IsocenterToStripDistance_Result_Value_Value`, `TotalPeaks`, `LeavesThatFailed`. |
| `MQA_MDL_MlcQA_TestExecutions` | MLC QA test execution. |
| `MQA_MDL_Cbct_Results` | CBCT image quality results. Columns: `ScalingDiscrepancy_Result_Value_Value`, `GeometricDistortion_Result_Value_Value`, `SpatialResolution_Result_Value_Value`, `OverallUniformity_Result_Value_Value`, `MinimumUniformity_Result_Value_Value`, `Contrast_Result_Value_Value`, `CNR_Result_Value_Value`, `MaxHuDeviation_Result_Value_Value`, `MeasuredSliceWidth_Result_Value_Value`, `SliceWidthDifference_Value`. |
| `MQA_MDL_Cbct_TestExecutions` | CBCT test execution. |
| `MQA_MDL_Planar_Results` | Planar imaging QA results. Columns: `ScalingDiscrepancy_Result_Value_Value`, `SpatialResolution_Result_Value_Value`, `MinimumUniformity_Result_Value_Value`, `Contrast_Result_Value_Value`, `CNR_Result_Value_Value`, `XOffset_Result_Value_Value`, `YOffset_Result_Value_Value`. |
| `MQA_MDL_Planar_TestExecutions` | Planar test execution. |
| `MQA_MDL_VmatDmlc_Results` | VMAT/DMLC results. Columns: `NormalizationValueResult_Value_Value`. |
| `MQA_MDL_VmatDmlc_TestExecutions` | VMAT test execution. |
| `MQA_MDL_VmatDmlc_RoiResults` | Per-ROI VMAT results. Columns: `Name` (ROI name), `Mean_Value_Value`, `StandardDeviation_Value_Value`, `Rank`. |
| `MQA_IsoCheck_WinstonLutz_TestExecutions` | Winston-Lutz results. Columns: `MaximumDeviation2D`, `Deviation3D`, `Expected`, `Tolerance_Warn`, `Tolerance_Fail`. |

### State Values

The `State` column in `MQA_TestExecutions` indicates the execution status:

| State | Meaning | Import Action |
|-------|---------|---------------|
| 10 | Not started | Skip (no TestInstance created) |
| 30 | Incomplete | Import as "unreviewed" |
| 40 | Completed | Import as "approved" |
| 50 | Approved | Import as "approved" |
| 60 | Skipped | Import as "skipped" |

---

## 2. Discovery Queries (TaskName-level)

Discovery queries run during `setup_myqa_tests` to determine what TestLists,
Tests, UTCs, and UTIs to create. They query by `TaskName` (not session ID) to
find all possible conditions across all sessions for that task.

### discover_tasknames

Returns all distinct TaskNames in the database.

```sql
SELECT DISTINCT TaskName
FROM MQA_TestExecutions
WHERE TaskName IS NOT NULL
ORDER BY TaskName
```

**Parameters:** none.
**Returns:** list of TaskName strings (e.g. `"5.Tmt.Linac.M.Dosimetry - Monthly QA"`).

---

### discover_task_protocol

Returns the protocol name for a TaskName (e.g. `"TG-142 + PlugIn (template ver. 2020-002)"`).

```sql
SELECT TOP 1 te.ProtocolName
FROM MQA_TestExecutions te
WHERE te.TaskName = %s AND te.ProtocolName IS NOT NULL
```

**Parameters:** `(taskname,)`.
**Returns:** protocol name string or empty string.

---

### discover_units_for_taskname

Returns all distinct device names for a TaskName, mapped to QATrack+ unit
numbers via `LINAC_MAP` / `myqa_device_map.yaml`.

```sql
SELECT DISTINCT te.RadiationDeviceName
FROM MQA_TestExecutions te
WHERE te.TaskName = %s
  AND te.RadiationDeviceName IS NOT NULL
```

**Parameters:** `(taskname,)`.
**Returns:** list of QATrack+ unit numbers (int).

---

### discover_condition_metadata

Returns tolerance and description metadata for numeric conditions. Used during
setup to populate `Test.description` with provenance info.

```sql
SELECT tcne.Name AS condition_name,
       te.Name AS test_step,
       te.Description AS description,
       te.Category AS category,
       tcne.Expected AS expected,
       tcne.WarnOn AS warn_on,
       tcne.FailOn AS fail_on
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie
    ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND tcne.Name IS NOT NULL
```

**Parameters:** `(taskname,)`.
**Returns:** dict keyed by condition name with metadata.

---

### discover_numeric_conditions

Returns all numeric condition names for a TaskName. Condition names are
prefixed with the energy/test-step code when multiple test steps exist
(`multi=True`).

```sql
SELECT DISTINCT tcne.Name, te.Name AS test_step
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie
    ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND tcne.Name IS NOT NULL AND te.State != 10
ORDER BY tcne.Name
```

**Parameters:** `(taskname,)`.
**Returns:** list of condition name strings.
**Post-processing:** `_energy_prefixed()` adds energy prefix (e.g. `"6MV Flatness"`)
when `multi=True`. Energy is extracted from the first `_`-delimited token of
`test_step`, or from `_test_step_prefix()` for descriptive test step names.

---

### discover_passfail_conditions

Returns PassFail test names for a TaskName. Each PassFail execution becomes a
separate condition.

```sql
SELECT DISTINCT te.Name
FROM MQA_PassFail_TestExecutions pfte
JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND te.Name IS NOT NULL AND te.State != 10
ORDER BY te.Name
```

**Parameters:** `(taskname,)`.
**Returns:** list of test name strings.

---

### discover_profile_conditions

Returns profile display names with direction suffix. Direction is appended
when not already in the name.

```sql
SELECT DISTINCT dpr.DisplayName, dpr.ProfileDirection, te.Name AS test_step
FROM MQA_Dosimetry_Profile_Results dpr
JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
    ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
JOIN MQA_Dosimetry_Profile_TestExecutions dpte
    ON dpqie.Id = dpte.ProfileQueueItem_Id
JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND dpr.DisplayName IS NOT NULL
```

**Parameters:** `(taskname,)`.
**Returns:** list of condition name strings.
**Post-processing:** `_profile_condition_name()` appends `(crossline)` or
`(inline)` based on `ProfileDirection` (1=crossline, 2=inline), and prefixes
with test step descriptor when `multi=True`.

---

### discover_wedge_conditions

Returns one condition per distinct energy value. Names are derived as
`"Wedge Constancy {energy}x"`.

```sql
SELECT DISTINCT wte.BeamQuality_EnergyValue
FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
JOIN MQA_Dosimetry_Wedge_TestExecutions wte
    ON wqie.WedgeConstancyExecution_Id = wte.Id
JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND wte.BeamQuality_EnergyValue IS NOT NULL
ORDER BY wte.BeamQuality_EnergyValue
```

**Parameters:** `(taskname,)`.
**Returns:** list of `"Wedge Constancy {N}x"` strings.

---

### discover_output_conditions

Returns one condition per distinct energy value. Names are derived as
`"Output {energy}x"`.

```sql
SELECT DISTINCT cqie.BeamQuality_EnergyValue
FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON oqie.Id = cqie.Id
JOIN MQA_Dosimetry_Output_TestExecutions ote
    ON oqie.OutputConstancyExecution_Id = ote.Id
JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
ORDER BY cqie.BeamQuality_EnergyValue
```

**Parameters:** `(taskname,)`.
**Returns:** list of `"Output {N}x"` strings.

---

### discover_energy_conditions

Returns one condition per distinct (energy, FFF flag, chamber number) combo.
Names are derived as `"Energy {energy}{fff?} ch{chamber}"`.

```sql
SELECT DISTINCT cqie.BeamQuality_EnergyValue,
                cqie.BeamQuality_IsFlatteningFilterFree,
                ece.ChamberNumber
FROM MQA_Dosimetry_Energy_ChamberExecutions ece
JOIN MQA_Dosimetry_Energy_QueueItemExecutions eqie
    ON ece.EnergyConstancyQueueItemExecution_Id = eqie.Id
JOIN MQA_Dosimetry_Energy_TestExecutions ete ON eqie.EnergyConstancyExecution_Id = ete.Id
JOIN MQA_TestImplementationExecutions tie ON ete.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON eqie.Id = cqie.Id
WHERE te.TaskName = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
ORDER BY cqie.BeamQuality_EnergyValue, ece.ChamberNumber
```

**Parameters:** `(taskname,)`.
**Returns:** list of `"Energy {N}{fff?} ch{N}"` strings.

---

### discover_mlc_conditions / discover_cbct_conditions / discover_planar_conditions

These all use the generic `_discover_pattern_b_conditions` function with
different table parameters. Returns metric names prefixed with test step
when `multi=True`.

**Template SQL:**
```sql
SELECT DISTINCT te.Name AS test_step
FROM {results_table} r
JOIN {exec_table} {exec_alias} ON r.{join_col} = {exec_alias}.Id
JOIN MQA_TestImplementationExecutions tie ON {exec_alias}.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

**Parameters:** `(taskname,)`.

**Returns:** `[]` when no data exists for this TaskName/type. Otherwise returns
metric names (e.g. `"Failing Peaks"`, `"CNR"`) prefixed with test step name
when `multi=True`.

#### MLC parameters:
- Table: `MQA_MDL_MlcQA_Results` / `MQA_MDL_MlcQA_TestExecutions`
- Join column: `MlcQATestExecutionBase_Id`
- Metrics (7): Failing Peaks, Maximum Deviation, Interstrip Ratio, Standard
  Deviation, Isocenter To Strip Distance, Total Peaks, Leaves That Failed

#### CBCT parameters:
- Table: `MQA_MDL_Cbct_Results` / `MQA_MDL_Cbct_TestExecutions`
- Join column: `Id` (shared UUID)
- Metrics (10): Scaling Discrepancy, Geometric Distortion, Spatial Resolution,
  Overall Uniformity, Minimum Uniformity, Contrast, CNR, Max Hu Deviation,
  Measured Slice Width, Slice Width Difference

#### Planar parameters:
- Table: `MQA_MDL_Planar_Results` / `MQA_MDL_Planar_TestExecutions`
- Join column: `Id` (shared UUID)
- Metrics (7): Scaling Discrepancy, Spatial Resolution, Minimum Uniformity,
  Contrast, CNR, X Offset, Y Offset

---

### discover_vmat_conditions

Returns the parent normalization name plus per-ROI mean/std dev names.

**Query 1** — check if data exists + get test steps:
```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_MDL_VmatDmlc_Results r
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

**Query 2** — get distinct ROI names:
```sql
SELECT DISTINCT rr.Name, te.Name AS test_step
FROM MQA_MDL_VmatDmlc_RoiResults rr
JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND rr.Name IS NOT NULL
```

**Parameters:** `(taskname,)`.
**Returns:** list of condition names: `"Normalization Value"` (unprefixed) +
`"{prefix} {roi_name} mean"` and `"{prefix} {roi_name} std dev"` per ROI.

---

### discover_winston_lutz_conditions

Returns two base metrics, prefixed with test step when `multi=True`.

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

**Parameters:** `(taskname,)`.
**Returns:** `[]` when no data. Otherwise: `"Maximum Deviation 2D"` and
`"Deviation 3D"`, prefixed with test step when `multi=True`.

---

## 3. Extraction Queries (Session-level)

Extraction queries run during `import_myqa` to pull actual measurement values
for a specific session. They query by `TaskExecutionId` (UUID).

### extract_numeric

Returns measured values, tolerances, and state for each numeric condition in
the session.

```sql
SELECT tcne.Name, tcne.Actual, te.State, te.Name AS test_step,
       tcne.Expected, tcne.WarnOn, tcne.FailOn, tcne.IsRelative
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie
    ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s AND te.State != 10
```

**Parameters:** `(execution_id,)`.
**Returns:** `{condition_name: {value, state, expected, warn, fail, relative}}`.
**Post-processing:** `_energy_prefixed()` applied when `multi_override=True`.

---

### extract_passfail

Returns acceptance criteria text and state for each PassFail test.

```sql
SELECT te.Name, pfte.AcceptanceCriteria, te.State
FROM MQA_PassFail_TestExecutions pfte
JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s AND te.State != 10
ORDER BY te.Name
```

**Parameters:** `(execution_id,)`.
**Returns:** `{test_name: {value: acceptance_criteria_text, state}}`.

---

### extract_profile

Returns beam profile measurements (flatness, symmetry, penumbra, etc.) with
tolerances.

```sql
SELECT dpr.Actual, dpr.DisplayName, dpr.Expected, dpr.Warn, dpr.Fail,
       dpr.ProfileDirection, te.Name AS test_step
FROM MQA_Dosimetry_Profile_Results dpr
JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
    ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
JOIN MQA_Dosimetry_Profile_TestExecutions dpte
    ON dpqie.Id = dpte.ProfileQueueItem_Id
JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s AND dpr.DisplayName IS NOT NULL
```

**Parameters:** `(execution_id,)`.
**Returns:** `{condition_name: {value, expected, warn, fail, relative}}`.
Values rounded to 4 decimal places.

---

### extract_wedge

Returns wedge constancy measurements per energy.

```sql
SELECT wqie.ActualValue, wqie.ExpectedValue,
       wqie.Tolerance_Warn, wqie.Tolerance_Fail,
       wte.BeamQuality_EnergyValue
FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
JOIN MQA_Dosimetry_Wedge_TestExecutions wte
    ON wqie.WedgeConstancyExecution_Id = wte.Id
JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s AND wte.BeamQuality_EnergyValue IS NOT NULL
```

**Parameters:** `(execution_id,)`.
**Returns:** `{"Wedge Constancy {N}x": {value, expected, warn, fail, relative=True}}`.

---

### extract_output

Returns output constancy measurements per energy.

```sql
SELECT oqie.Actual, oqie.Expected, oqie.WarningTolerance, oqie.ErrorTolerance,
       cqie.BeamQuality_EnergyValue
FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON oqie.Id = cqie.Id
JOIN MQA_Dosimetry_Output_TestExecutions ote
    ON oqie.OutputConstancyExecution_Id = ote.Id
JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
```

**Parameters:** `(execution_id,)`.
**Returns:** `{"Output {N}x": {value, expected, warn, fail, relative=True}}`.

---

### extract_energy

Returns energy constancy measurements per chamber.

```sql
SELECT ece.Actual, ece.Expected, ece.WarningTolerance, ece.ErrorTolerance,
       cqie.BeamQuality_EnergyValue,
       cqie.BeamQuality_IsFlatteningFilterFree,
       ece.ChamberNumber
FROM MQA_Dosimetry_Energy_ChamberExecutions ece
JOIN MQA_Dosimetry_Energy_QueueItemExecutions eqie
    ON ece.EnergyConstancyQueueItemExecution_Id = eqie.Id
JOIN MQA_Dosimetry_Energy_TestExecutions ete ON eqie.EnergyConstancyExecution_Id = ete.Id
JOIN MQA_TestImplementationExecutions tie ON ete.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON eqie.Id = cqie.Id
WHERE te.TaskExecutionId = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
```

**Parameters:** `(execution_id,)`.
**Returns:** `{"Energy {N}{fff?} ch{N}": {value, expected, warn, fail, relative=True}}`.

---

### extract_mlc / extract_cbct / extract_planar

These all use the generic `_extract_pattern_b` function. The SELECT clause is
dynamically built from the metric column maps. For each metric column ending
in `_Result_Value_Value` or `_Value`, three tolerance columns are also selected:
`{prefix}_AcceptanceCriterion_ExpectedValue_Value`,
`{prefix}_AcceptanceCriterion_Tolerances_Warn_Value`,
`{prefix}_AcceptanceCriterion_Tolerances_Fail_Value`.

**Template SQL:**
```sql
SELECT te.Name AS test_step,
       r.{metric_col_1}, r.{tol_1_expected}, r.{tol_1_warn}, r.{tol_1_fail},
       r.{metric_col_2}, ...
FROM {results_table} r
JOIN {exec_table} {exec_alias} ON r.{join_col} = {exec_alias}.Id
JOIN MQA_TestImplementationExecutions tie ON {exec_alias}.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

**Parameters:** `(execution_id,)`.
**Returns:** `{condition_name: {value, expected, warn, fail, relative=False}}`.
Condition names prefixed with test step when `multi_override=True`.

---

### extract_vmat

Returns parent normalization value + per-ROI mean and std dev.

```sql
SELECT te.Name AS test_step,
       r.NormalizationValueResult_Value_Value,
       rr.Name AS roi_name, rr.Mean_Value_Value,
       rr.StandardDeviation_Value_Value, rr.Rank
FROM MQA_MDL_VmatDmlc_Results r
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
LEFT JOIN MQA_MDL_VmatDmlc_RoiResults rr ON rr.VmatDmlcResult_Id = r.Id
WHERE te.TaskExecutionId = %s
ORDER BY te.Name, rr.Rank
```

**Parameters:** `(execution_id,)`.
**Returns:** `"Normalization Value"` (unprefixed) + per-ROI
`"{prefix} {cleaned_roi_name} mean"` and `"{prefix} {cleaned_roi_name} std dev"`.
ROI names are stripped of brackets via `clean_roi_name()`.

---

### extract_winston_lutz

Returns 2D and 3D deviation values with tolerances.

```sql
SELECT te.Name AS test_step,
       wl.MaximumDeviation2D, wl.Deviation3D,
       wl.Expected, wl.Tolerance_Warn, wl.Tolerance_Fail
FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

**Parameters:** `(execution_id,)`.
**Returns:** `"Maximum Deviation 2D"` and `"Deviation 3D"` with values and
tolerances. Prefixed with test step when `multi_override=True`.

---

## 4. Multi-Flag Queries

The `compute_multi_flags` function runs 7 queries to determine whether each
execution type has multiple test steps for a TaskName. When `multi=True`,
condition names are prefixed with the test step descriptor to disambiguate.

Each query returns `DISTINCT te.Name AS test_step` and the result is
`len(distinct_steps) > 1`.

### Numeric

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_Numeric_TestConditionExecutions tcne
JOIN MQA_TestImplementationExecutions tie
    ON tcne.NumericTestExecution_Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s AND te.State != 10
```

### Profile

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_Dosimetry_Profile_Results dpr
JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
    ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
JOIN MQA_Dosimetry_Profile_TestExecutions dpte
    ON dpqie.Id = dpte.ProfileQueueItem_Id
JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

### VMAT

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_MDL_VmatDmlc_Results r
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

### WinstonLutz

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

### MLC

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_MDL_MlcQA_Results r
JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

### CBCT

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_MDL_Cbct_Results r
JOIN MQA_MDL_Cbct_TestExecutions cte ON r.Id = cte.Id
JOIN MQA_TestImplementationExecutions tie ON cte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

### Planar

```sql
SELECT DISTINCT te.Name AS test_step
FROM MQA_MDL_Planar_Results r
JOIN MQA_MDL_Planar_TestExecutions pte ON r.Id = pte.Id
JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskName = %s
```

---

## 5. Session Querying

### query_sessions

Returns all sessions for a TaskName within a date range. Each session becomes
one TestListInstance in QATrack+.

```sql
SELECT DISTINCT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate,
       te.TaskName, te.RadiationDeviceName
FROM MQA_TestExecutions te
WHERE te.TaskName = %s
  AND te.ReferenceDate IS NOT NULL
  AND te.ReferenceDate >= %s
  AND te.ReferenceDate <= %s
ORDER BY te.ReferenceDate, te.FinishingDate
```

**Parameters:** `(taskname, cutoff_naive, now_naive)` where cutoff and now are
Python naive datetimes.

**Returns:** list of session dicts:
```python
{
    "task_execution_id": "UUID string",
    "reference_date": datetime,
    "finishing_date": datetime,
    "task_name": str,
    "unit_number": int,  # mapped from RadiationDeviceName via LINAC_MAP
}
```

### duplicate_check

Uses Django ORM (not raw SQL) to check if a session has already been imported:

```python
TestInstance.objects.filter(
    unit_test_info__test__slug=f"{slugify_name(taskname)}_taskid",
    unit_test_info__unit__number=unit_number,
    string_value=execution_id,
).exists()
```

Queries the QATrack+ PostgreSQL `qa_testinstance` table for a TestInstance
storing the myQA `TaskExecutionId` as `string_value`.
