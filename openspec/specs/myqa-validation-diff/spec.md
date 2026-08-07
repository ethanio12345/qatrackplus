# myqa-validation-diff Specification

## Purpose
TBD - created by archiving change myqa-centre-trust-and-ops. Update Purpose after archive.
## Requirements
### Requirement: Read-only diff command against myQA
A management command `myqa_validate` SHALL compare QATrack+ state to the myQA source-of-truth for a given TaskName/window, reporting session-count mismatches, per-session condition-count mismatches, per-condition value mismatches, and per-condition tolerance mismatches. The command SHALL NOT modify any data — it is strictly read-only (SELECTs against myQA, ORM reads against QATrack+).

#### Scenario: All-match happy path
- **WHEN** `myqa_validate --days 30` is run against a centre where every myQA session in scope has a corresponding QATrack+ TLI
- **AND** every TLI has the expected condition count, values, and tolerances
- **THEN** the report status is `pass` for every TestList
- **AND** the summary reports `pass: N, needs_review: 0`

#### Scenario: Session-count mismatch detected
- **WHEN** myQA reports 14 sessions for a TaskName+unit in the window
- **AND** QATrack+ has only 10 TLIs for that combination
- **THEN** the report flags the TestList as `needs_review`
- **AND** lists the 4 missing sessions with their TaskExecutionIds

### Requirement: Valueless-skip distinguished from genuine-drop
For sessions myQA has but QATrack+ doesn't, `myqa_validate` SHALL categorise each missing session as either `valueless_skip` (myQA had no values for any condition — engine correctly skipped per the valueless-session guard) or `genuine_drop` (myQA had values but no TLI was created — indicates a bug or a slug collision).

#### Scenario: Valueless session correctly skipped
- **WHEN** a myQA session has rows for all conditions but every value is NULL
- **AND** the session has no corresponding QATrack+ TLI
- **THEN** the report categorises the session as `valueless_skip`
- **AND** the summary counts it under `valueless_skip` (not `genuine_drop`)
- **AND** the centre sees a clear "OK — engine correctly skipped" message

#### Scenario: Genuine drop surfaced for investigation
- **WHEN** a myQA session has at least one non-null value
- **AND** the session has no corresponding QATrack+ TLI
- **THEN** the report categorises the session as `genuine_drop`
- **AND** the summary counts it under `genuine_drop`
- **AND** the centre sees a "INVESTIGATE — engine bug or slug collision likely" message

### Requirement: Value-match tolerance
When comparing myQA `Actual` to QATrack+ `TI.value`, `myqa_validate` SHALL accept a match if the values are equal after rounding to 4 decimal places (matching the engine's `_result()` rounding precision in `qatrack/myqa_import.py`). Mismatches outside this threshold SHALL be reported with both values shown.

#### Scenario: Values match within rounding
- **WHEN** myQA `Actual` is 1.23450001
- **AND** QATrack+ `TI.value` is 1.2345
- **THEN** the report records a match (no mismatch reported)

#### Scenario: Values differ beyond rounding
- **WHEN** myQA `Actual` is 1.234
- **AND** QATrack+ `TI.value` is 1.235
- **THEN** the report records a mismatch with both values shown to 6 decimal places

### Requirement: Reuses engine SQL, doesn't reimplement
`myqa_validate` SHALL call back into `qatrack.myqa_import.query_sessions`, `extract_all_types`, and `duplicate_check` rather than reimplementing the queries. This keeps the validator in sync with the engine for free — if the engine's extractors are updated, validate automatically uses the new versions.

#### Scenario: Engine extractor update automatically picked up
- **WHEN** a new extractor is added to `qatrack.myqa_import._EXTRACTORS`
- **AND** `myqa_validate` is run
- **THEN** the new extractor's conditions are included in the per-session fidelity comparison without code changes to `myqa_validate`

### Requirement: Human and JSON output modes
`myqa_validate` SHALL support two output modes: human-readable (default, formatted with section dividers and ✓/⚠/✗ status indicators) and machine-readable (`--json` flag, single JSON object on stdout with stable schema).

#### Scenario: Human output format
- **WHEN** `myqa_validate --days 30` is run without `--json`
- **THEN** output uses section dividers (`─────`), per-TestList blocks with myQA↔QATrack+ paired counts, and a final summary line

#### Scenario: JSON output schema
- **WHEN** `myqa_validate --days 30 --json` is run
- **THEN** stdout is a single valid JSON object
- **AND** the object contains `window_days`, `summary`, and `testlists` keys
- **AND** each entry in `testlists` has a stable schema with `taskname`, `unit_number`, `unit_name`, `status`, and the relevant count/mismatch fields

### Requirement: Summary-only fast mode
A `--summary-only` flag SHALL skip the per-condition comparison (the slowest part — runs `extract_all_types` for every session) and report only session counts. Useful for frequent operational spot-checks where per-condition fidelity is not needed.

#### Scenario: Summary-only skips per-condition work
- **WHEN** `myqa_validate --summary-only --days 30` is run
- **THEN** the per-condition `extract_all_types` calls are not made
- **AND** the report shows session counts and valueless/genuine-drop categorisation only
- **AND** runtime is significantly lower than the full check

