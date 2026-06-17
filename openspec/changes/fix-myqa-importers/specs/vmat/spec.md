# VMAT Import

> Implements Pattern C (hybrid: parent wide-row + child-table fan-out) per
> `design.md`. One static parent metric + N dynamic child metrics per ROI.
> The only type with a 1-to-many child relationship.

## Requirements

### R1: Parent metric (static)

The system SHALL extract the `NormalizationValue` metric from the parent table
`MQA_MDL_VmatDmlc_Results`:

| Parent column | Test slug |
|---|---|
| `NormalizationValueResult_Value_Value` | `myqa_vmat_normalization_value` |

Tolerance columns
(`NormalizationValueAcceptanceCriterion_Tolerances_Warn/Fail_Value`) are read
during setup only.

### R2: Child metrics (dynamic, per ROI)

The system SHALL iterate rows in `MQA_MDL_VmatDmlc_RoiResults` linked via
`VmatDmlcResult_Id`. Per child row, emit TWO test instances:

| Child column | Suffix (pre-slugify) | Final slug suffix | Tolerance source (parent) |
|---|---|---|---|
| `Mean_Value_Value` | `{roi} mean` | `{roi}_mean` | `RoiMeanAcceptanceCriterion_Tolerances_Warn/Fail_Value` |
| `StandardDeviation_Value_Value` | `{roi} std dev` | `{roi}_std_dev` | `RoiStandardDeviationAcceptanceCriterion_Tolerances_Warn/Fail_Value` |

All ROI Mean rows share the `RoiMean*` tolerance; all StdDev rows share the
`RoiStd*` tolerance. Tolerances are setup-only.

### R3: ROI slugification (per O3)

The system SHALL derive ROI test slugs by:
1. Stripping leading/trailing brackets `[` `]` from `rr.Name` (e.g. `[2.0 cm/s]` → `2.0 cm/s`)
2. `slugify_name(list_slug, f'{cleaned} mean')` and `slugify_name(list_slug, f'{cleaned} std dev')`

Note: `slugify_name` (`myqa_import.py:40`) **preserves periods** — `2.0` stays
`2.0` in the slug. Implementer MUST confirm period-in-slugs is acceptable to
QATrack+ URL routing, or pre-strip periods in the `clean()` helper.

### R4: JOIN paths (filter te.TaskExecutionId)

Parent:
```sql
SELECT r.NormalizationValueResult_Value_Value
FROM MQA_MDL_VmatDmlc_Results r
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

Child:
```sql
SELECT rr.Name, rr.Mean_Value_Value, rr.StandardDeviation_Value_Value, rr.Rank
FROM MQA_MDL_VmatDmlc_RoiResults rr
JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
ORDER BY rr.Rank
```

### R5: Setup (static parent + child discovery)

Setup SHALL create the static `NormalizationValue` test, then discover ROI
tests via `SELECT DISTINCT rr.Name` from the child table (JOIN through parent
+ te, filter by `te.TaskName LIKE %s`). Each distinct Name → two Tests (Mean +
StdDev) with shared tolerances from the parent.

## Scenarios

**Scenario: VMAT import (happy path)**

- GIVEN a VMAT execution with NormalizationValueResult_Value_Value=100.5,
  and 3 ROI rows: `[2.0 cm/s]` Mean=42.1, `[5.0 cm/s]` Mean=38.2, `[10.0 cm/s]` Mean=35.0
- WHEN imported
- THEN `myqa_vmat_normalization_value` SHALL have value=100.5
- AND `myqa_vmat_2.0_cm_s_mean` SHALL have value=42.1
- AND `myqa_vmat_5.0_cm_s_mean` SHALL have value=38.2
- AND `myqa_vmat_10.0_cm_s_mean` SHALL have value=35.0
- AND pass_fail SHALL be `no_tol` for all (D4 verdict storage deferred)

**Scenario: NULL ROI Mean value**

- GIVEN a VMAT ROI row where Mean_Value_Value IS NULL
- WHEN imported
- THEN `{roi}_mean` SHALL be created with value=None
- AND `{roi}_std_dev` SHALL still be created (independent)

**Scenario: Empty ROI result set**

- GIVEN a VMAT execution with NormalizationValue but no rows in
  `MQA_MDL_VmatDmlc_RoiResults`
- WHEN imported
- THEN only `myqa_vmat_normalization_value` SHALL be emitted
- AND no ROI test instances SHALL be created

**Scenario: NULL parent NormalizationValue**

- GIVEN a VMAT execution where NormalizationValueResult_Value_Value IS NULL
- WHEN imported
- THEN `myqa_vmat_normalization_value` SHALL be created with value=None
- AND ROI child metrics SHALL still be processed independently

**Scenario: Duplicate ROI Name across executions**

- GIVEN two VMAT executions both containing ROI `[2.0 cm/s]`
- WHEN setup discovers ROI tests
- THEN `SELECT DISTINCT rr.Name` SHALL yield one `[2.0 cm/s]` → two Tests
  (`{roi}_mean`, `{roi}_std_dev`) created once
- AND both executions' imports SHALL write to the same Test slugs (no duplication)
