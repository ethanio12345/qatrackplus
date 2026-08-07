## ADDED Requirements

### Requirement: Centre configuration externalised to YAML
All centre-specific values (network name, site list with device-prefix routing, device-to-unit_type-and-category classification rules, linac unit-type allowlist, optional frequency-inference overrides) SHALL live in a single YAML file at `qatrack/qa/management/commands/myqa_centre_config.yaml`. No Python code in the import engine or management commands SHALL contain centre-specific literals.

#### Scenario: Default config ships with BCHC values
- **WHEN** the repository is cloned
- **THEN** `myqa_centre_config.yaml` exists with BCHC/CPMCC site definitions matching today's `create_myqa_units.py` constants
- **AND** running `create_myqa_units` against today's `myqa_device_map.yaml` produces byte-identical output to the pre-refactor behaviour

#### Scenario: Centre config absent falls back gracefully
- **WHEN** `myqa_centre_config.yaml` is missing
- **THEN** `_load_centre_config()` returns a hardcoded `_BCHC_DEFAULT_CENTRE_CONFIG` dict whose values reproduce today's behaviour
- **AND** a `DeprecationWarning` is emitted once per process pointing at the new file

#### Scenario: Multi-site deploy is the default shape
- **WHEN** a centre configures multiple sites under `sites:`
- **THEN** `create_myqa_units` routes each device to the correct `Site.slug` based on the first matching `device_prefixes` entry
- **AND** Units are created with the site resolved correctly without per-site code changes

### Requirement: Loader helper mirrors existing device-map pattern
The `_load_centre_config()` helper in `qatrack/myqa_import.py` SHALL follow the same pattern as the existing `_load_device_map()`: module-level cache, lazy read on first access, dict return type.

#### Scenario: Loader is cached
- **WHEN** `_load_centre_config()` is called multiple times
- **THEN** the YAML is parsed at most once per process; subsequent calls return the cached dict

### Requirement: Frequency inference is overridable
The seven frequency regex patterns used by `infer_frequency()` SHALL be read from `centre_config["frequency_inference"]` if present, with sensible defaults matching today's IBA-template-path conventions (`\.d`, `\.w`, `\.m`, `\.q`, `\.y`, `\.6m`, `\.c`).

#### Scenario: Default frequency inference unchanged
- **WHEN** `infer_frequency("5.Tmt.Linac.D - Daily Constancy Check")` is called
- **THEN** it returns `"daily"` (matching today's behaviour)

#### Scenario: Centre overrides frequency inference
- **WHEN** `centre_config["frequency_inference"]["monthly"]` includes `"^Monthly\\s"`
- **AND** `infer_frequency("Monthly QA - Mech")` is called
- **THEN** it returns `"monthly"` without code changes

### Requirement: Robust category lookup replaces hardcoded PK
`setup_myqa_tests` SHALL resolve the default Test category via a `_default_category()` helper that tries `Category.objects.get(slug="uncategorised")`, then `Category.objects.order_by("id").first()`, then `Category.objects.get(pk=1)` — each wrapped in try/except.

#### Scenario: Slug-based lookup succeeds
- **WHEN** a Category with slug `"uncategorised"` exists
- **THEN** `_default_category()` returns it

#### Scenario: Falls back to first category
- **WHEN** no Category with slug `"uncategorised"` exists
- **AND** at least one Category exists
- **THEN** `_default_category()` returns `Category.objects.order_by("id").first()`

#### Scenario: Final fallback to PK 1
- **WHEN** no Category exists with the slug and no Category rows exist at all
- **THEN** `_default_category()` raises `Category.DoesNotExist` (the legacy behaviour) — but only in the catastrophic case where the table is empty

### Requirement: Internal user via existing helper
`setup_myqa_tests` and `qatrack/qa/tasks.py:import_myqa_all` SHALL resolve the "QATrack+ Internal" user via `qatrack.qa.utils.get_internal_user()` (which does `get_or_create`) instead of bare `User.objects.get(username=...)`.

#### Scenario: Internal user exists
- **WHEN** a User with username "QATrack+ Internal" exists
- **THEN** the helper returns the existing user; no new row created

#### Scenario: Internal user missing
- **WHEN** no User with username "QATrack+ Internal" exists
- **THEN** the helper creates one with sensible defaults
- **AND** setup/import proceeds normally (no `DoesNotExist` crash)
