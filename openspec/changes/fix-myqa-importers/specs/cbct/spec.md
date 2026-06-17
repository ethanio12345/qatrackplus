# CBCT Import

> Implements Pattern B (denormalized wide-row) per `design.md`. Nine metric
> prefixes with the full 4-tuple column structure, plus non-conforming columns.

## Requirements

### R1: METRICS dict (9 prefixes)

The system SHALL extract each metric via a static `METRICS` dict. Each prefix
has the standard 4-tuple: `{P}_Result_Value_Value`, `{P}_Result_Verdict`,
`{P}_AcceptanceCriterion_Tolerances_Warn_Value`,
`{P}_AcceptanceCriterion_Tolerances_Fail_Value`.

| Prefix | Test slug |
|---|---|
| `ScalingDiscrepancy` | `myqa_cbct_scaling_discrepancy` |
| `GeometricDistortion` | `myqa_cbct_geometric_distortion` |
| `SpatialResolution` | `myqa_cbct_spatial_resolution` |
| `OverallUniformity` | `myqa_cbct_overall_uniformity` |
| `MinimumUniformity` | `myqa_cbct_minimum_uniformity` |
| `Contrast` | `myqa_cbct_contrast` |
| `CNR` | `myqa_cbct_cnr` |
| `MaxHuDeviation` | `myqa_cbct_max_hu_deviation` |
| `MeasuredSliceWidth` | `myqa_cbct_measured_slice_width` |

### R2: Non-conforming columns (per O2)

| Column | Handling |
|---|---|
| `SliceWidthDifference_Value` | value-only → slug `myqa_cbct_slice_width_difference` (no tolerance, no verdict) |
| `SliceWidthDifference_Dimension` | metadata → not emitted |
| `MaxHuDeviationRoi`, `MinUniformityRoi` | metadata (ROI name strings) → not emitted |
| `EnergyType`, `EnergyValue`, `TestResult` | execution metadata → not emitted |

### R3: JOIN path (same-UUID, filter te.TaskExecutionId)

CBCT uses the same-UUID link (`Cbct_Results.Id = Cbct_TestExecutions.Id`):

```sql
SELECT r.<metric cols>, r.SliceWidthDifference_Value, r.TestResult
FROM MQA_MDL_Cbct_Results r
JOIN MQA_MDL_Cbct_TestExecutions cte ON r.Id = cte.Id
JOIN MQA_TestImplementationExecutions tie ON cte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Replaces the existing broken path via `MQA_MDL_Cbct_QueueItemExecutions`
(`myqa_import.py:474-476`), not in the verified schema.

### R4: Setup creates Test + UTI for every emitted slug (per D2)

Setup SHALL create a Test (and UnitTestInfo per unit) for **every slug the
importer emits** — not just the 9 tolerance-bearing prefixes. The engine
silently drops TestInstances for slugs lacking a Test (`myqa_import.py:209-211`).
Specifically setup creates:
- 9 prefix Tests (`myqa_cbct_scaling_discrepancy`, etc.) — each with Tolerance
  where `warn_col`/`fail_col` are present, via `get_or_create_tolerance(warn,
  fail, is_relative=False, limit_tendency=0)`
- `myqa_cbct_slice_width_difference` — type=`numerical`, value-only, no Tolerance

No discovery query (no `Name` column on `MQA_MDL_Cbct_Results`).

## Scenarios

**Scenario: CBCT metric extraction (happy path)**

- GIVEN a CBCT execution with ScalingDiscrepancy_Result_Value_Value=0.02,
  CNR_Result_Value_Value=1.5
- WHEN imported
- THEN `myqa_cbct_scaling_discrepancy` SHALL have value=0.02
- AND `myqa_cbct_cnr` SHALL have value=1.5
- AND pass_fail SHALL be `no_tol` for both (D4 verdict storage deferred)

**Scenario: SliceWidthDifference value-only**

- GIVEN a CBCT execution with SliceWidthDifference_Value=0.3
- WHEN imported
- THEN `myqa_cbct_slice_width_difference` SHALL have value=0.3
- AND no Tolerance SHALL be created for it (value-only entry in METRICS)

**Scenario: NULL metric value**

- GIVEN a CBCT execution where Contrast_Result_Value_Value IS NULL
- WHEN imported
- THEN `myqa_cbct_contrast` SHALL be created with value=None
- AND other metrics SHALL still be created

**Scenario: Missing tolerance column in setup**

- GIVEN setup is processing CBCT and a metric prefix has
  `_AcceptanceCriterion_Tolerances_Warn_Value` IS NULL
- WHEN setup creates the Test
- THEN the Test SHALL be created with no Tolerance

**Scenario: Empty result set**

- GIVEN an execution_id with no row in `MQA_MDL_Cbct_Results`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances
