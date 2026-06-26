## Context

The `myqa-dynamic-taskname-import` change created a dynamic discovery system that builds one TestList per myQA TaskName with shared Tests named by myQA condition name. The setup pipeline currently uses the raw myQA condition name verbatim as the QATrack+ `Test.name`:

```
myQA condition name "01. Vrt"  →  Test.name = "01. Vrt"
```

Analysis of the 2,504 unique condition names discovered from myQA:

| Category | Count | Example | Issue |
|----------|-------|---------|-------|
| Sequence-number prefix | 1,425 | `01. Vrt`, `00. Chamber SN` | Number prefix is a myQA UI ordering artifact, adds noise |
| Unexpanded abbreviations | 19 | `Exactrac ... Vrt (mm)` | `Vrt` not universally understood |
| Symbol/positional codes | 278 | `-45°`, `0.5 cm/s mean` | Meaningless without parent TaskName context |
| Already descriptive | 782 | `Flatness`, `Dose Output Constancy` | Fine as-is |

The enrichment must be **conservative** (per user decision) — only strip obvious noise and expand well-known abbreviations. Physics terminology must remain untouched because renaming `NDwQ` or `TPR` would be wrong and confusing to a medical physicist.

A separate concern is **traceability**. When a QATrack+ Test is later audited or reviewed, there must be a way to trace it back to the exact myQA condition that sourced it. Currently the only link is the slug, which is a lossy transformation of the name. A dedicated mapping document solves this.

## Goals / Non-Goals

**Goals:**
- Every QATrack+ Test name created from myQA is self-describing to a medical physicist without requiring cross-reference back to myQA
- Sequence-number prefixes (`01.`, `02.`, `00.`) are stripped from all names
- Common directional abbreviations are expanded (`Vrt` → `Vertical`, `Lng` → `Longitudinal`, `Lat` → `Lateral`)
- A version-controlled YAML file allows per-test manual overrides
- A mapping document (CSV + Markdown) is generated on every setup run, providing full myQA-condition → QATrack+ Test traceability
- The original myQA condition name is preserved in `Test.description` so it is visible inside the QATrack+ admin

**Non-Goals:**
- Aggressive renaming of physics terminology (`NDwQ`, `TPR`, `RAKR`, `MU`, `FFF`, `Dmax` stay as-is)
- Translation of measurement values or units (`cGy/MU`, `mGy/h` stay as-is)
- Adding TaskName context to ambiguous positional names (e.g., `0.5 cm/s mean` stays as-is — too risky to auto-prefix without knowing the myQA task semantics)
- Renaming existing pre-myQA Tests (Solid Water, MPC, CatPhan lists from the old backup)
- Changing slug generation. Slugs are stable identifiers; only `Test.name` changes.
- Modifying the import pipeline. Enrichment happens at setup time only; the extractor functions still emit raw myQA condition names so the mapping doc records provenance.

## Decisions

### D1: Enrichment applied at setup boundary, not in extractors

**Decision**: `discover_conditions()` continues to return raw myQA condition names. Enrichment is applied inside `setup_myqa_tests._setup_one_taskname()` immediately before creating each `Test`.

**Rationale**: The import path (`extract_*` → `import_session`) must still emit raw myQA names so they can be slugified and matched against the enriched Test slugs. Since the slug is derived from the raw name (via `slugify_name(condition_name)`), and enrichment does not change slugs, the import path works unchanged. Keeping enrichment at the setup boundary means the import path doesn't need to know about enrichment at all.

**Alternative considered**: Enrich inside `discover_conditions()` so both setup and import see enriched names. Rejected because (a) the mapping document needs the raw myQA name for provenance, and (b) the import path would need a parallel "enriched slug → Test" lookup table which is more fragile than the existing "raw slug → Test" lookup.

### D2: Conservative rule set (number stripping + abbreviation expansion)

**Decision**: Two enrichment rules only:

1. **Strip sequence-number prefix**: regex `^\d+\.\s*` removes leading `01.`, `00.`, `1.01 -` etc. Applied first.
2. **Expand abbreviation at word boundary**: a fixed lookup table:
   - `Vrt` → `Vertical`
   - `Lng` → `Longitudinal`
   - `Lat` → `Lateral`
   - `SN` → `Serial Number` (only when followed by whitespace or end-of-string, to avoid corrupting `SNC` or similar)
   
   Standard physics terms are explicitly NOT in the table: `MU`, `FFF`, `NDwQ`, `TPR`, `RAKR`, `Dmax`, `kQQ`, `kQ`, `kvol`.

**Rationale**: Per user decision (Conservative option). These two rules cover the highest-impact noise sources (1,425 numbered names + 19 abbreviations = ~58% of all names) with zero risk of producing wrong names. Aggressive renaming of the 278 symbol/positional names was explicitly rejected as too risky.

**Alternative considered**: Add TaskName-context prefixing for positional names (e.g., `0.5 cm/s mean` → `VMAT 0.5 cm/s mean` when the task is a VMAT task). Rejected because correctly inferring the right prefix requires per-task semantic knowledge that's fragile to encode as rules.

### D3: YAML override file, version-controlled

**Decision**: A YAML file at `qatrack/qa/management/commands/myqa_name_overrides.yaml` maps `(taskname, condition_name)` → `descriptive_name`. The file is checked into the repo so override decisions are code-reviewed and version-tracked.

**Schema**:
```yaml
# Map specific (TaskName, condition_name) pairs to a custom QATrack+ Test name.
# Keys are TaskNames; each maps condition_name -> descriptive_name.
# Enrichment rules (number stripping, abbreviation expansion) are applied FIRST,
# then the override is applied if it matches. To override for ALL TaskNames,
# use the special key "*".
"5.Tmt.Linac.Yearly - Relative Dosimetry":
  "01. 6MV_Dose (cGy/MU) @Dmax": "6MV Output Dose at Dmax (cGy/MU)"
"*":
  "Acceptance Criteria": "Pass/Fail Acceptance Criteria"
```

**Rationale**: Per user decision (YAML in repo). Version control gives review history for renaming decisions. YAML is human-friendly for manual editing. The `*` wildcard avoids duplication when the same override applies to every TaskName.

**Alternative considered**: Django model + admin. Rejected because (a) requires a migration, (b) renames are a deployment-time concern not a runtime concern, (c) admin edits bypass code review.

### D4: Mapping document format — CSV + Markdown

**Decision**: `setup_myqa_tests` writes two files at the end of a successful (non-dry-run) run:

- `docs/myqa_test_mapping.csv` — columns: `testlist_name, testlist_slug, myqa_condition_name, qatrack_test_name, test_slug, execution_type, source_table`
- `docs/myqa_test_mapping.md` — grouped by TestList, each section lists its Tests in a table

Both are regenerated from scratch on every setup run (overwriting the previous versions).

**Rationale**: Per user decision (CSV + Markdown). CSV is for Excel/audit workflows where filtering and sorting matter. Markdown is for human review in a code review or documentation context. Regeneration-on-each-run keeps the doc in sync with the DB.

### D5: Original myQA name stored in Test.description

**Decision**: When setup creates a Test, it sets:
```python
test.description = f"myQA condition: '{raw_condition_name}' (from TaskName '{taskname}')"
```

For Tests created from multiple TaskNames (shared Tests), the description is updated each time a new TaskName contributes to it, appending the new source:
```python
myQA condition: 'Flatness' (from TaskNames: '5.Tmt.Linac.D - myQA Daily Constancy Check', 'Daily Constancy Check[1]')
```

**Rationale**: Provides in-admin traceability without needing to open the mapping file. The description field is already displayed in the QATrack+ admin Test edit page and in the test-perform UI tooltip.

### D6: Slug unchanged (FK-safe rebuild)

**Decision**: Enrichment changes `Test.name` but NOT `Test.slug`. The slug continues to be `slugify_name(raw_condition_name)` (using the RAW name, not the enriched name).

**Rationale**: This is the critical safety property. Because slugs are stable:
- Existing `UnitTestInfo.test` FKs remain valid after rebuild
- Existing `TestInstance.unit_test_info` FKs remain valid
- The import path's slug-matching continues to work unchanged
- Re-running `clear_myqa_data` + `setup_myqa_tests` updates names without orphaning any TestInstance data

**Consequence**: The slug no longer "matches" the enriched name (e.g., slug `01_vrt` for name `Vertical`). This is acceptable — slugs are machine identifiers, names are human labels. The mapping document provides the authoritative name→slug correspondence.

## Risks / Trade-offs

- **[Risk: Enrichment produces a wrong name for an edge case]** → Mitigation: Conservative rules only (strip number, expand 4 abbreviations). YAML override file for any case the rules get wrong. Mapping document makes mistakes easy to spot during review.
- **[Risk: Slug / name mismatch is confusing in admin]** → Mitigation: `Test.description` records the original myQA name and the mapping doc records the slug↔name correspondence. Document this in AGENTS.md.
- **[Risk: Re-running setup overrides manual admin edits to Test.name]** → Mitigation: Setup uses `get_or_create` + `update_fields=["name"]` only when the name actually differs from the enriched name. If a user has manually renamed a Test in admin, the override YAML is the explicit signal — without an override, setup wins.
- **[Risk: Mapping document becomes stale if Tests are renamed manually]** → Mitigation: Document that the mapping file is a setup-time snapshot, not a live view. The `Test.description` field is the live source of truth for the original myQA name.
- **[Risk: 1,425 numbered names produce duplicate enriched names within a task]** → Mitigation: The existing `_disambiguate()` function in `setup_myqa_tests.py` already handles duplicate condition names within a task by appending `_2`, `_3` suffixes to slugs. Since slugs are unchanged, disambiguation works on the raw names — but the enriched display names may collide (e.g., `01. Vrt` and `02. Vrt` both enrich to `Vertical`). The disambiguation suffix is applied to the display name too, producing `Vertical` and `Vertical 2`.
