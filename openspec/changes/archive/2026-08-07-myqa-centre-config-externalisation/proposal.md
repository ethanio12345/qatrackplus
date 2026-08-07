## Why

The myQA auto-detection engine (`qatrack/myqa_import.py` and the `setup_myqa_tests` / `import_myqa` management commands) is already centre-agnostic: every SQL query is parameterised against the standard IBA myQA product schema, and no TaskName, device name, or protocol literal appears in any query string. However, six places in the surrounding code are still hardcoded to BCHC/CPMCC and would break or silently produce wrong results at another hospital:

1. `myqa_device_map.yaml` contains 129 lines of BCHC/CPMCC device names (already config-driven; contents must be regenerable per site).
2. `create_myqa_units.py` hardcodes BCHC/CPMCC/WSLHD site prefixes and unit-number-range categories in Python.
3. `local_settings.py` ships live myQA credentials and a BCHC `sys.path` entry (committed in this dev repo).
4. `setup_myqa_tests.py` hardcodes `category_id=1` for every created Test — fails on a centre that has re-seeded `qa_category`.
5. `setup_myqa_tests.py:153` and `qa/tasks.py:73` use `User.objects.get(username="QATrack+ Internal")` with no fallback; crashes on first run if the user doesn't exist (a `get_internal_user()` helper at `qa/utils.py:188` already exists for this and is just not being used).
6. **Latent BCHC bug:** `create_myqa_units.py:14` creates linacs with `UnitType.name = "Treatment LINAC"`, but `reports/qa_selection.py:18-32`'s `LINAC_UNIT_TYPE_NAMES` allowlist doesn't include that string — so myQA-created linacs (including RFT26) are silently invisible to `clear_stale_due_dates --linacs-only` and the linac QA PDF archive.

This change externalises every centre-specific value to a single YAML config file, fixes the latent UnitType bug, and makes the category/user lookups robust. BCHC's behaviour is preserved byte-for-byte because the YAML ships with the current BCHC values as defaults.

This is the first of three changes comprising the myQA centre-portability programme. It is the prerequisite for the bootstrap/onboarding (`myqa-centre-onboarding`) and trust-and-ops (`myqa-centre-trust-and-ops`) changes that follow.

## What Changes

- **NEW** `qatrack/qa/management/commands/myqa_centre_config.yaml` — single config file holding: network name, multi-site list (slug/name/device-prefixes), device-class rules (pattern → unit_type + category), linac unit-type allowlist, optional frequency-inference overrides. Ships with BCHC defaults extracted from current `create_myqa_units.py` constants.
- **NEW** `qatrack/myqa_import.py:_load_centre_config()` — loader helper (analogous to existing `_load_device_map()`), with module-level cache and graceful fallback to BCHC defaults + deprecation warning when the YAML is absent.
- **MODIFIED** `qatrack/qa/management/commands/create_myqa_units.py` — delete `UNIT_CATEGORIES` constant and `_site_for()` function; replace with config-driven lookups against `myqa_centre_config.yaml`.
- **MODIFIED** `qatrack/qa/management/commands/setup_myqa_tests.py` — replace `category_id=1` (lines 317, 344) with a `_default_category()` helper that tries slug `"uncategorised"`, then `Category.objects.first()`, then PK 1; replace `User.objects.get(username="QATrack+ Internal")` (line 153) with `qatrack.qa.utils.get_internal_user()`.
- **MODIFIED** `qatrack/qa/tasks.py` — replace `User.objects.get(username="QATrack+ Internal")` (line 73) with `get_internal_user()`.
- **MODIFIED** `qatrack/reports/qa_selection.py` — replace hardcoded `LINAC_UNIT_TYPE_NAMES` (lines 18-32) with a read from `centre_config["linac_unit_type_names"]`. Default value includes `"Treatment LINAC"` (fixes the latent bug).
- **MODIFIED** `qatrack/myqa_import.py:infer_frequency()` — move the four module-level frequency regex constants into a function that reads from `centre_config["frequency_inference"]` if present, else uses the current IBA-template-path defaults.
- **NEW** `qatrack/local_settings.example.py` — placeholder version of `local_settings.py` with redacted `MYQA_*` credentials and a clear "copy and fill in" header comment.
- **MODIFIED** `qatrack/local_settings.py` — add header comment marking it as BCHC-dev-only and pointing at the `.example.py` template.

## Capabilities

### New Capabilities
- `myqa-centre-config`: A single YAML configuration file (`myqa_centre_config.yaml`) externalises all centre-specific values (site list, device-class rules, linac unit-type allowlist, frequency inference overrides) so the Python engine and management commands contain no centre-specific literals. Multi-site-per-deploy is the default schema shape.

### Modified Capabilities
- `dynamic-taskname-discovery`: Frequency inference regexes are now overridable via `centre_config["frequency_inference"]`. Category and internal-user lookups are now robust (slug → first → PK fallback; `get_internal_user()` helper instead of hard `.get()`).
- `myqa-device-expansion`: `LINAC_MAP` / `myqa_device_map.yaml` continues to map devices to units, but is now one of three config files (alongside the new `myqa_centre_config.yaml` and the existing `myqa_name_overrides.yaml`) instead of the only one.
- `qa-suite-selection`: `LINAC_UNIT_TYPE_NAMES` is now read from `centre_config["linac_unit_type_names"]` (default includes `"Treatment LINAC"`, fixing the latent bug where myQA-created linacs were invisible to `clear_stale_due_dates --linacs-only` and the linac QA archive).

## Impact

- **Files added (2):** `qatrack/qa/management/commands/myqa_centre_config.yaml`, `qatrack/local_settings.example.py`.
- **Files modified (6):** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/create_myqa_units.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`, `qatrack/qa/tasks.py`, `qatrack/reports/qa_selection.py`, `qatrack/local_settings.py` (header comment only).
- **Tests added (~9):**
  - `test_centre_config.py` (3): load YAML, fall back to BCHC defaults when file absent, schema validation for required keys.
  - Extend `test_setup_schedule.py` (1): verify `_default_category()` lookup path.
  - Extend `test_qa_selection.py` or new file (3): verify `LINAC_UNIT_TYPE_NAMES` is config-driven; verify `"Treatment LINAC"` is now matched.
  - Extend `test_create_myqa_units.py` (2): verify site resolution and unit categorisation are config-driven.
- **Database:** none. No migrations; no data changes. BCHC continues to work identically (default config = BCHC values).
- **Clinical safety:** none. No tolerance, reference, or pass/fail behaviour changes. Pure refactor + latent bug fix.
- **Backwards compatibility:** 100%. If `myqa_centre_config.yaml` is absent, the engine emits a `DeprecationWarning` and falls back to in-code BCHC defaults equivalent to today's behaviour.
- **Test strategy:** Every change covered by a unit test. BCHC values extracted to YAML verified against pre-refactor output for the existing device map (regression check). CI runs `uv run pytest -x -m "not selenium"`.

## Non-goals

- New management commands (`bootstrap_myqa_centre`, `myqa_doctor`, `myqa_validate`) — those belong to the follow-on `myqa-centre-onboarding` and `myqa-centre-trust-and-ops` changes.
- Deployment guide and at-action-time warnings — those belong to `myqa-centre-trust-and-ops`.
- Tolerance auto-configuration or post-import sanity reports — out of scope for the portability programme entirely (per decision: "document loudly, ship anyway").
- QATrack+ pip-installable plugin packaging — out of scope (deployment model is fork-and-config).
