## Why

The current myQA import pipeline ignores test execution states and collapses
all PassFail tests in a session into a single "Acceptance Criteria" result.
Analysis of the myQA database reveals **5 distinct execution states** (10, 30,
40, 50, 60) with different semantics:

| State | Count | Values? | Meaning |
|-------|-------|---------|---------|
| 10 | 90K conditions | 0% | Not started — empty draft, nothing to import |
| 30 | 52K conditions | 22% | In progress — partial data |
| 40 | 355K conditions | 93% | Completed — full results |
| 50 | 10K conditions | 100% | Failed — out-of-tolerance results |
| 60 | 14K conditions | 100% | Skipped / N/A — intentionally not measured |

Currently, State=10 tests with NULL `Actual` values are imported as `None`
TestInstances, cluttering the review queue with empty results that were never
performed. State=60 (skipped) tests are indistinguishable from State=40
(completed) tests. And sessions with multiple PassFail tests (e.g., 10 safety
checks in one annual QA session) lose 9 of 10 results because
`extract_passfail` only reads the first row.

## What Changes

- Add a `Skipped` TestInstanceStatus to QATrack+ so users can distinguish
  intentionally-skipped tests from completed tests.
- Map myQA execution states to QATrack+ statuses during import:
  - State 10 (not started): **skip import entirely** — no TestInstance created
  - State 30/40/50 (in progress / completed / failed): import normally with
    `Unreviewed` status (let QATrack+ tolerances flag failures)
  - State 60 (skipped): import with value if present, set `Skipped` status
- Rewrite `extract_passfail` to return **all** PassFail tests in a session,
  keyed by test execution name (e.g., `"Door closing safety"` → criteria),
  instead of collapsing to a single `"Acceptance Criteria"` row.
- Update `extract_numeric` to include per-condition state so the import can
  filter by state.
- Update `discover_conditions` and `discover_has_passfail_data` to account
  for the new per-test PassFail conditions.

## Capabilities

### New Capabilities
- `myqa-state-aware-import`: State-aware extraction and import that respects
  myQA test execution states and imports all PassFail tests per session.

### Modified Capabilities
- `dynamic-taskname-discovery`: PassFail discovery now returns per-test
  conditions (one per PassFail test execution), not a single synthetic
  "Acceptance Criteria" condition.

## Impact

- **qatrack/myqa_import.py**: Rewrite `extract_passfail` to return all tests.
  Add state-aware filtering to `extract_numeric`. Pass state metadata through
  `extract_all_types` → `import_session`. Map states to QATrack+ statuses.
- **qatrack/qa/management/commands/setup_myqa_tests.py**: Update PassFail
  discovery to enumerate per-test PassFail conditions instead of a single
  synthetic condition.
- **Data model**: Create `Skipped` TestInstanceStatus via setup or migration.
- **Operational**: Requires re-running `clear_myqa_data` + `setup_myqa_tests`
  + `import_myqa` to rebuild with the new PassFail conditions and state mapping.
