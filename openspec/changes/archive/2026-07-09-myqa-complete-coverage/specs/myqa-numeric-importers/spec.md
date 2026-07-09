## ADDED Requirements

### Requirement: Numeric importer subclasses for all task namespaces

The system SHALL include `MyqaNumericImportBase` subclasses covering every
myQA task namespace that uses the Numeric execution type. Each subclass
SHALL specify `task_name_patterns`, `list_slug`, and inherit
`extract_results`/`discover_setup_tests` from the base class.

#### Scenario: CT daily QA import

- GIVEN myQA has Numeric test executions under task name
  `3.Sim.CT.D - Daily QA (RTs)` for device `CPMCC CT22`
- WHEN the `MyqaCtDailyImport` importer runs
- THEN it SHALL query `MQA_Numeric_TestConditionExecutions` for those sessions
- AND create TestInstances under the `myqa_ct_daily` test list for unit 100

#### Scenario: MRI daily QA import

- GIVEN myQA has Numeric test executions under task name
  `3.Sim.MRI.D - Daily QA` for device `CPMCC MRI23 Magnetom Vida 3T`
- WHEN the `MyqaMriDailyImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_mri_daily` test list
  for unit 101

#### Scenario: HDR brachytherapy import

- GIVEN myQA has Numeric test executions under task names `5.Tmt.HDR.%`
  for device `Flexitron19`
- WHEN the `MyqaHdrImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_hdr` test list
  for unit 200

#### Scenario: Physics equipment import

- GIVEN myQA has Numeric test executions under task names `2.Phys.%`
  (e.g., `2.Phys.Chamber.Q`, `2.Phys.Thermometer.M - Monthly`)
  for various physics devices
- WHEN the `MyqaPhysicsImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_physics` test list
- AND each device's data SHALL be assigned to the correct unit number

#### Scenario: Exactrac import

- GIVEN myQA has Numeric test executions under task names `5.Tmt.ET.D%`,
  `5.Tmt.ET.W%`, `5.Tmt.ET.M%` for device `Exactrac_LA317`
- WHEN the `MyqaExactracImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_exactrac` test list
  for unit 3

### Requirement: LINAC safety and IGRT Numeric import

The system SHALL import Numeric data from LINAC safety/mechanical, IGRT,
annual, and quarterly tasks that are currently not captured by any importer.

#### Scenario: Monthly safety/mechanical import

- GIVEN myQA has Numeric test executions under
  `5.Tmt.Linac.M.Safety/Mechanical - Monthly QA`
- WHEN the `MyqaLinacSafetyImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_linac_safety` test list

#### Scenario: Annual QA import

- GIVEN myQA has Numeric test executions under `5.Tmt.Linac.Y%` and
  `5.Tmt.Linac.6M%`
- WHEN the `MyqaAnnualImport` importer runs
- THEN it SHALL create TestInstances under the `myqa_annual` test list

### Requirement: Dynamic test discovery per task pattern

Each Numeric importer's `discover_setup_tests` SHALL query
`MQA_Numeric_TestConditionExecutions` (filtered by the importer's
`task_name_patterns`) to discover all distinct test names, tolerances
(WarnOn/FailOn/IsRelative/LimitTendency), and Expected values.

#### Scenario: Discovery of physics equipment tests

- GIVEN the `2.Phys.Chamber.Q` task has Numeric conditions named
  "NDw", "Ptp", "Pion" with WarnOn/FailOn values
- WHEN `MyqaPhysicsImport.discover_setup_tests()` runs
- THEN it SHALL return specs for each test name
- AND each spec SHALL include warn/fail tolerance values
- AND the test slugs SHALL use the `myqa_physics_` prefix

#### Scenario: Discovery across multiple task patterns

- GIVEN `MyqaExactracImport` has patterns `["5.Tmt.ET.D%", "5.Tmt.ET.W%",
  "5.Tmt.ET.M%"]`
- WHEN `discover_setup_tests()` runs
- THEN it SHALL query all patterns and return the union of discovered tests
- AND duplicate test names across patterns SHALL be deduplicated

### Requirement: Expected value capture for references

The Numeric `extract_results` method SHALL capture the `Expected` column from
`MQA_Numeric_TestConditionExecutions` in addition to `Actual`, so that
per-session reference values can be set on TestInstances.

#### Scenario: Expected value stored as reference

- GIVEN a Numeric test condition with Actual=1.020 and Expected=1.000
- WHEN the session is imported
- THEN the TestInstance SHALL have value=1.020
- AND a Reference object with value=1.000 SHALL be assigned to the TestInstance
- AND pass_fail SHALL be evaluated against the tolerance using this reference

### Requirement: Registration in TASK_TYPE_REGISTRY

All new importer classes SHALL be registered in `TASK_TYPE_REGISTRY` so that
`import_myqa_all()` and `setup_myqa_tests` can discover and run them.

#### Scenario: All types run during full import

- GIVEN the `import_myqa` management command is run without `--task` flag
- WHEN `import_myqa_all()` iterates TASK_TYPE_REGISTRY
- THEN all new importer types SHALL be included in the iteration
- AND sessions from all device categories SHALL be imported
