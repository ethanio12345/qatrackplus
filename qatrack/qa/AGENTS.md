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
| Design docs | `openspec/changes/myqa-dynamic-taskname-import/` |

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

## Gotchas

See the top-level `AGENTS.md` "Gotchas" section for the 5 known issues and their fixes.
