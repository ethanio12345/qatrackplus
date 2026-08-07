# myqa-bootstrap-command Specification

## Purpose
TBD - created by archiving change myqa-centre-onboarding. Update Purpose after archive.
## Requirements
### Requirement: Two-phase interactive bootstrap command
A management command `bootstrap_myqa_centre` SHALL onboard a new centre via two phases: `--scan` (introspect myQA, write a reviewable draft YAML with auto-suggested unit numbers/types/sites) and `--apply` (read the edited draft, create Unit rows idempotently, write production `myqa_device_map.yaml` atomically, optionally run `setup_myqa_tests`).

The command SHALL NOT modify the production `myqa_device_map.yaml` during `--scan` — only the draft file (`myqa_device_map.draft.yaml`) is written, so the centre can review before any production change.

#### Scenario: Scan discovers devices and writes draft
- **WHEN** `bootstrap_myqa_centre --scan` is run against a reachable myQA database
- **THEN** the command connects, queries `SELECT DISTINCT RadiationDeviceName`, filters test fixtures, and writes `myqa_device_map.draft.yaml` with one entry per real device
- **AND** each entry includes an auto-suggested unit number, type, category, and site based on `centre_config`
- **AND** the production `myqa_device_map.yaml` is unchanged

#### Scenario: Apply creates Units and runs setup
- **WHEN** `bootstrap_myqa_centre --apply` is run after the centre has reviewed and saved the draft
- **THEN** Units are created for every entry in the draft (skipping any whose `number` already exists)
- **AND** `myqa_device_map.yaml` is written atomically (temp file + rename)
- **AND** `setup_myqa_tests` runs automatically (unless `--skip-setup`)
- **AND** a loud tolerance-review warning is printed at completion

#### Scenario: Apply is idempotent
- **WHEN** `bootstrap_myqa_centre --apply` is run twice in succession on the same draft
- **THEN** the second run logs "exists — skipping" for every Unit
- **AND** no duplicate Units are created
- **AND** `myqa_device_map.yaml` is rewritten with identical contents

#### Scenario: Non-interactive mode emits skeleton
- **WHEN** `bootstrap_myqa_centre --scan --non-interactive` is run
- **THEN** the draft YAML is written with every discovered device as a commented-out line
- **AND** the centre uncomments/edits the entries they want, then runs `--apply`

### Requirement: Test-fixture device filtering
The `--scan` phase SHALL filter out device names matching a configurable regex (default `^(z*[Dd]ummy|test|tbd)\b`) before writing the draft. The filtered devices SHALL be summarised in the scan output so the centre can verify nothing real was excluded.

#### Scenario: DUMMY devices filtered by default
- **WHEN** myQA contains devices `DUMMY LINAC`, `zzDummy Linac`, `RFT26 - H197686`
- **AND** `bootstrap_myqa_centre --scan` is run with default flags
- **THEN** the draft contains only `RFT26 - H197686`
- **AND** the scan output lists `"Filtered 2 test fixtures: DUMMY LINAC, zzDummy Linac"`

#### Scenario: Filter disabled
- **WHEN** `bootstrap_myqa_centre --scan --no-filter-dummy` is run
- **THEN** no devices are filtered; all show up in the draft

#### Scenario: Custom filter regex
- **WHEN** `bootstrap_myqa_centre --scan --dummy-regex '^(TEST|DEV)'` is run
- **THEN** only devices matching the custom regex are filtered

### Requirement: Atomic production YAML write
The `--apply` phase SHALL write `myqa_device_map.yaml` via temp-file + `os.fsync` + `os.rename`, so a crash mid-write leaves the existing file untouched.

#### Scenario: Crash during apply preserves existing map
- **WHEN** `--apply` is interrupted between opening the temp file and the rename
- **THEN** the existing `myqa_device_map.yaml` is unchanged
- **AND** a stale `.tmp` file may exist (the next successful `--apply` overwrites it)

### Requirement: Loud tolerance warning at apply time
The `--apply` phase SHALL print a prominent banner at completion warning that tolerances were auto-configured from myQA defaults and may not match the centre's clinical protocols.

#### Scenario: Warning printed after apply completes
- **WHEN** `bootstrap_myqa_centre --apply` finishes successfully
- **THEN** a banner is printed containing: (a) the count of UTIs created/updated with tolerances; (b) a URL to the QATrack+ admin for tolerance review; (c) a reminder to run `myqa_validate` (from the follow-on change) after the first import

