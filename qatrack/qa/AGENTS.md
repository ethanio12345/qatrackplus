# AGENTS.md — myQA Import Engine

This directory contains the myQA import system. The main engine is a single
file: `myqa_import.py` (~1960 lines).

## Quick reference

| What | Where |
|------|-------|
| Import engine | `qatrack/myqa_import.py` |
| Management commands | `qatrack/qa/management/commands/` |
| Scheduled tasks | `qatrack/qa/tasks.py` |
| Device map | `qatrack/qa/management/commands/myqa_device_map.yaml` |
| Name overrides | `qatrack/qa/management/commands/myqa_name_overrides.yaml` |
| Test mapping (generated) | `docs/myqa_test_mapping.{csv,md}` |
| SQL schema reference | `docs/sql/myqa_schema.md` |
| Query patterns | `docs/sql/queries.md` |
| Data mapping | `docs/sql/mapping.md` |
| Design docs | `openspec/changes/archive/2026-07-09-myqa-dynamic-taskname-import/` |

## Architecture

Two-phase system:
1. **Setup** (`setup_myqa_tests`): discovers TaskNames/conditions from myQA → creates TestLists/Tests/UTCs/UTIs
2. **Import** (`import_myqa`): extracts session data → creates TestListInstances/TestInstances

One TestList per TaskName. Tests shared by condition name. One TestListInstance per session aggregating all execution types.

## Key patterns

- **Shared FROM/JOIN constants** (`_*_FROM`): SQL JOIN blocks defined once, used by both discover and extract
- **`_DISCOVERERS` / `_EXTRACTORS` lists**: parallel lists driving the type pipeline
- **`compute_multi_flags`**: determines test-step prefixing at TaskName level (not session level)
- **`_fetchall` / `_result` helpers**: reduce cursor boilerplate and standardize result dicts
- **Valueless sessions are skipped.** `import_session` early-returns `skipped_empty` when a session has rows but no non-null values (don't reintroduce importing empty TLIs).
- **`*_taskid` TestInstances are created Approved** (`requires_review=False`) — dedup metadata, not clinical data.
- **Each imported TLI is auto-approved if all its tests pass** via `TestListInstance.auto_approve()` (Default AutoReviewRuleSet); failing/commented tests leave it unreviewed.
- **`MYQA_DB_SETTINGS` is lazy** (`_myqa_db_settings()` inside `get_connection`) so this module imports without `MYQA_*` configured (the test suite mocks the connection).

## Gotchas

See the top-level `AGENTS.md` "Gotchas" section for the known issues and their
fixes. Engine-specific: the valueless-session guard must check for any non-null
value across **all** extractors (not just non-zero rows), and `multi` flags must
stay TaskName-level (recompute per batch, pass via `multi_override`).
