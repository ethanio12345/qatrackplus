# Myqa Device Expansion Specification

## Purpose

Capability promoted from the `myqa-dynamic-taskname-import` OpenSpec change (see
`openspec/changes/archive/...` for design context).

## Requirements

### Requirement: LINAC_MAP retained for unit resolution only
The LINAC_MAP dictionary SHALL be retained for mapping myQA RadiationDeviceName values to QATrack+ unit numbers. However, `task_name_patterns`, `list_slug`, and hardcoded importer classes are removed. TaskName discovery is now dynamic.

#### Scenario: Device name resolved to unit
- **WHEN** a session has RadiationDeviceName "LA317 - H192972"
- **THEN** LINAC_MAP resolves it to unit number 3

#### Scenario: Unknown device skipped
- **WHEN** a session has a RadiationDeviceName not in LINAC_MAP
- **THEN** the session is skipped with a warning
