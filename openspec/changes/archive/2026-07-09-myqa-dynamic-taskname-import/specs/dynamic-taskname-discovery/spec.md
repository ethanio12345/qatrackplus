## ADDED Requirements

### Requirement: Discover all myQA TaskNames
The setup command SHALL query myQA for all distinct TaskName values from `MQA_TestExecutions` where TaskName is not NULL. Each discovered TaskName SHALL become a TestList in QATrack+.

#### Scenario: Setup discovers all tasks
- **WHEN** `setup_myqa_tests` runs without `--task-type`
- **THEN** the system queries `SELECT DISTINCT TaskName FROM MQA_TestExecutions WHERE TaskName IS NOT NULL` and creates one TestList per result

#### Scenario: Setup with specific task
- **WHEN** `setup_myqa_tests` runs with `--task-name "5.Tmt.Linac.D - myQA Daily Constancy Check"`
- **THEN** only that TaskName is processed

### Requirement: TestList named from myQA TaskName
Each TestList SHALL be named verbatim from the myQA TaskName. The slug SHALL be `slugify(TaskName)` with dots and special characters replaced by underscores.

#### Scenario: TaskName becomes TestList name
- **WHEN** TaskName is `"5.Tmt.Linac.D - myQA Daily Constancy Check"`
- **THEN** TestList.name = `"5.Tmt.Linac.D - myQA Daily Constancy Check"` and TestList.slug = `"5_tmt_linac_d_myqa_daily_constancy_check"`

### Requirement: Shared Tests by condition name
Tests SHALL be named by their myQA condition name (e.g., "Center (crossline)"). The slug SHALL be `slugify(condition_name)` without any list prefix. The same condition name across different tasks SHALL map to the same Test object, shared via TestListMembership.

#### Scenario: Condition shared across tasks
- **WHEN** task A and task B both have a condition named "Flatness"
- **THEN** one Test object with slug "flatness" is created, with TestListMemberships linking it to both TestLists

#### Scenario: Condition unique to one task
- **WHEN** a condition named "00. Barometer SN" appears in only one task
- **THEN** one Test object with slug "00_barometer_sn" is created, linked to that task's TestList only

### Requirement: Disambiguate duplicate conditions within a task
When a single TaskName has multiple conditions with the same name but different tolerances, the system SHALL create separate Test objects with `_2`, `_3` suffixes appended to the slug.

#### Scenario: Duplicate condition names
- **WHEN** task "Daily Constancy Check" has "Center (crossline)" with tolerance ±1.0 and also ±2.0
- **THEN** two Tests are created: "Center (crossline)" (slug `center_crossline`) and "Center (crossline) 2" (slug `center_crossline_2`), both linked to the same TestList

### Requirement: Frequency inferred from TaskName
The system SHALL infer the QATrack+ Frequency from the TaskName naming convention. The frequency SHALL be assigned to the UnitTestCollection.

#### Scenario: Daily task
- **WHEN** TaskName contains `.D` or "Daily"
- **THEN** frequency is set to "daily"

#### Scenario: Monthly task
- **WHEN** TaskName contains `.M` or "Monthly"
- **THEN** frequency is set to "monthly"

#### Scenario: Annual task
- **WHEN** TaskName contains `.Y`, "Annual", or "Yearly"
- **THEN** frequency is set to "annual"

### Requirement: No tolerances during setup
The system SHALL NOT assign tolerances during setup. UnitTestInfo.tolerance SHALL remain NULL for all created tests. Users configure tolerances manually through QATrack+ admin after setup.

#### Scenario: Setup creates no tolerances
- **WHEN** setup completes
- **THEN** all UnitTestInfo records have tolerance_id = NULL

### Requirement: UTCs and UTIs for units with data
For each TaskName, the system SHALL create UnitTestCollections and UnitTestInfos only for units that actually have execution data for that task in myQA.

#### Scenario: Unit with data gets UTIs
- **WHEN** unit 3 (LA317) has sessions for TaskName "5.Tmt.Linac.D - myQA Daily Constancy Check"
- **THEN** a UnitTestCollection is created linking unit 3 to that TestList, and UnitTestInfos are created for each test in the list

#### Scenario: Unit without data gets nothing
- **WHEN** unit 50 (DXR) has no sessions for a linac daily task
- **THEN** no UTC or UTIs are created for unit 50 under that TestList
