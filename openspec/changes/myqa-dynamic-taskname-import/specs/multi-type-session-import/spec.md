## ADDED Requirements

### Requirement: Aggregate multiple execution types per session
For each myQA session, the import SHALL detect which execution types are present (Numeric, PassFail, Profile, Wedge, Energy, Output, MLC, CBCT, Planar, VMAT, Winston-Lutz) and extract results from all of them. All results SHALL be merged into a single dict and written to one TestListInstance.

#### Scenario: Multi-type session
- **WHEN** a Monthly Dosimetry session has Numeric, Profile (×8), Wedge (×3), Output (×2), and PassFail (×3) executions
- **THEN** one TestListInstance is created under the TaskName's TestList, with TestInstances for all extracted results combined

#### Scenario: Single-type session
- **WHEN** a Daily Constancy session has only Numeric executions
- **THEN** one TestListInstance is created with TestInstances only from the Numeric extraction

### Requirement: Session queried by exact TaskName
The import SHALL query sessions using exact TaskName match (`WHERE TaskName = %s`), not pattern LIKE. Each TaskName is processed independently.

#### Scenario: Exact match
- **WHEN** importing TaskName "5.Tmt.Linac.D - myQA Daily Constancy Check"
- **THEN** sessions are queried with `WHERE TaskName = '5.Tmt.Linac.D - myQA Daily Constancy Check'`

### Requirement: Results mapped to shared Test slugs
Each extracted result key (condition name, DisplayName, column name) SHALL be slugified without a list prefix to match the Test slug created during setup. The import SHALL look up the Test by slug within the TestList's memberships.

#### Scenario: Condition maps to shared test
- **WHEN** extraction produces {"Center (crossline)": 1.05}
- **THEN** the value 1.05 is stored as a TestInstance for Test with slug "center_crossline"

#### Scenario: Unknown condition skipped
- **WHEN** extraction produces a condition name that has no matching Test in the TestList
- **THEN** the result is skipped (not stored) and logged as a warning

### Requirement: Duplicate detection per TaskName
Duplicate detection SHALL use a taskid TestInstance storing the myQA TaskExecutionId (UUID) as string_value. The taskid Test slug SHALL be `slugify(TaskName)_taskid`.

#### Scenario: Already imported session
- **WHEN** a session with TaskExecutionId "abc-123" was previously imported
- **THEN** the session is skipped (status: skipped_dup)

#### Scenario: New session
- **WHEN** a session with TaskExecutionId "def-456" has no matching taskid TestInstance
- **THEN** the session is imported, and a taskid TestInstance storing "def-456" is created

### Requirement: MatrixX specialized extractors retained
The existing specialized extraction logic for Profile, Wedge, Energy, Output, MLC, CBCT, Planar, VMAT, and Winston-Lutz SHALL be retained. Each extractor SHALL be adapted to emit shared slugs (no list prefix) and contribute results to the session's merged dict.

#### Scenario: Profile extraction
- **WHEN** a session has Profile executions
- **THEN** the Profile extractor reads `MQA_Dosimetry_Profile_Results`, extracts DisplayName + Actual values, and contributes them to the results dict

#### Scenario: MLC extraction
- **WHEN** a session has MLC executions
- **THEN** the MLC extractor reads `MQA_MDL_MlcQA_Results`, parses column prefixes (e.g., "MaximumDeviation"), and contributes them as condition names

#### Scenario: No matching extractor
- **WHEN** a session has an execution type with no specialized extractor
- **THEN** that execution type's results are skipped and a warning is logged

### Requirement: Import 90 days first, then full history
The import SHALL support `--days N` parameter. The operational sequence is: import 90 days first for user review, then import 3650 days for full history after approval.

#### Scenario: Limited import
- **WHEN** `import_myqa --days 90` runs
- **THEN** only sessions from the last 90 days are imported across all TaskNames

#### Scenario: Full import
- **WHEN** `import_myqa --days 3650` runs after 90-day review
- **THEN** all sessions from the last 10 years are imported; previously imported sessions (from 90-day run) are skipped as duplicates
