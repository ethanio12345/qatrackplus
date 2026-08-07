## MODIFIED Requirements

### Requirement: Frequency inferred from TaskName
The `infer_frequency(taskname)` function SHALL parse the TaskName for frequency patterns and return one of: `daily`, `weekly`, `monthly`, `quarterly`, `semi-annual`, `annual`, `once_off`, or `other`.

The seven regex patterns SHALL be read from `centre_config["frequency_inference"]` if present (with sensible defaults matching the IBA-template-path conventions `\.d`, `\.w`, `\.m`, `\.q`, `\.y`, `\.6m`, `\.c`). A centre with non-IBA TaskName conventions (e.g. plain `"Monthly QA"` without the dotted path) can override the patterns via YAML without code changes.

The compiled regexes SHALL be cached at module level after first call (memoised) so there is no per-call performance impact.

#### Scenario: Default behaviour unchanged
- **WHEN** `infer_frequency("5.Tmt.Linac.D")` is called with no override config
- **THEN** it returns `"daily"` (matching pre-refactor behaviour)

#### Scenario: Override via config
- **WHEN** `centre_config["frequency_inference"]["monthly"]` includes `"^Monthly\\s"`
- **AND** `infer_frequency("Monthly QA - Mech")` is called
- **THEN** it returns `"monthly"`

#### Scenario: Unrecognised TaskName
- **WHEN** no pattern matches
- **THEN** `infer_frequency` returns `"other"` (unchanged)

## ADDED Requirements

### Requirement: Test category resolution
`setup_myqa_tests` SHALL resolve the default Test category via the `_default_category()` helper (slug `"uncategorised"` → `Category.objects.first()` → `Category.objects.get(pk=1)`) rather than hardcoding `category_id=1`.

#### Scenario: Centre has re-seeded categories
- **WHEN** a centre's `qa_category` table has different primary keys
- **THEN** `_default_category()` still returns a valid Category
- **AND** no `IntegrityError` is raised during setup
