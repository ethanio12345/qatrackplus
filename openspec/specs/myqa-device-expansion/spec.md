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

### Requirement: Three centre-config files, distinct purposes
The centre-specific configuration surface area SHALL be split across three YAML files in `qatrack/qa/management/commands/`, each with a distinct change cadence:

| File | Purpose | Changes when |
|---|---|---|
| `myqa_device_map.yaml` | `unit_number → myQA RadiationDeviceName` mapping | myQA adds/renames devices |
| `myqa_name_overrides.yaml` | myQA condition-name → descriptive display-name overrides | physicist wants a clearer display name |
| `myqa_centre_config.yaml` | network name, sites, device classes, linac unit-type allowlist, frequency overrides | centre reorganises, renames a site, adds a unit type |

Each file is independent: editing one does not require touching the others.

#### Scenario: All three files absent
- **WHEN** none of the three YAML files exists
- **THEN** the engine emits `DeprecationWarning` for the missing centre config and `myqa_device_map.yaml`
- **AND** falls back to in-code BCHC defaults
- **AND** `myqa_name_overrides` returns `{}` (empty overrides, no warning)

#### Scenario: Adding a new device
- **WHEN** a centre adds a new linac to myQA
- **THEN** only `myqa_device_map.yaml` needs editing (one new line)
- **AND** no other config file or code change is required

