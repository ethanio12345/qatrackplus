# myqa-sync Specification

## Purpose

Describes the **current** behavior of myQA→QATrack+ integration as implemented
today. The full multi-task-type sync is a proposed change tracked under
`openspec/changes/full-myqa-sync/` and is NOT yet implemented.

## Current behavior: Monthly Matrix Dosimetry Import

Only monthly dosimetry (matrix) data is currently imported from myQA into
QATrack+, via `qatrack/matrix_import.py` (class `MatrixResultImporter`, entry
point `import_matrix_results`) and the `import_matrix_monthly` management command
/ django-q task.

### Requirement: Monthly matrix dosimetry import

The system SHALL import monthly dosimetry matrix results from the myQA SQL Server
database (read-only, via `pymssql`) into QATrack+ TestList #133 ("Monthly Matrix
Dosimetry Import").

#### Scenario: Monthly matrix session import

- GIVEN myQA has monthly dosimetry executions for a configured linac within the
  lookback window
- WHEN the `import_matrix_monthly` task runs
- THEN one `TestListInstance` SHALL be created per execution under TestList #133,
  with `TestInstance` rows for each matrix result, inside a per-session
  `transaction.atomic()` block

#### Scenario: De-duplication of monthly matrix sessions

- GIVEN a myQA matrix execution was already imported
- WHEN the import runs again over any window containing that execution
- THEN that execution SHALL be skipped, detected via a `TestInstance` whose
  `unit_test_info__test__slug == 'mtx_taskid'` and whose `string_value` equals
  the myQA execution id for that unit

#### Scenario: Scheduled daily run

- GIVEN the django-q `Schedule` named "Matrix Monthly Import" is registered (see
  `qatrack/qa/apps.py`)
- WHEN the scheduled time arrives
- THEN the `import_matrix_monthly` task SHALL run with its configured lookback

#### Scenario: Manual trigger

- GIVEN an operator at `/admin/django_q/schedule/`
- WHEN they click "Run" on the "Matrix Monthly Import" schedule
- THEN the import SHALL run on demand
