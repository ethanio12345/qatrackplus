# Proposal: Fix myQA Importers

Correct SQL queries and column mappings in `myqa_import.py` based on the
actual myQA database schema, then extend `setup_myqa_tests.py` and backfill.

## Background

The `full-myqa-sync` change implemented a generic import engine but assumed
table/column names that differ from the actual myQA database. The profile
(matrix dosimetry) importer works correctly. All other importers have broken
queries due to missing tables, wrong column names, or incorrect JOIN paths.

## Data Volumes

| Type | Sessions | Priority |
|---|---|---|
| Numeric (daily QA) | 3,670 | High |
| Profile (matrix) | 534 | Working |
| Winston Lutz | 400 | Medium |
| MLC | 252 | Medium |
| VMAT | 247 | Medium |
| CBCT | 46 | Low |
| Planar | 4 | Low |

## Files Affected

| File | Action |
|---|---|
| `qatrack/myqa_import.py` | Fix queries in 7 importers |
| `qatrack/qa/management/commands/setup_myqa_tests.py` | Extend for all execution types |
