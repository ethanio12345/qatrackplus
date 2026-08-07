## 1. `bootstrap_myqa_centre --scan`

- [x] 1.1 Create `qatrack/qa/management/commands/bootstrap_myqa_centre.py` with the `BaseCommand` skeleton, args `--scan`, `--apply`, `--skip-setup`, `--non-interactive`, `--dummy-regex`, `--no-filter-dummy`
- [x] 1.2 Implement `_scan()`: connect to myQA, `SELECT DISTINCT RadiationDeviceName FROM MQA_TestExecutions WHERE RadiationDeviceName IS NOT NULL ORDER BY RadiationDeviceName`, return list
- [x] 1.3 Implement `_filter_dummy(devices, regex)`: filter out names matching `^(z*[Dd]ummy|test|tbd)\b` (or custom regex), print summary of filtered devices
- [x] 1.4 Implement `_suggest_unit_number(name, existing_units)`: if Unit with exact name exists reuse its number; if similar-name exists (Levenshtein ≤ 3) suggest that + warn; else suggest `max(Unit.number) + 1`
- [x] 1.5 Implement `_suggest_class(name, centre_config)`: iterate `centre_config["device_classes"]`, return first match's `(unit_type, category)`; fallback `("Other", "Other")`
- [x] 1.6 Implement `_suggest_site(name, centre_config)`: iterate `centre_config["sites"]`, return first match's `(slug, name)`; fallback `sites[0]`
- [x] 1.7 Implement `_write_draft_yaml(devices_with_suggestions, path)`: write `myqa_device_map.draft.yaml` with full comments showing the suggestions
- [x] 1.8 Implement `--non-interactive` mode: write every device as a commented-out line with suggestions inline
- [x] 1.9 Verify: run `--scan` against the BCHC myQA; confirm it discovers 73 real devices + filters 14 DUMMY fixtures; draft YAML is well-formed
- [x] 1.10 Verify: `--no-filter-dummy` includes the 14 DUMMY entries in the draft

## 2. `bootstrap_myqa_centre --apply`

- [x] 2.1 Implement `_read_draft_yaml(path)`: parse draft, validate structure (dict of `{unit_number_int: device_name_str}` or list form for multi-name units)
- [x] 2.2 Implement uniqueness validation: every unit_number in draft must be unique AND not collide with existing `Unit.objects.exclude(number__in=draft_numbers).values_list("number")` for the same device name
- [x] 2.3 Implement `_create_units(entries, centre_config)`: for each entry, if Unit with that `number` exists log "exists — skipping", else create with `name=device_name`, `type=unit_type` (looked up via `UnitType.objects.get_or_create(name=...)`), `site=site` (looked up via `Site.objects.get_or_create(slug=...)`)
- [x] 2.4 Implement `_write_production_yaml(entries, path)`: atomic write to `myqa_device_map.yaml` (write `.tmp`, fsync, rename)
- [x] 2.5 Implement `_run_setup()`: shell out to `manage.py setup_myqa_tests` via `subprocess.run` (capture output, surface failures clearly)
- [x] 2.6 Implement the loud tolerance warning banner printed at end of `--apply` (per the design's "document loudly at-action-time" pattern)
- [x] 2.7 Verify: `--apply` against a 5-device test fixture creates 5 Units, writes the YAML atomically, and runs setup successfully
- [x] 2.8 Verify: re-running `--apply` on the same fixture is a no-op for existing Units (idempotency)
- [x] 2.9 Verify: `--skip-setup` writes YAML and creates Units but does not shell out to setup

## 3. `myqa_doctor`

- [x] 3.1 Create `qatrack/qa/management/commands/myqa_doctor.py` with `BaseCommand` skeleton, args `--no-autofix`, `--json` (machine-readable output)
- [x] 3.2 Implement check 1: `_check_settings()` — verify `settings.MYQA_DB_SERVER`, `MYQA_DB_NAME`, `MYQA_DB_USERNAME`, `MYQA_DB_PASSWORD` are all set (not None / not empty)
- [x] 3.3 Implement check 2: `_check_connection()` — `get_connection()` + `SELECT 1`, 5-second timeout
- [x] 3.4 Implement check 3: `_check_device_map()` — `myqa_device_map.yaml` exists and parses to ≥1 entry
- [x] 3.5 Implement check 4: `_check_centre_config()` — warn (not fail) if `myqa_centre_config.yaml` is absent
- [x] 3.6 Implement check 5: `_check_internal_user()` — `User.objects.filter(username="QATrack+ Internal").exists()`; auto-create via `get_internal_user()` unless `--no-autofix`
- [x] 3.7 Implement check 6: `_check_category()` — `_default_category()` returns a Category; auto-create "Uncategorised" if missing unless `--no-autofix`
- [x] 3.8 Implement check 7: `_check_status("Approved")` — exists; fail if not (cannot auto-create — admin decision)
- [x] 3.9 Implement check 8: `_check_status("skipped")` — exists; auto-create via `ensure_statuses_exist()` unless `--no-autofix`
- [x] 3.10 Implement check 9: `_check_frequencies()` — slugs `daily`, `weekly`, `monthly`, `quarterly`, `annual`, `once_off`, `other` all exist; auto-create missing via `ensure_frequencies_exist()` unless `--no-autofix`
- [x] 3.11 Implement check 10: `_check_default_autoreview_ruleset()` — `AutoReviewRuleSet.objects.filter(is_default=True).exists()`; fail if not
- [x] 3.12 Implement check 11: `_check_device_map_units()` — for every `unit_number` in `myqa_device_map.yaml`, verify a Unit exists; warn (not fail) listing missing
- [x] 3.13 Implement check 12: `_check_croniter()` — `import croniter` succeeds; fail if not
- [x] 3.14 Implement output formatter: `[OK]` / `[FAIL]` / `[WARN]` per check with remediation hint; exit 1 if any FAIL
- [x] 3.15 Implement `--json` flag for machine-readable output (CI integration)
- [x] 3.16 Verify: run against BCHC production settings — all 12 checks pass

## 4. setup_myqa_tests site/class miss reporting

- [x] 4.1 In `qatrack/qa/management/commands/setup_myqa_tests.py:_setup_one_taskname`, after `discover_units_for_taskname` returns, iterate the units and check each device's `device_class` lookup result; if any unit's device falls through to the `"Other"` fallback, print to stderr: `"NOTICE: device {name!r} matched no device_class rule — falling back to 'Other'. Consider extending myqa_centre_config.yaml."`
- [x] 4.2 Verify: with current BCHC device map, the notice fires for any unmatched devices (there shouldn't be any — confirm zero notices)

## 5. Auto-register weekly setup schedule in apps.py

- [x] 5.1 In `qatrack/qa/apps.py:do_scheduling`, add a third `_schedule_periodic_task` call registering `qatrack.qa.tasks.run_setup_myqa_tests` as name `"myQA Weekly Setup"`, schedule_type `Schedule.CRON`, cron `"0 2 * * 0"`
- [x] 5.2 Verify: on a fresh `migrate`, the Schedule is created automatically
- [x] 5.3 Verify: re-running `migrate` is idempotent (existing Schedule updated, not duplicated)
- [x] 5.4 Verify: `setup_myqa_setup_schedule` command still works as an explicit re-registration (idempotent alongside the auto-registration)

## 6. Tests

- [x] 6.1 Create `qatrack/qa/tests/test_bootstrap.py` with: (a) `test_scan_lists_devices` — mocked myQA returns 5 fake devices, scan discovers all 5; (b) `test_scan_filters_dummy` — DUMMY-prefixed devices excluded, summary printed; (c) `test_scan_writes_draft_yaml` — draft file written, parses correctly; (d) `test_apply_creates_units` — 5 entries in draft → 5 Units created with right type/site; (e) `test_apply_idempotent_rerun` — second `--apply` is a no-op; (f) `test_non_interactive_emits_skeleton` — `--non-interactive` produces commented YAML
- [x] 6.2 Create `qatrack/qa/tests/test_doctor.py` with: (a) `test_all_checks_pass` — fresh test DB with all fixtures loaded, all 12 checks green; (b) `test_missing_internal_user_autofixed` — without Internal user, doctor auto-creates it; (c) `test_missing_status_fails` — without "Approved" status, doctor fails check 7 with clear message; (d) `test_missing_device_map_warns` — without `myqa_device_map.yaml`, doctor fails check 3
- [x] 6.3 Add to `qatrack/qa/tests/test_setup_schedule.py`: (a) test that `apps.do_scheduling` creates the "myQA Weekly Setup" Schedule on `post_migrate`; (b) idempotency test

## 7. Regression + lint

- [x] 7.1 Run `uv run ruff check .` — no new errors
- [x] 7.2 Run `uv run black --target-version py312 .` — all formatted
- [x] 7.3 Run `uv run python manage.py check` — no system check issues
- [x] 7.4 Run `uv run pytest -x -m "not selenium" qatrack/qa/tests/ qatrack/reports/tests/` — all pass (currently 403 + ~10 new tests)
- [x] 7.5 End-to-end smoke: simulate a fresh centre by running `myqa_doctor` against a temp SQLite DB with `migrate` run but no fixtures — verify doctor guides the user through autofixing what's auto-fixable and failing loudly on what isn't
