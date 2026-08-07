# myqa-doctor-validation Specification

## Purpose
TBD - created by archiving change myqa-centre-onboarding. Update Purpose after archive.
## Requirements
### Requirement: Precondition validator command
A management command `myqa_doctor` SHALL run a battery of checks covering settings, myQA connectivity, fixtures, statuses, frequencies, user, categories, device-map integrity, and dependencies. The command SHALL exit 0 if all checks pass, exit 1 if any "FAIL"-severity check fails, and print warnings for "WARN"-severity issues without affecting exit code.

#### Scenario: All checks pass
- **WHEN** `myqa_doctor` is run against a fully-configured centre
- **THEN** every check prints `[OK]`
- **AND** exit code is 0

#### Scenario: Hard failure exits non-zero
- **WHEN** any of checks 1 (settings), 2 (connection), 3 (device map exists), 5 (internal user), 6 (category), 7 (status "Approved"), 10 (default AutoReviewRuleSet), 12 (croniter) fail
- **THEN** the failing check prints `[FAIL]` with a remediation hint
- **AND** exit code is 1

#### Scenario: Soft warning does not fail
- **WHEN** any of checks 4 (centre config), 8 (status "skipped"), 9 (frequencies), 11 (device-map-Unit coverage) fail
- **THEN** the failing check prints `[WARN]` with a remediation hint
- **AND** exit code is 0 unless a hard check also fails

### Requirement: Auto-fix for soft preconditions
Unless `--no-autofix` is passed, `myqa_doctor` SHALL auto-create the auto-creatable preconditions: the "QATrack+ Internal" user (check 5), the "skipped" TestInstanceStatus (check 8), missing Frequencies (check 9), and the "Uncategorised" Category if `_default_category()` would fail (check 6).

#### Scenario: Auto-fix creates missing items
- **WHEN** `myqa_doctor` is run without `--no-autofix`
- **AND** the "skipped" status is missing
- **THEN** the status is created via `ensure_statuses_exist()`
- **AND** the check prints `[FIXED] created missing 'skipped' status`

#### Scenario: No-autofix previews only
- **WHEN** `myqa_doctor --no-autofix` is run
- **AND** the "skipped" status is missing
- **THEN** the check prints `[WARN] missing (would auto-create; re-run without --no-autofix)`
- **AND** no database changes are made

### Requirement: Machine-readable output for CI
`myqa_doctor --json` SHALL emit a single JSON object on stdout with the structure `{"checks": [{"id": 1, "name": "...", "status": "OK|FAIL|WARN|FIXED", "detail": "..."}], "exit_code": 0|1}` for use in continuous-integration pipelines.

#### Scenario: JSON output structure
- **WHEN** `myqa_doctor --json` is run
- **THEN** stdout is a single valid JSON object
- **AND** the object contains a `checks` array with one entry per check
- **AND** the object contains an `exit_code` integer matching the process exit code

### Requirement: Twelve specific checks
`myqa_doctor` SHALL implement exactly the following checks in order, each with a stable integer ID for machine-parseable output:

| ID | Check | Severity |
|---|---|---|
| 1 | `settings.MYQA_DB_*` configured | FAIL |
| 2 | myQA connection works (`SELECT 1`, 5s timeout) | FAIL |
| 3 | `myqa_device_map.yaml` exists with ≥1 entry | FAIL |
| 4 | `myqa_centre_config.yaml` exists | WARN |
| 5 | "QATrack+ Internal" user exists (autofixable) | FAIL |
| 6 | `_default_category()` resolves (autofixable) | FAIL |
| 7 | `TestInstanceStatus` slug "Approved" exists | FAIL |
| 8 | `TestInstanceStatus` slug "skipped" exists (autofixable) | WARN |
| 9 | All required `Frequency` slugs exist (autofixable) | WARN |
| 10 | `AutoReviewRuleSet` with `is_default=True` exists | FAIL |
| 11 | Every device in `myqa_device_map.yaml` has a matching Unit | WARN |
| 12 | `croniter` installed | FAIL |

#### Scenario: Stable check IDs
- **WHEN** `myqa_doctor --json` is run across multiple versions of the command
- **THEN** the integer `id` of each check remains stable (a centre's automation can rely on `id == 1` always being the settings check)
- **AND** new checks are added at the end with new IDs (existing IDs are not reused for different checks)

