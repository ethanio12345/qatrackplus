# Proposal: Full myQA Sync

Import all treatment machine QA results from myQA SQL Server into QATrack+,
covering all linacs and the DXR unit across daily through annual frequencies.

## Why

Currently only monthly dosimetry (matrix) data is imported from myQA into
QATrack+. All other linac QA — daily constancy, monthly mechanical/safety,
beam/collimation, IGRT, quarterly CBCT, annual dosimetry, tank profiles,
and DXR checks — must be manually entered or viewed separately in the myQA
web interface. Automating the full sync eliminates duplicate data entry,
reduces transcription errors, and provides a single source of truth for all
linac QA results in QATrack+. The existing myQA monthly dosimetry import
provides the proven pattern (read-only myQA query, de-duplication via
mtx_taskid, ORM-based persistence) that this proposal extends to all QA
task types.

## Scope

- 19 new TestList objects (one per myQA task type × frequency)
- ~800 new Test objects with tolerances derived from myQA Warn/Fail values
- UnitTestCollections for 8 linac units + 1 DXR unit
- Import engine handling 11 execution types (Numeric, PassFail, Profile, Energy,
  Wedge, Output, MLC, CBCT, Planar, VMAT, WinstonLutz)
- Backfill historical data via `--days` flag
- Automated daily schedule via django-q
- Consolidate existing `Monthly Matrix Dosimetry Import` (#133) into new scheme

## Non-goals

- Commissioning tasks, CT QA, Strontium, Well Chamber
- Writing to myQA DB (read-only always)
- Removing existing manual test lists
- Real-time or sub-daily import

## Files

| File | Action |
|---|---|
| `qatrack/myqa_import.py` | Create — general import engine |
| `qatrack/qa/management/commands/setup_myqa_tests.py` | Create — one-time setup |
| `qatrack/qa/management/commands/import_myqa.py` | Create — management command |
| `qatrack/qa/tasks.py` | Modify — add `import_myqa_all()` |
| `qatrack/qa/apps.py` | Modify — register Schedule entries |
| `qatrack/matrix_import.py` | Modify — consolidate into new scheme |

## Risks

- High volume: ~438K TestInstances/year from Daily QA alone
- Complex MLC/CBCT sub-tables need careful mapping
- Task name variations require robust normalisation
