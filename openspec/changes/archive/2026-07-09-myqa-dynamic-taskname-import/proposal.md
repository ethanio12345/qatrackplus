## Why

The current myQA import system uses broad pattern matchers (e.g., `"2.Phys.%"`) that lump dozens of distinct myQA tasks into a handful of generic TestLists named "myQA Numeric Import". Users cannot tell which myQA task or condition any given test represents. The system needs a direct 1:1 mapping: one TestList per myQA TaskName, with tests named by their actual myQA condition names and shared across lists where reused.

Additionally, an old QATrack+ database backup (Oct 2022) contains 3.3M TestInstances from manually-entered physics QA (Solid Water, MPC, CatPhan) that was never in myQA. This data must be preserved and re-imported.

## What Changes

- **BREAKING**: Replace all existing myQA TestLists, Tests, TestInstances, UTCs, UTIs, and Tolerances. Clear everything and rebuild from scratch.
- **BREAKING**: Replace hardcoded importer classes (24+ classes with broad `task_name_patterns`) with a dynamic discovery system that queries myQA for all distinct TaskNames and creates one TestList per name.
- One TestList per myQA TaskName (242 tasks). Name = myQA TaskName verbatim; slug = `slugify(TaskName)`.
- Tests named by myQA condition name (e.g., "Center (crossline)"), shared/reused across TestLists via TestListMembership. No list-prefix slugs.
- Disambiguate duplicate condition names within a task by appending `_2`, `_3`, etc.
- Tolerances NOT set during setup (shared tests can have conflicting tolerances across tasks). Users configure per unit/test through admin.
- Aggregate multiple execution types per session: one TaskName can have Numeric + PassFail + Profile + Wedge + Output + MLC results, all writing to the same TestListInstance.
- Keep specialized MatrixX extractors (Profile, Wedge, Energy, Output, MLC, CBCT, Planar, VMAT, Winston-Lutz) for now (Option B). Adapt them to emit shared test slugs and target TaskName-based TestLists.
- Import 17,403 historical myQA sessions (all execution types, ~10 years).
- Import 93,902 TestListInstances / 3.3M TestInstances from the Oct 2022 QATrack+ backup (Solid Water, MPC, CatPhan, etc.) as additional TestLists not sourced from myQA.
- Frequency inferred from TaskName naming patterns (`.D`→daily, `.M`→monthly, `.Y`→annual, etc.).

## Capabilities

### New Capabilities
- `dynamic-taskname-discovery`: Query myQA for all distinct TaskNames and their conditions across all execution types. Create one TestList per TaskName with shared Tests named by condition name.
- `multi-type-session-import`: For each myQA session, aggregate results from all execution types present (Numeric, PassFail, Profile, Wedge, Output, MLC, CBCT, Planar, VMAT, Winston-Lutz) into a single TestListInstance.
- `old-db-restore`: Restore TestListInstances and TestInstances from the Oct 2022 QATrack+ backup database for data not in myQA (Solid Water, MPC, CatPhan, etc.).

### Modified Capabilities
- `myqa-dosimetry-tolerances`: Tolerances are no longer set during setup. Shared tests cannot have conflicting tolerances. Users configure per-unit tolerances through QATrack+ admin after setup.
- `myqa-device-expansion`: LINAC_MAP remains for unit resolution, but task_name_patterns and list_slug are replaced by dynamic TaskName discovery.

## Impact

- **qatrack/myqa_import.py**: Full rewrite. Remove 24+ hardcoded importer classes, TASK_TYPE_REGISTRY, UNITS_PER_LIST. Replace with dynamic TaskName discovery, shared test slug generation, and multi-type session aggregation.
- **qatrack/qa/management/commands/setup_myqa_tests.py**: Full rewrite. Dynamic discovery of all TaskNames, creation of shared Tests, TestLists per TaskName, bulk UTC/UTI creation.
- **qatrack/qa/management/commands/import_myqa.py**: Rewrite to import per-TaskName with multi-type extraction.
- **qatrack/qa/tasks.py**: Update `import_myqa_all` to iterate over discovered TaskNames.
- **Database**: Delete all existing myQA-sourced data (TestLists with `myqa_*` and `matrix-dosimetry-import` slugs, associated Tests/TestInstances/UTCs/UTIs). Rebuild from scratch.
- **Old backup**: `/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/2022-10-19-daily/qatrackplus.custom` (75MB, 120 TestLists, 3.3M TestInstances).
- **Test strategy**: Import 90 days of myQA data first, user reviews naming and values, then import full history. Old backup imported last.
