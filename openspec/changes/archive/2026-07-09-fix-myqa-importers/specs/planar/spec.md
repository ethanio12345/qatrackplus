# Planar Import

> Implements Pattern B (denormalized wide-row) per `design.md`. Seven metric
> prefixes with the full 4-tuple column structure, plus non-conforming columns.

## Requirements

### R1: METRICS dict (7 prefixes)

The system SHALL extract each metric via a static `METRICS` dict. Each prefix
has the standard 4-tuple: `{P}_Result_Value_Value`, `{P}_Result_Verdict`,
`{P}_AcceptanceCriterion_Tolerances_Warn_Value`,
`{P}_AcceptanceCriterion_Tolerances_Fail_Value`.

| Prefix | Test slug |
|---|---|
| `ScalingDiscrepancy` | `myqa_planar_scaling_discrepancy` |
| `SpatialResolution` | `myqa_planar_spatial_resolution` |
| `MinimumUniformity` | `myqa_planar_minimum_uniformity` |
| `Contrast` | `myqa_planar_contrast` |
| `CNR` | `myqa_planar_cnr` |
| `XOffset` | `myqa_planar_x_offset` |
| `YOffset` | `myqa_planar_y_offset` |

### R2: Non-conforming columns (per O2)

| Column | Handling |
|---|---|
| `MinUniformityRoi`, `EnergyType`, `EnergyValue`, `TestResult` | execution metadata → not emitted |

### R3: JOIN path (same-UUID, filter te.TaskExecutionId)

Planar uses the same-UUID link (`Planar_Results.Id = Planar_TestExecutions.Id`):

```sql
SELECT r.<metric cols>, r.TestResult
FROM MQA_MDL_Planar_Results r
JOIN MQA_MDL_Planar_TestExecutions pte ON r.Id = pte.Id
JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Replaces the existing broken path via `MQA_MDL_Planar_QueueItemExecutions`
(`myqa_import.py:499-501`), not in the verified schema.

### R4: Setup iterates METRICS (per D2)

Setup SHALL iterate the same `METRICS` dict (no discovery query). For each
prefix with `warn_col`/`fail_col`, create a Tolerance via
`get_or_create_tolerance(warn, fail, is_relative=False, limit_tendency=0)`.

## Scenarios

**Scenario: Planar metric extraction (happy path)**

- GIVEN a Planar execution with XOffset_Result_Value_Value=0.5,
  YOffset_Result_Value_Value=-0.3, CNR_Result_Value_Value=2.1
- WHEN imported
- THEN `myqa_planar_x_offset` SHALL have value=0.5
- AND `myqa_planar_y_offset` SHALL have value=-0.3
- AND `myqa_planar_cnr` SHALL have value=2.1
- AND pass_fail SHALL be `no_tol` for all (D4 verdict storage deferred)

**Scenario: NULL metric value**

- GIVEN a Planar execution where Contrast_Result_Value_Value IS NULL
- WHEN imported
- THEN `myqa_planar_contrast` SHALL be created with value=None
- AND other metrics SHALL still be created

**Scenario: Negative offset value**

- GIVEN a Planar execution with XOffset_Result_Value_Value=-1.2
- WHEN imported
- THEN `myqa_planar_x_offset` SHALL have value=-1.2
- AND the engine SHALL store the negative float (not abs/clamped)

**Scenario: Missing tolerance column in setup**

- GIVEN setup is processing Planar and a metric prefix has
  `_AcceptanceCriterion_Tolerances_Warn_Value` IS NULL
- WHEN setup creates the Test
- THEN the Test SHALL be created with no Tolerance

**Scenario: Empty result set**

- GIVEN an execution_id with no row in `MQA_MDL_Planar_Results`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances
