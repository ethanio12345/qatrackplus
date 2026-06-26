## 1. Enrichment function + abbreviation table

- [x] 1.1 Add `enrich_test_name(condition_name, taskname, overrides)` function to `qatrack/myqa_import.py` that applies: (a) strip `^\d+\.\s*` prefix, (b) expand word-boundary abbreviations (`Vrt`→`Vertical`, `Lng`→`Longitudinal`, `Lat`→`Lateral`, `SN`→`Serial Number`), (c) apply YAML override if one matches. Returns the enriched display name.
- [x] 1.2 Add the `_ABBREVIATIONS` constant dict (word → expansion) covering the 4 approved abbreviations. Ensure regex uses word boundaries so `SN` inside `SNC` is NOT expanded.
- [x] 1.3 Add `load_name_overrides()` function that reads `qatrack/qa/management/commands/myqa_name_overrides.yaml` if it exists and returns a `{(taskname, condition_name): descriptive_name}` dict (including `"*"` wildcard entries). Returns `{}` if the file is absent.

## 2. Integrate enrichment into setup_myqa_tests

- [x] 2.1 In `setup_myqa_tests._setup_one_taskname()`, call `enrich_test_name(condition_name, taskname, overrides)` to compute the display name for each Test. Use the enriched name as `Test.name`; keep `Test.slug = slugify_name(raw_condition_name)` (raw, not enriched).
- [x] 2.2 Update the `_disambiguate()` helper so the disambiguation suffix (`_2`, `_3`) is appended to the enriched display name when enriched names collide within a task. The slug disambiguation path is unchanged (operates on raw names).
- [x] 2.3 Set `Test.description` to `f"myQA condition: '{raw_condition_name}' (from TaskName '{taskname}')"` on Test creation. For shared Tests (already exist when a new TaskName contributes), append the new TaskName to the existing description.
- [x] 2.4 Create the default `qatrack/qa/management/commands/myqa_name_overrides.yaml` file with a header comment documenting the schema and one commented-out example entry. The file should be valid empty YAML (just the comment) so `load_name_overrides()` returns `{}` by default.

## 3. Mapping document generation

- [x] 3.1 Add `_generate_mapping_document(testlist_data)` helper to `setup_myqa_tests.py` that writes `docs/myqa_test_mapping.csv` with columns: `testlist_name, testlist_slug, myqa_condition_name, qatrack_test_name, test_slug, execution_type, source_table`. One row per TestListMembership.
- [x] 3.2 Add Markdown generation that writes `docs/myqa_test_mapping.md` grouped by TestList, each section containing a table of its Tests (myQA name → QATrack+ name → slug → type).
- [x] 3.3 Call the mapping-document generators at the end of `Command.handle()` after all TaskNames are processed (non-dry-run only). Collect the per-TaskName enrichment results during the loop so the generators have the data they need.

## 4. Rebuild with enriched names

- [x] 4.1 Run `clear_myqa_data --yes` to remove all existing myQA Tests/TestLists (the 90-day TestInstances are removed too because they reference the old Tests — this is expected per the "full clear + rebuild" decision).
- [x] 4.2 Run `setup_myqa_tests` to rebuild all 223 TestLists with enriched Test names.
- [x] 4.3 Run `import_myqa --days 90` to re-import the 90-day sessions against the rebuilt Tests.

## 5. Verify enrichment + mapping

- [x] 5.1 Verify sequence-number prefixes are stripped: query for Tests whose name starts with a digit+dot pattern (`^\d+\.`). Expected count: 0.
- [x] 5.2 Verify abbreviation expansion: query for Tests whose name contains `\b(Vrt|Lng|Lat)\b` as a whole word. Expected count: 0 (the abbreviations should all be expanded).
- [x] 5.3 Verify slug stability: spot-check that `Test.slug` still matches `slugify_name(raw_condition_name)` for a sample of Tests (slug is from the raw name, not the enriched name).
- [x] 5.4 Verify `docs/myqa_test_mapping.csv` exists, has the expected column headers, and row count matches `TestListMembership.objects.filter(test_list__slug__in <myQA slugs>).count()`.
- [x] 5.5 Verify `docs/myqa_test_mapping.md` is human-readable and grouped by TestList.
- [x] 5.6 Spot-check 5 enriched names against the original myQA names to confirm the enrichment is correct (e.g., `"01. Vrt"` → `"Vertical"`, `"00. Chamber SN"` → `"Chamber Serial Number"`, `"Flatness"` → `"Flatness"`).

## 6. Final checks + docs

- [x] 6.1 Run `uv run ruff check` and `uv run black --target-version py312` on all modified files (`myqa_import.py`, `setup_myqa_tests.py`, `myqa_name_overrides.yaml`).
- [x] 6.2 Run `uv run python manage.py check` (Django system check).
- [x] 6.3 Update `AGENTS.md` with a note about the enrichment layer, the override YAML, and the mapping document location.
