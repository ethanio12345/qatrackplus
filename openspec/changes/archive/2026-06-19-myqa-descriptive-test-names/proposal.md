## Why

The myQA dynamic TaskName import (`myqa-dynamic-taskname-import`) creates Tests using myQA condition names verbatim. Analysis of the ~2,500 discovered condition names shows that **1,425 (57%)** carry a sequence-number prefix from myQA (`01.`, `02.`, `00.`) that adds noise without meaning, **19** use unexpanded abbreviations (`Vrt`, `Lng`, `Lat`), and **278** are positional/ROI codes (`-45°`, `0.5 cm/s mean`) that are meaningless without the parent TaskName for context. Users viewing these test names in QATrack+ cannot tell what a test actually measures without cross-referencing back to myQA. There is also no traceability document mapping the QATrack+ Test back to its source myQA condition for audit/review purposes.

## What Changes

- Add a conservative name-enrichment layer to the setup pipeline that strips sequence-number prefixes and expands common abbreviations (`Vrt` → `Vertical`, `Lng` → `Longitudinal`, `Lat` → `Lateral`). Standard physics terms (`NDwQ`, `TPR`, `RAKR`, `MU`, `FFF`) are left untouched.
- Introduce a YAML override file (`myqa_name_overrides.yaml`) checked into the repo that maps `(TaskName, condition_name)` → descriptive name, giving full manual control for any individual test.
- Generate a traceability mapping document on every setup run — `docs/myqa_test_mapping.csv` (for Excel) and `docs/myqa_test_mapping.md` (human-readable) — recording: TestList name, myQA condition name, QATrack+ Test name, slug, execution type, source table.
- Store the original myQA condition name in `Test.description` so the provenance is visible inside the QATrack+ admin without needing to open the mapping file.
- **BREAKING (myQA data only)**: Clear and rebuild all myQA-sourced Tests to apply the enriched names. Test **slugs are unchanged**, so existing `TestInstance` / `UnitTestInfo` foreign-key references remain valid; only the human-readable `Test.name` field changes. Existing 90-day `TestInstance` data remains intact because it references Tests by slug.

## Capabilities

### New Capabilities
- `descriptive-test-names`: Transform raw myQA condition names into self-describing QATrack+ Test names via enrichment rules + YAML overrides, and emit a mapping document for traceability.

### Modified Capabilities
- `dynamic-taskname-discovery`: Setup no longer uses myQA condition names verbatim as Test names. The `discover_conditions` → `Test.name` pipeline now passes through `enrich_test_name()`. The slug generation path is unchanged.

## Impact

- **qatrack/myqa_import.py**: Add `enrich_test_name(condition_name, taskname)` function + abbreviation/override loading helpers. `discover_conditions` output unchanged (still returns raw myQA names so the mapping doc records provenance); enrichment is applied at the setup boundary only.
- **qatrack/qa/management/commands/setup_myqa_tests.py**: Apply `enrich_test_name()` when creating Tests. Write `Test.description` with original myQA name. Generate `docs/myqa_test_mapping.{csv,md}` after setup completes. Load `myqa_name_overrides.yaml` if present.
- **qatrack/qa/management/commands/myqa_name_overrides.yaml** (new): Default-empty YAML file documenting the override schema. Users add per-test overrides here.
- **docs/myqa_test_mapping.csv** + **docs/myqa_test_mapping.md** (new, generated): Traceability artifacts, regenerated on each setup run.
- **Operational**: Requires re-running `clear_myqa_data --yes` then `setup_myqa_tests` to rebuild Tests with enriched names. Existing 90-day `TestListInstance`/`TestInstance` data survives because slugs are stable, but the user will need to re-import to refresh any cached display names.
