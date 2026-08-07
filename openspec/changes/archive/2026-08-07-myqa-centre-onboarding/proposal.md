## Why

The predecessor change `myqa-centre-config-externalisation` makes the import engine portable in principle: a centre that hand-writes `myqa_device_map.yaml`, hand-creates Unit rows, and hand-runs `setup_myqa_tests` can use the system. But that's a multi-day exercise requiring reading the source code to understand the schema, interrogating myQA separately to discover device names, and typing YAML without typos.

The vision is one command, one outcome: a centre runs `bootstrap_myqa_centre`, answers prompts about their devices, and ends up with a working import system against their myQA. No code edits, no manual YAML authoring, no Python knowledge assumed.

This change introduces that command (`bootstrap_myqa_centre`) plus a precondition validator (`myqa_doctor`) that catches configuration errors before they become silent runtime failures. Both are designed for the high-trust-but-low-shared-context reality of inter-hospital open source: colleagues trust the engine but cannot assume anything about each other's myQA configuration.

This is the second of three changes in the myQA centre-portability programme. It depends on `myqa-centre-config-externalisation` for the config schema and loader.

## What Changes

- **NEW** `qatrack/qa/management/commands/bootstrap_myqa_centre.py` — interactive two-phase onboarding command:
  - `bootstrap_myqa_centre --scan`: connects to myQA, queries `SELECT DISTINCT RadiationDeviceName`, filters obvious test fixtures (configurable pattern, default `^(z*[Dd]ummy|test|tbd)`), writes `myqa_device_map.draft.yaml` with auto-suggested unit numbers/types/sites based on `centre_config["device_classes"]` and `centre_config["sites"]`.
  - User reviews/edits the draft in their editor of choice.
  - `bootstrap_myqa_centre --apply`: reads the draft, creates Unit rows (idempotent — skips existing numbers), writes the production `myqa_device_map.yaml` atomically (temp file + rename), runs `setup_myqa_tests` automatically (unless `--skip-setup`).
  - `--non-interactive` flag: emits a fully-commented starter YAML with all discovered devices commented out (alternative workflow for centres that prefer pure manual editing).
- **NEW** `qatrack/qa/management/commands/myqa_doctor.py` — precondition validator inspired by `manage.py check` but specific to myQA deployment. Runs 12 checks, exits non-zero if any fail:
  1. `settings.MYQA_DB_*` configured (no AttributeError on access).
  2. myQA connection works (open + `SELECT 1`).
  3. `myqa_device_map.yaml` exists and has ≥1 entry.
  4. `myqa_centre_config.yaml` exists (warn — not fail — if absent and using BCHC defaults).
  5. "QATrack+ Internal" user exists (auto-create via `get_internal_user()`).
  6. A Category resolvable by `_default_category()` exists.
  7. `TestInstanceStatus` slug `"Approved"` exists.
  8. `TestInstanceStatus` slug `"skipped"` exists (auto-create via `ensure_statuses_exist()`).
  9. All required `Frequency` slugs exist: `daily`, `weekly`, `monthly`, `quarterly`, `annual`, `once_off`, `other` (auto-create missing via `ensure_frequencies_exist()`).
  10. An `AutoReviewRuleSet` with `is_default=True` exists.
  11. For every device in `myqa_device_map.yaml`: corresponding `Unit` row exists.
  12. `croniter` installed (required for Schedule cron evaluation).
- **MODIFIED** `qatrack/qa/management/commands/setup_myqa_tests.py` — `_setup_one_taskname()` reports the centre's site and device-class lookup misses to stderr so the centre sees which devices fell through to `"Other"`.
- **MODIFIED** `qatrack/qa/apps.py` — `do_scheduling` post-migrate hook now also creates the weekly `myQA Weekly Setup` Schedule (currently created by the separate `setup_myqa_setup_schedule` command). The management command remains for explicit re-registration; this just makes the schedule auto-recover if dropped.

## Capabilities

### New Capabilities
- `myqa-bootstrap-command`: An interactive two-phase command (`bootstrap_myqa_centre --scan` then `--apply`) that introspects a centre's myQA database, auto-proposes unit numbers/types/sites for each device, writes a reviewable draft YAML, then creates Unit rows and runs setup. Reduces multi-day onboarding to a single command pair.
- `myqa-doctor-validation`: A precondition validator (`myqa_doctor`) that runs 12 checks covering settings, myQA connectivity, fixtures, statuses, frequencies, user, categories, device-map integrity, and dependencies. Exits non-zero if any check fails; designed as the first command a new centre runs after `git clone`.

### Modified Capabilities
- `myqa-centre-config`: `bootstrap_myqa_centre --scan` consumes `centre_config["device_classes"]` and `centre_config["sites"]` to auto-suggest classification, surfacing misconfigurations early.
- `myqa-sync`: The weekly `setup_myqa_tests` schedule (currently registered via the standalone `setup_myqa_setup_schedule` command) is now also auto-registered by the `do_scheduling` post-migrate hook, so a fresh DB deploy gets it without manual command invocation.

## Impact

- **Files added (2):** `qatrack/qa/management/commands/bootstrap_myqa_centre.py`, `qatrack/qa/management/commands/myqa_doctor.py`.
- **Files modified (2):** `qatrack/qa/management/commands/setup_myqa_tests.py` (site-miss reporting), `qatrack/qa/apps.py` (auto-register weekly setup schedule).
- **Tests added (~10):**
  - `test_bootstrap.py` (6): scan-lists-devices, scan-filters-dummy, scan-writes-draft-yaml, apply-creates-units, apply-idempotent-rerun, non-interactive-mode-emits-skeleton.
  - `test_doctor.py` (4): all-pass, missing-internal-user, missing-status-fixture, missing-device-map.
- **Database:** none. No migrations; commands operate on existing schema.
- **Dependencies:** `croniter` already declared (required by `django-q2` cron schedules); no new dependencies.
- **Clinical safety:** none. Bootstrap creates Units and runs setup (idempotent); doctor validates only. Neither touches tolerance/reference/pass_fail data.
- **Backwards compatibility:** 100%. BCHC's existing deployment is unaffected; the new commands are additive.

## Non-goals

- `myqa_validate` (post-import diff against myQA) — belongs to `myqa-centre-trust-and-ops`.
- Deployment guide documentation — belongs to `myqa-centre-trust-and-ops`.
- Tolerance review tooling — out of scope (per decision: document loudly, ship anyway).
- Web UI for bootstrap — out of scope; CLI two-phase is sufficient for the inter-hospital use case.
