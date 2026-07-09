## MODIFIED Requirements

### Requirement: LINAC_MAP retained for unit resolution only
The LINAC_MAP dictionary SHALL be retained for mapping myQA RadiationDeviceName values to QATrack+ unit numbers. However, `task_name_patterns`, `list_slug`, and hardcoded importer classes are removed. TaskName discovery is now dynamic.

#### Scenario: Device name resolved to unit
- **WHEN** a session has RadiationDeviceName "LA317 - H192972"
- **THEN** LINAC_MAP resolves it to unit number 3

#### Scenario: Unknown device skipped
- **WHEN** a session has a RadiationDeviceName not in LINAC_MAP
- **THEN** the session is skipped with a warning

## REMOVED Requirements

### Requirement: Hardcoded task_name_patterns per importer
**Reason**: Replaced by dynamic TaskName discovery from myQA database
**Migration**: TaskNames are now queried directly from MQA_TestExecutions. No importer classes with hardcoded patterns needed.
