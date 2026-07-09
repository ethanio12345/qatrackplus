## 1. Clear existing myQA data

- [x] 1.1 Create `clear_myqa_data` management command that deletes all TestLists/Tests/TestInstances/UTCs/UTIs with `myqa_*` or `mtx_` slug prefixes or `matrix-dosimetry-import` slug, following the FK-safe delete order from design D8
- [x] 1.2 Run `clear_myqa_data` and verify all myQA-sourced data is removed
- [x] 1.3 Create a PostgreSQL backup before clearing: `pg_dump qatrackplus31 > backup_pre_redesign.sql`

## 2. Rewrite setup_myqa_tests — dynamic discovery

- [x] 2.1 Write `discover_tasknames()` function: query `SELECT DISTINCT TaskName FROM MQA_TestExecutions WHERE TaskName IS NOT NULL` and return the list
- [x] 2.2 Write `discover_conditions(taskname)` function: for a given TaskName, query conditions from ALL execution types present (Numeric from `MQA_Numeric_TestConditionExecutions`, PassFail from `MQA_PassFail_TestExecutions`, MatrixX from specialized Results tables) and return a list of {name, type} dicts
- [x] 2.3 Write `infer_frequency(taskname)` function: parse TaskName for frequency patterns (.D→daily, .M→monthly, .Y→annual, etc.) per design D6
- [x] 2.4 Rewrite `_setup_one_taskname()`: for each TaskName, create TestList (name=TaskName, slug=slugify(TaskName)), create/get shared Tests (slug=slugify(condition_name), disambiguate duplicates with _2/_3), create TestListMemberships
- [x] 2.5 Add UTC/UTI creation: query which units have data for each TaskName, create UnitTestCollections with inferred frequency, create UnitTestInfos for each test (no tolerances)
- [x] 2.6 Optimize UTI creation with bulk_create (batch_size=1000) to handle large task×unit combinations efficiently
- [x] 2.7 Remove all hardcoded importer class references, TASK_TYPE_REGISTRY, UNITS_PER_LIST from setup command
- [x] 2.8 Run `setup_myqa_tests --dry-run` and verify all 242 TaskNames are discovered with correct condition counts

## 3. Rewrite import_myqa — multi-type session aggregation

- [x] 3.1 Write `query_sessions(taskname, days)`: query sessions by exact TaskName match with date filter, resolve unit via LINAC_MAP
- [x] 3.2 Write `extract_all_types(session)`: detect execution types present in session, run appropriate extractors, merge results into one dict
- [x] 3.3 Adapt Numeric extractor: emit `slugify(condition_name)` slugs (no list prefix), return {condition_name: actual_value}
- [x] 3.4 Adapt PassFail extractor: read AcceptanceCriteria from `MQA_PassFail_TestExecutions`, return {"Acceptance Criteria": value}
- [x] 3.5 Adapt Profile extractor: read DisplayName + Actual from `MQA_Dosimetry_Profile_Results`, return {DisplayName: Actual}
- [x] 3.6 Adapt Wedge extractor: read from `MQA_Dosimetry_Wedge_TestExecutions` results, return {DisplayName: Actual}
- [x] 3.7 Adapt Output extractor: read from `MQA_Dosimetry_Output_TestExecutions`, map column names to human-readable condition names
- [x] 3.8 Adapt Energy extractor: read from `MQA_Dosimetry_Energy_TestExecutions` results
- [x] 3.9 Adapt MLC extractor: read from `MQA_MDL_MlcQA_Results`, parse column prefixes to condition names
- [x] 3.10 Adapt CBCT extractor: read from `MQA_MDL_Cbct_Results`, parse column prefixes
- [x] 3.11 Adapt Planar extractor: read from `MQA_MDL_Planar_Results`
- [x] 3.12 Adapt VMAT extractor: read from `MQA_MDL_VmatDmlc_Results`, parse ROI names
- [x] 3.13 Adapt Winston-Lutz extractor: read from `MQA_IsoCheck_WinstonLutz_TestExecutions`
- [x] 3.14 Write `import_session(taskname, session)`: create TestListInstance under slugify(TaskName) TestList, create TestInstances for each result, create taskid TestInstance for dedup
- [x] 3.15 Update `import_myqa_all()` in tasks.py to iterate over discovered TaskNames

## 4. Rewrite myqa_import.py — shared slug generation

- [x] 4.1 Change `slugify_name()` to NOT prepend list_slug — just `slugify(condition_name)` for all slugs
- [x] 4.2 Remove all hardcoded importer classes (MyqaNumericConstancyImport, MyqaCtDailyImport, etc.)
- [x] 4.3 Remove TASK_TYPE_REGISTRY, UNITS_PER_LIST, execution_type overrides
- [x] 4.4 Remove `get_importer()` function — replaced by dynamic TaskName-based dispatch
- [x] 4.5 Keep LINAC_MAP for unit resolution
- [x] 4.6 Keep specialized extraction functions as standalone methods callable by the multi-type aggregator

## 5. Test and verify — 90 day import

- [x] 5.1 Run `setup_myqa_tests` (all 242 TaskNames)
- [x] 5.2 Verify TestList count = 242, Test count is reasonable (~2000 shared tests)
- [x] 5.3 Run `import_myqa --days 90`
- [x] 5.4 Verify TestListInstance and TestInstance counts are reasonable
- [x] 5.5 User reviews: check names, values, test matching in QATrack+ UI
- [x] 5.6 Fix any naming or extraction issues found during review

## 6. Full import — all history

- [x] 6.1 Run `import_myqa --days 3650` (17,403 sessions)
- [x] 6.2 Verify no errors, check final TestInstance count
- [x] 6.3 Spot-check data integrity: compare a few sessions between myQA and QATrack+

## 7. Import old QATrack+ backup

- [x] 7.1 Create `import_old_qatrack` management command that reads a pg_restore custom-format file
- [x] 7.2 Extract TestLists, Tests, TestListInstances, TestInstances from the backup using pg_restore --data-only
- [x] 7.3 Implement ID remapping: map old PKs to new auto-generated PKs, preserve FK relationships
- [x] 7.4 Implement unit number mapping (verify old unit numbers match current)
- [x] 7.5 Bulk-insert TestLists and Tests first, then TestListInstances, then TestInstances (batch_size=5000)
- [x] 7.6 Run `import_old_qatrack --file "/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/2022-10-19-daily/qatrackplus.custom"`
- [x] 7.7 Verify 120 TestLists and ~3.3M TestInstances imported successfully
- [x] 7.8 Verify Solid Water, MPC, CatPhan data is accessible in QATrack+ UI

## 8. Final verification

- [x] 8.1 Verify total TestList count (242 myQA + 120 old = ~362)
- [x] 8.2 Verify all TestLists have interpretable names
- [x] 8.3 Verify shared Tests are reused across TestLists (check TestListMembership counts)
- [x] 8.4 Run `ruff check` and `black` on all modified files
- [x] 8.5 Run Django system check: `python manage.py check`
- [x] 8.6 Update AGENTS.md with new command documentation
