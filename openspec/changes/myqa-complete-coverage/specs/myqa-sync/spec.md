## MODIFIED Requirements

### Requirement: PassFail task name patterns

The `MyqaPassFailImport.task_name_patterns` SHALL use broad patterns covering
all device categories, replacing the current `["5.Tmt.Linac.P%", "5.Tmt.DXR.P%"]`
which matches zero sessions in production.

**New patterns**: `["5.Tmt.%", "3.Sim.%", "2.Phys.%", "1.FM.%"]`

The skip-empty guard (`myqa_import.py:249-251`) SHALL prevent creating empty
TestListInstances for sessions that have no PassFail test data.

#### Scenario: HDR pretreatment QA import

- GIVEN myQA has 9,268 PassFail test executions under
  `5.Tmt.HDR.D - Pretreatment QA` for device `Flexitron19`
- WHEN the PassFail importer runs with corrected patterns
- THEN sessions SHALL be found for Flexitron19 (unit 200)
- AND the AcceptanceCriteria text SHALL be stored as string_value

#### Scenario: CT daily PassFail import

- GIVEN myQA has 3,048 PassFail test executions under
  `3.Sim.CT.D - Daily QA (RTs)` for device `CPMCC CT22`
- WHEN the PassFail importer runs with corrected patterns
- THEN sessions SHALL be found for CPMCC CT22 (unit 100)

#### Scenario: LINAC down day PassFail

- GIVEN myQA has PassFail test executions under `5.Tmt.Linac.F - Down Day`
- WHEN the PassFail importer runs
- THEN sessions SHALL be found for all LINAC units
- AND the AcceptanceCriteria text SHALL capture the down-day checklist results

#### Scenario: Skip sessions without PassFail data

- GIVEN a session `5.Tmt.Linac.M.Beam/Collimation - Monthly QA` has only
  MLC and Numeric tests (no PassFail rows in `MQA_PassFail_TestExecutions`)
- WHEN the PassFail importer processes this session
- THEN `extract_results` SHALL return only the taskid key
- AND the skip-empty guard SHALL return `skipped_empty` status
- AND no empty TestListInstance SHALL be created

### Requirement: Wedge task name patterns

The `MyqaWedgeImport.task_name_patterns` SHALL use monthly dosimetry patterns
matching the Output and Profile importers, replacing the current
`["5.Tmt.Linac.M%Wedge%", "5.Tmt.DXR.M%Wedge%"]` which matches zero sessions.

**New patterns**: `["5.Tmt.Linac.M.Dosimetry%", "5.Tmt.Linac.Monthly - Dosimetry",
"5.Tmt.Linac.Y.Dosimetry%", "5.Tmt.Linac.Yearly - Relative%",
"Commissioning.Dos%"]`

#### Scenario: Wedge data found in monthly dosimetry

- GIVEN myQA has 327 wedge test executions for LA414 under
  `5.Tmt.Linac.M.Dosimetry - Monthly QA`
- WHEN the Wedge importer runs with corrected patterns
- THEN sessions SHALL be found for LA414 (unit 4)
- AND wedge ActualValue/ExpectedValue SHALL be extracted from
  `MQA_Dosimetry_Wedge_QueueItemExecutions`

### Requirement: Energy task name patterns

The `MyqaEnergyImport.task_name_patterns` SHALL use the same monthly dosimetry
patterns as Output/Profile/Wedge, replacing the current
`["5.Tmt.Linac.M%Energy%", "5.Tmt.DXR.M%Energy%"]`.

**New patterns**: same as Wedge patterns above.

#### Scenario: Energy data found in monthly dosimetry

- GIVEN myQA has 16 energy test executions
- WHEN the Energy importer runs with corrected patterns
- THEN sessions SHALL be found (primarily on DUMMY LINAC)
- AND the skip-empty guard SHALL filter sessions without energy chamber data

### Requirement: Wedge extract_results column mapping

The `MyqaWedgeImport.extract_results` method SHALL correctly reference the
verified column names in `MQA_Dosimetry_Wedge_QueueItemExecutions`.

**Verified columns**: `ActualValue`, `ExpectedValue`, `Tolerance_Warn`,
`Tolerance_Fail`, `WedgeAngle`, `WedgeDirection`, `WedgeType`.

The `BeamQuality_EnergyValue` column lives on the parent
`MQA_Dosimetry_Wedge_TestExecutions` table, not on the QueueItemExecutions
table.

#### Scenario: Wedge value extraction

- GIVEN a wedge QueueItemExecution with ActualValue=0.6506,
  ExpectedValue=0.649, parent TestExecution BeamQuality_EnergyValue=6
- WHEN `extract_results` processes this row
- THEN slug SHALL be `mtx_wedge_cont_6x`
- AND value SHALL be 0.6506

### Requirement: PassFail scope expansion

The PassFail importer SHALL capture PassFail test data across ALL device
categories, not just LINACs. This includes treatment machines, imaging
equipment, HDR brachytherapy, physics equipment, and facility management.

**Applicable units for `myqa_passfail`**: all units in LINAC_MAP (1–9, 50,
100–101, 200, 300–499).

#### Scenario: MRI daily PassFail import

- GIVEN myQA has 3,264 PassFail test executions under
  `3.Sim.MRI.D - Daily QA` for MRI device
- WHEN the PassFail importer runs
- THEN sessions SHALL be found for unit 101
- AND TestInstances SHALL be created under `myqa_passfail`

#### Scenario: Source security PassFail import

- GIVEN myQA has PassFail test executions under `1.FM.%` task names
  for `Source Security` device
- WHEN the PassFail importer runs
- THEN sessions SHALL be found for the security unit (482)
- AND TestInstances SHALL be created under `myqa_passfail`

### Requirement: import_myqa_all tracks skipped_empty separately

The `import_myqa_all` function SHALL track `skipped_empty` counts separately
from `skipped_err`, so that empty sessions (normal when importers share task
patterns) are not reported as errors.

#### Scenario: Empty session not counted as error

- GIVEN a session matches the PassFail pattern but has no PassFail data
- WHEN `import_session` returns `{"status": "skipped_empty"}`
- THEN `import_myqa_all` SHALL increment `skipped_empty` count
- AND SHALL NOT increment `skipped_err` count
- AND the summary SHALL report empty counts separately from error counts
