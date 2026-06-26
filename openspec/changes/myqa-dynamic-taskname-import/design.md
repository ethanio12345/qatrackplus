## Context

The current myQA import system (built across `fix-myqa-importers`, `myqa-complete-coverage`, and `full-myqa-sync` changes) uses 24+ hardcoded importer classes with broad pattern matchers like `"2.Phys.%"` and `"5.Tmt.Linac.D%"`. These lump many distinct myQA tasks into a few generic TestLists, producing names like "myQA Numeric Import" that users cannot distinguish.

The myQA database has 242 distinct TaskNames across 19 execution types, totaling 17,403 historical sessions. A single TaskName session can span multiple execution types (e.g., Monthly Dosimetry = Numeric + Profile + Wedge + Output + PassFail). Each execution type stores results in different table structures.

Additionally, an old QATrack+ backup from Oct 2022 has 120 TestLists and 3.3M TestInstances of manually-entered physics QA data (Solid Water, MPC, CatPhan) that was never in myQA.

**Current architecture:**
```
Pattern ("2.Phys.%") → ONE TestList ("myQA Physics Import")
  → Tests prefixed: myqa_physics_00_barometer_sn
  → No sharing across lists
```

**Target architecture:**
```
TaskName ("2.Phys.Chamber.Q - Quarterly")
  → TestList ("2.Phys.Chamber.Q - Quarterly")
    → Test "Sr-90 Constancy" (shared with other tasks)
    → Test "Pre-irradiation Leakage" (shared)
```

## Goals / Non-Goals

**Goals:**
- One TestList per myQA TaskName (242 lists), named verbatim from myQA
- Tests named by myQA condition name, shared/reused across TestLists
- Aggregate all execution types per session into one TestListInstance
- Import all 17,403 myQA sessions + 3.3M old QATrack+ TestInstances
- Every test and list interpretable by name alone

**Non-Goals:**
- Automatic tolerance assignment (shared tests have conflicting tolerances; users configure manually)
- Dynamic discovery for MatrixX Results tables (keep specialized extractors — Option B)
- Modifying myQA data (read-only SELECT queries)
- Backward compatibility with existing TestList/Test slugs (clean break)

## Decisions

### D1: TestList per TaskName, not per (TaskName, ExecType)

**Decision**: One TestList per TaskName. All execution types within that task contribute results to the same TestListInstance.

**Rationale**: Matches the myQA concept of a task. A "Monthly Dosimetry" session produces Numeric + Profile + Wedge + Output results together — they belong in one TestListInstance.

**Alternative considered**: One TestList per (TaskName, ExecType) pair. Rejected because it fragments a single clinical session across multiple lists.

### D2: Shared Tests by condition name (no list prefix)

**Decision**: Test slug = `slugify(condition_name)` without any list prefix. Same condition name → same Test object, reused via TestListMembership.

**Rationale**: User explicitly wants shared tests. "Center (crossline)" in Daily Constancy and Weekly QA is the same measurement. QATrack+ naturally supports this — Tests are shared across TestLists via Memberships.

**Consequence**: Duplicate condition names within a single task are disambiguated with `_2`, `_3` suffixes. These can be renamed later through admin.

**Example**:
```
Test: "Center (crossline)"  slug=center_crossline
  ├─ TestListMembership → "5.Tmt.Linac.D - myQA Daily Constancy Check"
  ├─ TestListMembership → "5.Tmt.Linac.W - Weekly QA"
  └─ TestListMembership → "5.Tmt.Linac.Y - Annual QA"
```

### D3: No tolerances during setup

**Decision**: Tolerances are NOT set during setup. UnitTestInfo.tolerance remains NULL.

**Rationale**: Shared tests can appear in multiple lists with different tolerances. Since tolerance is per (unit, test) via UnitTestInfo — not per (unit, test, list) — there's no way to have different tolerances for the same test in different lists. Setting no tolerance avoids picking the wrong one. Users configure tolerances manually after setup through QATrack+ admin.

**Alternative considered**: Pick the most common tolerance value. Rejected because the `Dimension` field doesn't disambiguate duplicates, and picking wrong tolerances would cause false pass/fail evaluations.

### D4: Aggregate extractors per session

**Decision**: For each session, detect which execution types are present and run the appropriate extractors. Merge all results into one dict before creating TestInstances.

```
For session S under TaskName T:
  results = {}
  if S has Numeric:  results.update(extract_numeric(S))
  if S has Profile:  results.update(extract_profile(S))
  if S has Output:   results.update(extract_output(S))
  if S has PassFail: results.update(extract_passfail(S))
  ... etc
  
  Create TestListInstance for TestList(slugify(T))
  Create TestInstance per (condition_name, value) in results
```

**Rationale**: A single myQA session can produce results from 5+ execution types. These must all land in the same TestListInstance.

### D5: Keep specialized MatrixX extractors (Option B)

**Decision**: Keep the existing specialized extraction code for Profile, Wedge, Energy, Output, MLC, CBCT, Planar, VMAT, Winston-Lutz. Adapt them to emit shared slugs (no list prefix) and target TaskName-based TestLists.

**Rationale**: Each MatrixX Results table has a different structure (Profile has DisplayName, MLC has column prefixes like `MaximumDeviation_`, Output has named columns). The specialized extractors already know how to read each table. A fully dynamic system would need per-table column mapping logic that essentially reimplements the same thing.

**Future**: Test dynamic discovery for MatrixX separately. If the condition names from each Results table are interpretable, switch to dynamic.

### D6: Frequency inference from TaskName

**Decision**: Infer frequency from TaskName patterns:
- Contains `.D` or `.D%` or "Daily" → `daily`
- Contains `.W` or "Weekly" → `weekly`
- Contains `.M` or "Monthly" → `monthly`
- Contains `.Q` or "Quarterly" → `quarterly`
- Contains `.6M` or "6 Monthly" → `monthly` (closest available)
- Contains `.Y` or "Annual" or "Yearly" → `annual`
- Contains `.C` or "Commissioning" → `monthly` (placeholder)
- Default → `daily`

**Rationale**: myQA doesn't expose a frequency field. The naming convention encodes it. Users can adjust through admin.

### D7: Old backup imported as-is

**Decision**: Restore old TestLists (Solid Water, MPC, CatPhan, etc.) from the Oct 2022 backup with their original names and tests. These coexist with the myQA-sourced TestLists.

**Rationale**: The old data uses different test structures (manually entered, not from myQA). Trying to map them to myQA TaskNames would lose data fidelity. Better to preserve them as-is.

**Implementation**: Use `pg_restore` to extract data, then bulk-insert into the current database with ID remapping to avoid conflicts.

### D8: Clear and rebuild (no migration)

**Decision**: Delete ALL existing myQA-sourced data (TestLists with `myqa_*` and `matrix-dosimetry-import` slugs) and rebuild from scratch.

**Rationale**: The old naming scheme (list-prefixed slugs, generic list names) is fundamentally incompatible with the new one (shared tests, TaskName-based lists). Migration would be more complex and error-prone than a clean rebuild. All source data exists in myQA and can be re-imported.

**Delete order** (FK constraints):
1. `UPDATE qa_unittestcollection SET last_instance_id = NULL` for affected lists
2. `DELETE FROM qa_testinstance` WHERE test_list_instance belongs to affected lists
3. `DELETE FROM qa_testlistinstance` WHERE test_list is affected
4. `DELETE FROM qa_unittestinfo` WHERE test belongs to affected tests
5. `DELETE FROM qa_unittestcollection` WHERE test_list is affected
6. `DELETE FROM qa_testlistmembership` WHERE test_list is affected
7. `DELETE FROM qa_test` WHERE slug starts with `myqa_` or `mtx_`
8. `DELETE FROM qa_testlist` WHERE slug starts with `myqa_` or equals `matrix-dosimetry-import`

## Risks / Trade-offs

- **[Risk: 242 TestLists is a lot to manage]** → Users deactivate lists they don't need through admin. QATrack+ supports unlimited lists.
- **[Risk: Shared tests with same name but different meaning across tasks]** → Acceptable per user direction. Names can be refined later.
- **[Risk: No tolerances means no pass/fail evaluation until manually configured]** → Users set tolerances per unit/test through admin after setup. This is a one-time configuration task.
- **[Risk: 3.3M old TestInstances could be slow to import]** → Use bulk_create with batch_size=5000. Estimated 5-10 minutes.
- **[Risk: Duplicate TaskNames with minor variations ("Daily Constancy Check" vs "[1]".."[4]")]** → Keep all as separate lists per user direction. These represent legitimate changes over time.
- **[Risk: MatrixX specialized extractors may not cover all TaskNames]** → Fall back gracefully — if no extractor matches an execution type, skip it and log a warning.
- **[Risk: Old backup has different schema version]** → Extract data via pg_restore to SQL text, parse and adapt column names to current schema.

## Migration Plan

1. **Backup current DB**: `pg_dump qatrackplus31 > backup_pre_redesign.sql`
2. **Clear myQA data**: Run cleanup SQL (D8 delete order)
3. **Setup new lists**: `python manage.py setup_myqa_tests` (dynamic discovery)
4. **Import myQA 90 days**: `python manage.py import_myqa --days 90`
5. **User review**: Check names, values, test matching in QATrack+ UI
6. **Import myQA full**: `python manage.py import_myqa --days 3650`
7. **Import old backup**: `python manage.py import_old_qatrack --file old_backup.custom`
8. **Rollback**: Restore from backup_pre_redesign.sql if needed

## Open Questions

- Profile/Wedge results have a `ProfileDirection` field (inline/crossline). Should this be part of the test name for disambiguation (e.g., "Center (inline)" vs "Center (crossline)")? Current specialized importers already handle this via DisplayName.
- Should the old backup TestLists be assigned to the same units as before, or re-mapped to current units?
- Energy execution type has only 16 sessions — is it worth building a specialized extractor, or can it be covered by the existing Wedge/Profile extractors?
