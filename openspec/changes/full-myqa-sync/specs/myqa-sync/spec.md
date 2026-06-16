## ADDED Requirements

### Requirement: Test and TestList creation

The system SHALL create QATrack+ Test objects and TestList objects for each myQA task type, using `myqa_` prefixed slugs.

#### Scenario: Test slugs created from myQA test names

- GIVEN a myQA Numeric test condition with Name `1.01 6MV Output`
- WHEN the setup script creates the Test object
- THEN the slug SHALL be `myqa_daily_physics_1_01_6mv_output`

### Requirement: Tolerance mapping

The system SHALL create QATrack+ Tolerance objects from myQA WarnOn/FailOn values.

#### Scenario: Absolute symmetric tolerance

- GIVEN a Numeric test with WarnOn=2.0, FailOn=3.0, IsRelative=0, LimitTendency=0
- WHEN the Tolerance is created
- THEN type SHALL be `absolute` with tol_lower=-2.0 and tol_upper=+2.0

### Requirement: UnitTestCollection creation

The system SHALL create UnitTestCollection objects for each unit and frequency.

#### Scenario: Daily UTC for LA317

- GIVEN Unit LA317 (#3) and myqa_daily_physics test list
- WHEN the setup script runs
- THEN a UnitTestCollection SHALL exist with unit=3, frequency=Daily, active=True

### Requirement: Historical data import

The system SHALL import existing historical data from myQA.

#### Scenario: Backfill Daily QA for LA317

- GIVEN myQA has Daily QA executions for LA317
- WHEN the import runs with `--days 365`
- THEN TestListInstances SHALL be created for each execution in the window

### Requirement: Incremental daily import

The system SHALL run automatically via django-q on a daily schedule.

#### Scenario: Daily import schedule

- GIVEN the django-q Schedule for `myqa_all` is configured
- WHEN 6pm AEST arrives
- THEN the import SHALL query myQA for new executions since last run

### Requirement: De-duplication

The system SHALL skip previously imported sessions.

#### Scenario: Duplicate detection

- GIVEN a myQA execution with UUID X was already imported
- WHEN the import runs again
- THEN that execution SHALL be skipped

### Requirement: Execution type support

The import engine SHALL handle Numeric, PassFail, Profile, Energy, Wedge, Output, MLC, CBCT, Planar, VMAT, and WinstonLutz execution types.

#### Scenario: Numeric type import

- GIVEN a Numeric execution with test conditions
- WHEN imported
- THEN each condition becomes a simple TestInstance with the Actual value

### Requirement: Task name normalisation

The system SHALL map myQA task name variants to canonical handlers.

#### Scenario: Legacy naming

- GIVEN myQA task name `Daily Constancy Check`
- WHEN the import resolves the handler
- THEN it SHALL use the myqa_daily_constancy handler

### Requirement: Manual trigger from UI

Users SHALL be able to trigger the import from QATrack+ admin.

#### Scenario: Run from django-q admin

- GIVEN a user at `/admin/django_q/schedule/`
- WHEN they click "Run" on the myqa_all schedule
- THEN the full import SHALL execute on demand

## MODIFIED Requirements

### Requirement: Monthly matrix dosimetry consolidation

The existing `Monthly Matrix Dosimetry Import` (test list #133) SHALL be consolidated into the new `myqa_monthly_dosimetry` scheme.

#### Scenario: Existing data remains accessible

- GIVEN existing TestListInstances under test list #133
- WHEN the consolidation runs
- THEN existing data SHALL remain visible
- AND new imports SHALL use the `myqa_monthly_dosimetry` test list

## REMOVED Requirements

None.

## RENAMED Requirements

None.
