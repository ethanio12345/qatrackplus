## ADDED Requirements

### Requirement: Skip import for not-started tests
The import SHALL NOT create a TestInstance for any myQA test execution with State=10 (not started). These tests have no measured values and importing them would clutter the review queue with empty results.

#### Scenario: State=10 condition skipped
- **WHEN** a Numeric condition has State=10 and Actual=NULL
- **THEN** no TestInstance is created for that condition

#### Scenario: State=10 condition with unexpected value
- **WHEN** a Numeric condition has State=10 but Actual is not NULL
- **THEN** no TestInstance is created (State=10 means not started regardless of value)

### Requirement: Skipped status for intentionally skipped tests
The import SHALL create a `Skipped` TestInstanceStatus (slug=`skipped`, valid=False, requires_review=False) and assign it to TestInstances sourced from myQA test executions with State=60 (skipped / N/A).

#### Scenario: State=60 test imported as Skipped
- **WHEN** a test execution has State=60
- **THEN** a TestInstance is created with the measured value (if any) and status=`Skipped`

#### Scenario: Skipped status excluded from review queue
- **WHEN** a TestInstance has status=`Skipped`
- **THEN** it does not appear in the unreviewed queue (requires_review=False)

### Requirement: Import all PassFail tests per session
The extractor SHALL return all PassFail test executions in a session, each keyed by its myQA TestExecution Name (e.g., `"Door closing safety - Light Curtain"`). The single synthetic "Acceptance Criteria" condition is replaced by N per-test conditions.

#### Scenario: Multiple PassFail tests in session
- **WHEN** a session has 10 PassFail test executions (Jaw Position, Jaw Sag, Door Safety, etc.)
- **THEN** 10 separate results are returned, each keyed by the test execution Name

#### Scenario: PassFail test with state
- **WHEN** a PassFail test execution has State=40
- **THEN** the result includes the AcceptanceCriteria value and the state

### Requirement: State-aware extraction
The extractors SHALL include the myQA execution State alongside each extracted value, so the import can apply the correct QATrack+ status. Results are returned as `{condition_name: {"value": ..., "state": int}}` instead of `{condition_name: value}`.

#### Scenario: Completed test with value
- **WHEN** a Numeric condition has State=40 and Actual=1.002
- **THEN** the extraction returns `{"Dose Output": {"value": 1.002, "state": 40}}`

#### Scenario: Skipped test with value
- **WHEN** a Numeric condition has State=60 and Actual=0.5
- **THEN** the extraction returns `{"Dose Output": {"value": 0.5, "state": 60}}`

#### Scenario: Not-started test excluded
- **WHEN** a Numeric condition has State=10
- **THEN** the extraction does not include it in the results
