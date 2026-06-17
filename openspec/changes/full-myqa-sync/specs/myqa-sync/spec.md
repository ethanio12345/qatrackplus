## ADDED Requirements

### Requirement: Test and TestList creation

The system SHALL create one QATrack+ `TestList` per myQA task type × frequency
combination (19 lists total), plus `Test` objects for every distinct myQA test
name. Each `Test` and `TestList` SHALL use a `myqa_`-prefixed slug derived from
its myQA name.

#### Scenario: Test slugs created from myQA test names

- GIVEN a myQA Numeric test condition with Name `1.01 6MV Output` belonging to
  the `myqa_daily_physics` list
- WHEN the setup script creates the Test object
- THEN the slug SHALL be `myqa_daily_physics_1_01_6mv_output` (dots collapsed to
  underscores, lowercased)

#### Scenario: Exactly 19 TestLists created

- GIVEN the setup script runs against the production myQA task-type catalogue
- WHEN it completes (non-dry-run)
- THEN exactly 19 `TestList` objects SHALL exist with `myqa_`-prefixed slugs, one
  per task type × frequency combination

#### Scenario: Slug collision detection

- GIVEN two distinct myQA test names that slugify identically
- WHEN the setup script creates Test objects
- THEN it SHALL log a warning and disambiguate by appending a numeric suffix
  (e.g. `_2`), so no two Tests share a slug

### Requirement: Tolerance mapping (two-band offsets)

The system SHALL create QATrack+ `Tolerance` objects from myQA `WarnOn`/`FailOn`
values, mapping `WarnOn → tol_*` and `FailOn → act_*` as offsets from the
reference value (not absolute thresholds).

#### Scenario: Absolute symmetric (two-sided)

- GIVEN a Numeric test with `WarnOn=2.0`, `FailOn=3.0`, `IsRelative=0`,
  `LimitTendency=0`
- WHEN the Tolerance is created
- THEN `type` SHALL be `absolute`, `tol_low=-2.0`, `tol_high=+2.0`,
  `act_low=-3.0`, `act_high=+3.0`

#### Scenario: Absolute lower-only

- GIVEN a Numeric test with `WarnOn=2.0`, `FailOn=3.0`, `IsRelative=0`,
  `LimitTendency=1`
- WHEN the Tolerance is created
- THEN `type` SHALL be `absolute`, `tol_low=-2.0`, `act_low=-3.0`,
  `tol_high=None`, `act_high=None` (no upper bound)

#### Scenario: Absolute upper-only

- GIVEN a Numeric test with `WarnOn=2.0`, `FailOn=3.0`, `IsRelative=0`,
  `LimitTendency=2`
- WHEN the Tolerance is created
- THEN `type` SHALL be `absolute`, `tol_high=+2.0`, `act_high=+3.0`,
  `tol_low=None`, `act_low=None` (no lower bound)

#### Scenario: Percent tolerance

- GIVEN a Numeric test with `WarnOn=2.0`, `FailOn=3.0`, `IsRelative=1`,
  `LimitTendency=0`
- WHEN the Tolerance is created
- THEN `type` SHALL be `percent` (the QATrack+ engine computes
  `diff = 100*(value-ref)/ref` against the attached `Reference.value`)

### Requirement: UnitTestCollection creation

The system SHALL create `UnitTestCollection` objects for each unit and frequency,
with `active=True`.

#### Scenario: Daily UTC for LA317

- GIVEN Unit LA317 (number 3) and the `myqa_daily_physics` test list
- WHEN the setup script runs
- THEN a `UnitTestCollection` SHALL exist with `unit=3`, `frequency=Daily`
  (slug `daily`), `active=True`

### Requirement: Historical data import

The system SHALL import existing historical data from myQA via the `--days`
lookback flag.

#### Scenario: Backfill Daily QA for LA317

- GIVEN myQA has Daily QA executions for LA317 within the last 365 days
- WHEN the import runs with `--days 365 --unit 3`
- THEN one `TestListInstance` SHALL be created per execution in the window,
  each inside its own `transaction.atomic()` block

### Requirement: Incremental daily import (stateless)

The system SHALL run automatically via django-q on a daily schedule, using a
fixed lookback window (no persisted "last run" state).

#### Scenario: Daily import schedule fires

- GIVEN the django-q `Schedule` for `import_myqa_all` is configured as DAILY at
  18:00 `Australia/Sydney`
- WHEN 18:00 Sydney local time arrives (AEST or AEDT, as django-q resolves DST)
- THEN the import SHALL query myQA with the default `--days 2` window

#### Scenario: Missed day recovery

- GIVEN the daily run failed yesterday
- WHEN today's run executes with `--days 2`
- THEN yesterday's sessions SHALL still be picked up (lookback overlaps)

### Requirement: De-duplication via single shared slug

The system SHALL skip previously imported sessions using one shared de-dup
`Test` slug per import family, whose `TestInstance.string_value` stores the myQA
`TaskExecutionId` (an integer, cast to `str`).

#### Scenario: Duplicate detection

- GIVEN a myQA execution with `TaskExecutionId` 12345 was already imported
- WHEN the import runs again over any window containing that execution
- THEN that execution SHALL be skipped (a `TestInstance` with
  `string_value='12345'` against the de-dup slug already exists for that unit)

#### Scenario: Matrix consolidation reuses existing slug

- GIVEN the monthly matrix task type is consolidated into the new engine
- WHEN new monthly matrix sessions are imported
- THEN de-duplication SHALL reuse the existing `mtx_taskid` slug (not a new
  per-list slug), preserving continuity with historical imports

### Requirement: Execution type support

The import engine SHALL handle 11 execution types (Numeric, PassFail, Profile,
Energy, Wedge, Output, MLC, CBCT, Planar, VMAT, WinstonLutz), each reading its
own myQA detail table. Fan-out rows SHALL be distinguished into deterministic,
stable slugs by their natural key columns.

#### Scenario: Numeric type import (simple value)

- GIVEN a Numeric execution with several test conditions (or an Output execution
  with simple values)
- WHEN imported
- THEN each condition SHALL become one `TestInstance` carrying the `Actual`
  value, with a slug derived from the condition's name

#### Scenario: PassFail type import

- GIVEN a PassFail execution
- WHEN imported
- THEN each result SHALL become a `TestInstance` storing the myQA outcome text
  verbatim in `string_value` (e.g. `Pass` / `Fail`)

#### Scenario: Multi-key composite import (Energy/Wedge/Profile family)

- GIVEN an Energy execution fanning out across chamber numbers (or a Wedge
  execution across wedge type/angle, or a Profile across display name/direction)
- WHEN imported
- THEN each natural-key combination SHALL produce a distinct, stable slug
  incorporating those key columns (e.g. chamber number), so two chambers never
  collide

#### Scenario: Sub-table aggregate import (MLC/CBCT/Planar/VMAT family)

- GIVEN an MLC execution whose detail table contains one row per leaf pair
  (or a CBCT execution per slice, etc.)
- WHEN imported
- THEN each sub-table row SHALL become its own `TestInstance` with a slug that
  encodes the row's index/key

#### Scenario: WinstonLutz import

- GIVEN an IsoCheck WinstonLutz execution
- WHEN imported
- THEN each result field SHALL become a `TestInstance` per its name

### Requirement: Task name normalisation

The system SHALL map myQA `TaskName` variants (legacy casing, parenthetical
suffixes, free-text notes) to canonical handler classes via a registry of
compiled-regex patterns, covered by unit tests.

#### Scenario: Legacy naming

- GIVEN a myQA task name `Daily Constancy Check`
- WHEN the import resolves the handler
- THEN it SHALL route to the `myqa_daily_constancy` handler regardless of casing
  or trailing parenthetical notes

### Requirement: Manual trigger from admin

Users SHALL be able to trigger the full import on demand from the django-q admin.

#### Scenario: Run from django-q admin

- GIVEN a user at `/admin/django_q/schedule/`
- WHEN they click "Run" on the `import_myqa_all` schedule
- THEN the full import SHALL execute on demand and the summary SHALL be visible
  in the task result

## MODIFIED Requirements

### Requirement: Monthly matrix dosimetry consolidation

The existing `Monthly Matrix Dosimetry Import` (TestList #133) SHALL be
consolidated into the new scheme: its task type routes through the new engine,
its standalone management command becomes a deprecation shim, and its
django-q schedule merges into the daily import.

#### Scenario: Existing data remains accessible

- GIVEN existing `TestListInstance` rows under TestList #133
- WHEN the consolidation runs
- THEN those rows SHALL remain visible unchanged
- AND new monthly matrix imports SHALL re-use the `mtx_taskid` de-dup slug so
  historical rows are never re-imported

## REMOVED Requirements

None.
