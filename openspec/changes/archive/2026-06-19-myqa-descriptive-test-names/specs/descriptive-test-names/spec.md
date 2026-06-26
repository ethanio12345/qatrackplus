## ADDED Requirements

### Requirement: Strip sequence-number prefix from Test names
The setup command SHALL strip a leading sequence-number prefix (matching `^\d+\.\s*`) from each myQA condition name before using it as the QATrack+ `Test.name`. The slug SHALL continue to be derived from the raw (unstripped) condition name so that existing foreign-key references remain valid.

#### Scenario: Numbered name enriched
- **WHEN** myQA condition name is `"01. Vrt"`
- **THEN** `Test.name` is `"Vrt"` and `Test.slug` is `"01_vrt"` (derived from the raw name)

#### Scenario: Multi-digit number prefix
- **WHEN** myQA condition name is `"00. Chamber SN"`
- **THEN** `Test.name` is `"Chamber SN"` and `Test.slug` is `"00_chamber_sn"`

#### Scenario: Name without number prefix is unchanged by this rule
- **WHEN** myQA condition name is `"Flatness"`
- **THEN** `Test.name` is `"Flatness"` (no prefix to strip)

### Requirement: Expand common directional abbreviations
The setup command SHALL expand the following abbreviations when they appear as whole words (bounded by whitespace, punctuation, or end-of-string) in the enriched condition name: `Vrt` → `Vertical`, `Lng` → `Longitudinal`, `Lat` → `Lateral`, `SN` → `Serial Number`. Standard physics terms (`MU`, `FFF`, `NDwQ`, `TPR`, `RAKR`, `Dmax`, `kQQ`) SHALL NOT be expanded.

#### Scenario: Directional abbreviation expanded
- **WHEN** enriched name is `"Exactrac Absolute Difference Vrt (mm)"`
- **THEN** `Test.name` is `"Exactrac Absolute Difference Vertical (mm)"`

#### Scenario: Abbreviation as substring is NOT expanded
- **WHEN** enriched name is `"SNC Chamber Calibration"`
- **THEN** `Test.name` is `"SNC Chamber Calibration"` (the `SN` inside `SNC` is not a whole word)

#### Scenario: Physics term preserved
- **WHEN** enriched name is `"00. MV NDwQ [TPR = 0.630] Result"` (after number stripping: `"MV NDwQ [TPR = 0.630] Result"`)
- **THEN** `Test.name` is `"MV NDwQ [TPR = 0.630] Result"` (neither `NDwQ` nor `TPR` is expanded)

### Requirement: YAML override file for manual name control
The setup command SHALL load a YAML file at `qatrack/qa/management/commands/myqa_name_overrides.yaml` if it exists. The file maps `(TaskName, condition_name)` pairs to descriptive names. The wildcard key `"*"` applies an override to all TaskNames. Overrides SHALL be applied AFTER the strip-prefix and expand-abbreviation rules, so an override always wins.

#### Scenario: Specific override applied
- **WHEN** the YAML file contains `{"5.Tmt.Linac.Yearly - Relative Dosimetry": {"01. 6MV_Dose (cGy/MU) @Dmax": "6MV Output Dose at Dmax (cGy/MU)"}}`
- **AND** setup processes condition `"01. 6MV_Dose (cGy/MU) @Dmax"` under TaskName `"5.Tmt.Linac.Yearly - Relative Dosimetry"`
- **THEN** `Test.name` is `"6MV Output Dose at Dmax (cGy/MU)"` (the override; number-stripping rule is not applied because override wins)

#### Scenario: Wildcard override applied
- **WHEN** the YAML file contains `{"*": {"Acceptance Criteria": "Pass/Fail Acceptance Criteria"}}`
- **AND** setup processes condition `"Acceptance Criteria"` under any TaskName
- **THEN** `Test.name` is `"Pass/Fail Acceptance Criteria"`

#### Scenario: Override file absent
- **WHEN** the YAML file does not exist
- **THEN** setup proceeds using only the strip-prefix and expand-abbreviation rules (no error)

### Requirement: Mapping document generated on setup
The setup command SHALL generate two traceability artifacts at the end of every non-dry-run setup run: `docs/myqa_test_mapping.csv` and `docs/myqa_test_mapping.md`. Both files are overwritten from scratch on each run. The CSV SHALL contain one row per (TestList, Test) pair with columns: `testlist_name, testlist_slug, myqa_condition_name, qatrack_test_name, test_slug, execution_type, source_table`.

#### Scenario: CSV generated
- **WHEN** setup completes successfully
- **THEN** `docs/myqa_test_mapping.csv` exists and contains one row per TestListMembership, with the raw myQA condition name in `myqa_condition_name` and the enriched name in `qatrack_test_name`

#### Scenario: Markdown generated
- **WHEN** setup completes successfully
- **THEN** `docs/myqa_test_mapping.md` exists, grouped by TestList, with each TestList's tests listed in a table showing the myQA name → QATrack+ name mapping

#### Scenario: Dry-run does NOT generate mapping
- **WHEN** setup runs with `--dry-run`
- **THEN** no mapping files are written (the mapping documents are a record of what was actually created, not a preview)

### Requirement: Original myQA name stored in Test description
The setup command SHALL set `Test.description` to record the original myQA condition name and the TaskName(s) it was sourced from. For Tests shared across multiple TaskNames, the description SHALL list all contributing TaskNames.

#### Scenario: Single-source Test description
- **WHEN** a Test is created from condition `"Flatness"` under TaskName `"5.Tmt.Linac.D - myQA Daily Constancy Check"`
- **THEN** `Test.description` contains the string `"myQA condition: 'Flatness'"` and the TaskName

#### Scenario: Shared Test description accumulates TaskNames
- **WHEN** a Test with slug `"flatness"` already exists with description mentioning TaskName A
- **AND** setup encounters the same condition under TaskName B
- **THEN** `Test.description` is updated to list both TaskName A and TaskName B

### Requirement: Slug stability during enrichment
The setup command SHALL derive `Test.slug` from the raw myQA condition name via `slugify_name(raw_condition_name)`, NOT from the enriched name. This ensures that enrichment (which changes display names) does not invalidate existing `UnitTestInfo` or `TestInstance` foreign-key references.

#### Scenario: Slug derived from raw name
- **WHEN** myQA condition name is `"01. Flatness"` (enriched to `"Flatness"`)
- **THEN** `Test.slug` is `"01_flatness"` (from the raw name), NOT `"flatness"` (from the enriched name)

#### Scenario: Re-running setup preserves TestInstance references
- **WHEN** setup runs a second time after enrichment rules change
- **AND** a TestInstance references `UnitTestInfo` whose `test.slug` is `"01_flatness"`
- **THEN** the TestInstance remains valid because the slug is unchanged; only `Test.name` may have changed
