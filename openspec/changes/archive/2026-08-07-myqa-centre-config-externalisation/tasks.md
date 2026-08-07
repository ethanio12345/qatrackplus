## 1. New `myqa_centre_config.yaml` + loader

- [x] 1.1 Create `qatrack/qa/management/commands/myqa_centre_config.yaml` with the BCHC defaults extracted from `create_myqa_units.py:13-62` (sites, device_classes, linac_unit_type_names including "Treatment LINAC", optional frequency_inference)
- [x] 1.2 Add `_BCHC_DEFAULT_CENTRE_CONFIG` constant to `qatrack/myqa_import.py` whose dict values reproduce the YAML contents exactly (for fallback)
- [x] 1.3 Add `_load_centre_config()` helper in `qatrack/myqa_import.py` (mirrors `_load_device_map()` at lines 67-76: module-level cache `_CENTRE_CONFIG_CACHE`, lazy read, `DeprecationWarning` + fallback to `_BCHC_DEFAULT_CENTRE_CONFIG` when file is missing)
- [x] 1.4 Verify: `python -c "from qatrack.myqa_import import _load_centre_config; print(_load_centre_config())"` returns the expected dict
- [x] 1.5 Verify: temporarily move `myqa_centre_config.yaml` aside, re-import, confirm `DeprecationWarning` fires and fallback dict is returned

## 2. Refactor `create_myqa_units.py` to be config-driven

- [x] 2.1 Delete `UNIT_CATEGORIES` constant (lines 13-30) and `_site_for()` function (lines 41-62) from `qatrack/qa/management/commands/create_myqa_units.py`
- [x] 2.2 Replace with config-driven helpers: `_classify_device(name)` iterates `centre_config["device_classes"]` and returns first match's `(unit_type, category)`; `_site_for(name)` iterates `centre_config["sites"]` and returns first match's `(slug, name)`
- [x] 2.3 Preserve the existing Unit-creation loop (lines 95-139) — only the lookup helpers change
- [x] 2.4 Verify: run `create_myqa_units --dry-run` against today's `myqa_device_map.yaml`; diff output before/after refactor — must be byte-identical
- [x] 2.5 Verify: run with `myqa_centre_config.yaml` moved aside; confirm DeprecationWarning and identical BCHC fallback output

## 3. Robust category + internal-user lookups in `setup_myqa_tests.py`

- [x] 3.1 Add `_default_category()` helper in `qatrack/qa/management/commands/setup_myqa_tests.py` that tries `Category.objects.get(slug="uncategorised")`, then `Category.objects.order_by("id").first()`, then `Category.objects.get(pk=1)` (each wrapped in try/except)
- [x] 3.2 Replace `category_id=1` at line 317 (taskid Test) and line 344 (condition Tests) with `category=_default_category()` (pass the Category object instead of the PK)
- [x] 3.3 Replace `User.objects.get(username="QATrack+ Internal")` at line 153 with `from qatrack.qa.utils import get_internal_user; internal_user = get_internal_user()`
- [x] 3.4 Verify: `setup_myqa_tests --dry-run` runs without error on the existing BCHC DB
- [x] 3.5 Verify: temporarily rename the "QATrack+ Internal" user, re-run, confirm helper recreates it instead of crashing

## 4. Same internal-user fix in `qatrack/qa/tasks.py`

- [x] 4.1 Replace `User.objects.get(username="QATrack+ Internal")` at `qatrack/qa/tasks.py:73` with `get_internal_user()` (import from `qatrack.qa.utils`)
- [x] 4.2 Verify: `import_myqa_all` runs without error; `_get_internal_user()` is called once per TaskName batch (acceptable perf — already opening a fresh connection per TaskName)

## 5. Fix UnitType reconciliation (audit issue #6)

- [x] 5.1 In `qatrack/reports/qa_selection.py`: replace the module-level `LINAC_UNIT_TYPE_NAMES` tuple (lines 18-32) with a `_DEFAULT_LINAC_TYPES` constant (includes "Treatment LINAC") plus a `get_linac_unit_type_names()` function that reads `centre_config["linac_unit_type_names"]` (falling back to `_DEFAULT_LINAC_TYPES`)
- [x] 5.2 Audit all call sites of `LINAC_UNIT_TYPE_NAMES`; switch each to call `get_linac_unit_type_names()`. Document any call site where the function-call form is awkward (likely none — it's only used inside `select_archive_utcs` and imported by `clear_stale_due_dates`)
- [x] 5.3 Add `"Treatment LINAC"` to `_DEFAULT_LINAC_TYPES`
- [x] 5.4 Verify: write a test in `qatrack/reports/tests/` that confirms unit 437 (RFT26, type "Treatment LINAC") is now selected by `select_archive_utcs` for a `lastmonth` window where it has TLIs
- [x] 5.5 Verify: same test confirms `clear_stale_due_dates --linacs-only` would now process RFT26 if it had a stale due_date

## 6. Externalise `infer_frequency` regexes

- [x] 6.1 In `qatrack/myqa_import.py`: move the seven module-level regex constants (`_FREQ_DAILY`, `_FREQ_WEEKLY`, `_FREQ_MONTHLY`, `_FREQ_QUARTERLY`, `_FREQ_ANNUAL`, `_FREQ_6MONTHLY`, `_FREQ_COMMISSIONING` at lines 298-304) into a lazily-initialised `_get_freq_regexes()` function that reads `centre_config["frequency_inference"]` and compiles the patterns
- [x] 6.2 Cache the compiled regexes at module level after first call (memoize)
- [x] 6.3 Update `infer_frequency()` body to call `_get_freq_regexes()` instead of referencing module-level constants
- [x] 6.4 Verify: existing frequency tests pass unchanged (no behaviour change for default config)
- [x] 6.5 Verify: new test confirms override works — `infer_frequency("Daily Constancy Check")` returns `"daily"` whether or not `frequency_inference.daily` includes `"daily"` (the literal-substring fallback)

## 7. `local_settings.example.py`

- [x] 7.1 Create `qatrack/local_settings.example.py` — placeholder version of `local_settings.py` with redacted `MYQA_*` credentials, no `PHYS_REPO_SCRIPTS_PATH`, a header comment "Copy to local_settings.py and fill in your centre's details"
- [x] 7.2 Add a header comment to the existing `qatrack/local_settings.py` marking it as BCHC-dev-only and pointing at the `.example.py` template
- [x] 7.3 Verify: `diff qatrack/local_settings.example.py qatrack/local_settings.py` shows only credential/path differences, no structural changes

## 8. Tests

- [x] 8.1 Create `qatrack/qa/tests/test_centre_config.py` with three tests: (a) `_load_centre_config()` returns expected dict from the YAML; (b) returns `_BCHC_DEFAULT_CENTRE_CONFIG` when YAML is absent + emits DeprecationWarning; (c) schema validation — required keys `sites`, `device_classes`, `linac_unit_type_names` are present
- [x] 8.2 Add a test to `qatrack/qa/tests/test_setup_schedule.py` (or new file `test_default_category.py`) that verifies `_default_category()` returns a Category under all three fallback branches
- [x] 8.3 Add a test (new file `test_create_myqa_units_config.py`) that verifies site resolution and device classification are config-driven — covers one BCHC-prefix device, one CPMCC-prefix device, one unmatched device (fallback)
- [x] 8.4 Add a test (extend `qatrack/reports/tests/test_qa_selection.py`) that verifies RFT26 (unit 437) is selected by `select_archive_utcs` after the UnitType fix
- [x] 8.5 Add a test in `qatrack/qa/tests/test_centre_config.py` that verifies `infer_frequency()` works with an overridden `frequency_inference` config (e.g. custom monthly regex matching `"Monthly"` without dotted path)

## 9. Regression + lint

- [x] 9.1 Run `uv run ruff check .` — no new errors
- [x] 9.2 Run `uv run black --target-version py312 .` — all formatted
- [x] 9.3 Run `uv run python manage.py check` — no system check issues
- [x] 9.4 Run `uv run pytest -x -m "not selenium" qatrack/qa/tests/ qatrack/reports/tests/` — all pass (currently 403 + ~10 new tests)
- [x] 9.5 Re-run the RFT26 verification script from the prior plan; confirm 29/29 TaskNames still deployed, 51 TLIs still present (no regression from the refactor)
