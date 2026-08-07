## ADDED Requirements

### Requirement: Step-by-step deployment guide
A document at `docs/myqa_deployment_guide.md` SHALL walk a new centre from `git clone` through confident clinical use, structured around the moments where decisions happen rather than around engine features. The guide SHALL cover at minimum: prerequisites, configure (local_settings.py), validate (myqa_doctor), bootstrap (bootstrap_myqa_centre), first import, tolerance review (LOUD), post-import validate, schedule registration, ongoing operation, customisation, and troubleshooting.

#### Scenario: Centre follows guide end-to-end
- **WHEN** a new centre follows the guide from section 1 to section 11
- **THEN** they end with: a configured fork, all preconditions validated, a device map built from their myQA, a 90-day historical import, tolerances reviewed against their clinical protocols, daily/weekly/monthly schedules registered, and an operational cadence documented
- **AND** no step requires reading Python source code or guessing at command invocations

### Requirement: Tolerance review as a moment-of-action warning
The deployment guide SHALL mark the tolerance review step prominently (blockquote callout with "STOP" framing) and explain that myQA's `WarnOn`/`FailOn` values become QATrack+ tolerances verbatim during import — these may not match the centre's clinical protocols and must be reviewed before clinical use.

#### Scenario: Tolerance review cannot be missed by skimming
- **WHEN** a reader skims the deployment guide
- **THEN** the tolerance review callout is visually prominent (markdown blockquote with bold "STOP" marker)
- **AND** the callout explains the risk in one sentence
- **AND** the callout links to the admin URL for tolerance review and to `myqa_validate` for tolerance-diff reporting

### Requirement: Troubleshooting section covers silent-failure modes
The deployment guide SHALL include a troubleshooting section covering the engine's four main silent-failure modes: valueless sessions (engine correctly skipped, no action needed), unmapped devices (edit `myqa_device_map.yaml` and re-run setup), slug collisions (rename the conflicting Test in admin), and missing TestLists (the TaskName has no conditions discovered — verify myQA has data).

#### Scenario: Centre hits a silent-failure mode
- **WHEN** a centre observes sessions are not being imported
- **THEN** the troubleshooting section helps them identify which of the four modes they're hitting based on symptoms
- **AND** prescribes the remedial action for each mode

### Requirement: Operational scripts reference
A companion document at `docs/myqa_operational_scripts.md` SHALL cover every Layer 4 maintenance command (`clear_myqa_data`, `clear_stale_due_dates`, `set_angular_wraparound`, `auto_approve_tlis`, `approve_myqa_taskids`, `delete_empty_tlis`, `myqa_validate`) with: purpose, when to run (cadence + triggering events), what it does (algorithm sketch), idempotency note, sample output, and BCHC operational note.

#### Scenario: Centre looks up a maintenance command
- **WHEN** a centre needs to run `clear_stale_due_dates` for the first time
- **THEN** `docs/myqa_operational_scripts.md` has a section for that command
- **AND** the section tells them the cadence (monthly), what the algorithm does (frequency-aware `max(180d, 3× nominal_interval)`), that it's idempotent, and shows sample output

### Requirement: AGENTS.md cross-link to deployment guide
The top-level `AGENTS.md` (developer-facing) SHALL include a "Sharing with another centre" section that names the three-change portability programme, points at `docs/myqa_deployment_guide.md` as the authoritative new-centre starting point, lists the three centre-config files (`myqa_device_map.yaml`, `myqa_centre_config.yaml`, `myqa_name_overrides.yaml`) with one-line descriptions, and notes the latent UnitType bug fix shipped in `myqa-centre-config-externalisation`.

#### Scenario: Developer reads AGENTS.md and finds the portability programme
- **WHEN** a developer reads the top-level `AGENTS.md`
- **THEN** they encounter a "Sharing with another centre" section near the bottom
- **AND** the section explains the system is portable across centres via the three-change programme
- **AND** the section links to `docs/myqa_deployment_guide.md` for new-centre onboarding
- **AND** the section lists the three config files a centre needs to edit

### Requirement: Documentation lives in repo and updates with changes
The deployment guide and operational scripts reference SHALL live in the repository under `docs/` (not in an external wiki) so they version with the code. Any future change proposal that modifies the engine, the bootstrap flow, or the operational scripts SHALL update the relevant docs as part of its task list.

#### Scenario: Engine change updates docs
- **WHEN** a future change proposal adds a new execution-type extractor to `qatrack.myqa_import._EXTRACTORS`
- **THEN** that change's task list includes updating `docs/myqa_deployment_guide.md` to mention the new type
- **AND** the docs do not drift out of sync with the engine
