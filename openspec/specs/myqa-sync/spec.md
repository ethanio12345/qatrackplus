# myqa-sync Specification

## Purpose

Import all treatment machine QA results from the myQA SQL Server database into QATrack+, covering all linacs (LA317, LA414, LA512, LA524, LA224, CST15, OBK15) and the DXR orthovoltage unit. Each myQA task type becomes a QATrack+ test list with tolerances derived from myQA's Warn/Fail values. Daily, weekly, monthly, quarterly, 6-monthly, and annual frequencies are supported.

## Requirements

### Requirement: Test and TestList creation

The system SHALL create QATrack+ Test objects and TestList objects for each myQA task type listed below, using `myqa_` prefixed slugs to avoid collisions with existing manual tests.

| Test List Slug | myQA Task Pattern | Frequency | Units |
|---|---|---|---|
| `myqa_daily_physics` | `5.Tmt.Linac.D2 - Daily QA (Physics)` | Daily | 1,2,3,4,5,7,8 |
| `myqa_daily_constancy` | `5.Tmt.Linac.D - myQA Daily Constancy Check` | Daily | 1,2,3,4,5,7,8 |
| `myqa_monthly_safety_mech` | `5.Tmt.Linac.M.Safety/Mechanical - Monthly QA` | Monthly | 1,2,3,4,5,7,8 |
| `myqa_monthly_beam_coll` | `5.Tmt.Linac.M.Beam/Collimation - Monthly QA` | Monthly | 1,2,3,4,5,7,8 |
| `myqa_monthly_igrt` | `5.Tmt.Linac.M.IGRT - Monthly QA` | Monthly | 1,2,3,4,5,7,8 |
| `myqa_monthly_ancillary` | `5.Tmt.Linac.M.AncillaryDevices - Monthly QA` | Monthly | 1,2,3,4,5,7,8 |
| `myqa_quarterly` | `5.Tmt.Linac.Q - Quarterly` | Quarterly | 1,2,3,4,5,7,8 |
| `myqa_6monthly` | `5.Tmt.Linac.6M - 6 Monthly` | 6Monthly | 1,2,3,4,5,7,8 |
| `myqa_annual_dosimetry` | `5.Tmt.Linac.Y.Dosimetry - Annual QA` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_tank` | `5.Tmt.Linac.Y.Tank - Annual QA` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_mech` | `5.Tmt.Linac.Y.Mech - Annual QA` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_abs_dos` | `5.Tmt.Linac.Yearly - Absolute Dosimetry` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_rel_dos` | `5.Tmt.Linac.Yearly - Relative Dosimetry` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_mech_safety` | `5.Tmt.Linac.Yearly - Mechanical/Safety` | Annual | 1,2,3,4,5,7,8 |
| `myqa_annual_igrt` | `5.Tmt.Linac.Yearly - IGRT` | Annual | 1,2,3,4,5,7,8 |
| `myqa_dxr_daily` | `5.Tmt.DXR.D - myQA Daily Constancy Check` | Daily | 50 |
| `myqa_dxr_weekly` | `5.Tmt.DXR.W - Weekly QA` | Weekly | 50 |
| `myqa_dxr_monthly` | `5.Tmt.DXR.M - Monthly QA` | Monthly | 50 |
| `myqa_dxr_annual` | `5.Tmt.DXR.Y - Annual QA` | Annual | 50 |
| `myqa_monthly_dosimetry` | `5.Tmt.Linac.M.Dosimetry - Monthly QA` | Monthly | 1,2,3,4,5,7,8 |

#### The existing `Monthly Matrix Dosimetry Import` (test list #133) SHALL be replaced/renamed to `myqa_monthly_dosimetry` and consolidated into this new spec.

#### Scenario: Test slugs created from myQA test names

- GIVEN a myQA Numeric test condition with Name `1.01 6MV Output`
- WHEN the setup script creates the Test object
- THEN the slug SHALL be `myqa_daily_physics_1_01_6mv_output`
- AND the display name SHALL be `1.01 6MV Output`
- AND the type SHALL be `simple`

### Requirement: Tolerance mapping

The system SHALL create QATrack+ Tolerance objects from myQA WarnOn/FailOn values during setup.

#### Scenario: Absolute symmetric tolerance

- GIVEN a Numeric test with WarnOn=2.0, FailOn=3.0, BoundingType=0, IsRelative=0, LimitTendency=0
- WHEN the Tolerance is created
- THEN type SHALL be `absolute`
- AND tol_lower SHALL be -2.0 (Warn) or -3.0 (Fail)
- AND tol_upper SHALL be +2.0 (Warn) or +3.0 (Fail)

#### Scenario: Percent tolerance

- GIVEN a Numeric test with IsRelative=1
- WHEN the Tolerance is created
- THEN type SHALL be `percent`

#### Scenario: One-sided tolerance

- GIVEN a Numeric test with LimitTendency=1 (lower only)
- WHEN the Tolerance is created
- THEN tol_upper SHALL be NULL

### Requirement: UnitTestCollection creation

The system SHALL create UnitTestCollection objects for each unit and frequency combination listed in the test list table.

#### Scenario: Daily UTC for LA317

- GIVEN Unit LA317 (#3) and myqa_daily_physics test list
- WHEN the setup script runs
- THEN a UnitTestCollection SHALL exist with:
  - unit=3 (LA317)
  - test_collection=myqa_daily_physics
  - frequency=Daily
  - active=True
  - auto_schedule=True
  - visible_to=Physicist group

### Requirement: Historical data import (backfill)

The system SHALL import existing historical data from myQA for all configured task types and units.

#### Scenario: Backfill Daily QA for LA317

- GIVEN myQA has 10,936 Daily QA executions for LA317
- WHEN the import runs with `--days 365`
- THEN TestListInstances SHALL be created for each execution dated within the last 365 days
- AND each TestInstance SHALL store the myQA actual value
- AND the myQA execution UUID SHALL be stored in a `myqa_{list}_taskid` string_value test

#### Scenario: De-duplication

- GIVEN a myQA execution with UUID X has already been imported
- WHEN the import runs again
- THEN the import SHALL skip that execution (check by mtx_taskid string_value match)
- AND no duplicate TestInstances SHALL be created

### Requirement: Incremental daily import

The system SHALL run automatically on a schedule via django-q to import new myQA data.

#### Scenario: Daily import schedule

- GIVEN the django-q Schedule for `myqa_all` is configured
- WHEN 6pm AEST arrives
- THEN the import SHALL query myQA for executions newer than the last successful import date
- AND create new TestListInstances for any new executions found

#### Scenario: Manual trigger from UI

- GIVEN a user is logged into QATrack+ admin
- WHEN they navigate to `/admin/django_q/schedule/`
- AND click "Run" on the myqa_all schedule entry
- THEN the full import SHALL run on demand

### Requirement: Task name normalisation

The system SHALL map myQA task name variants to a canonical import handler.

| myQA Task Name | Maps To Handler |
|---|---|
| `5.Tmt.Linac.D2 - Daily QA (Physics)` | myqa_daily_physics |
| `5.Tmt.Linac.D - myQA Daily Constancy Check` | myqa_daily_constancy |
| `Daily Constancy Check` | myqa_daily_constancy (legacy) |
| `Daily Constancy Check[1-4]` | myqa_daily_constancy (legacy) |
| `5.Tmt.Linac.Monthly - Dosimetry` | myqa_monthly_dosimetry |
| `5.Tmt.Linac.M.Dosimetry - Monthly QA` | myqa_monthly_dosimetry |
| `5.Tmt.Linac.M.Dosimetry - Monthly QA (1)` | myqa_monthly_dosimetry |
| `5.Tmt.Linac.Monthly - Dosimetry (LA3 values...to update)` | myqa_monthly_dosimetry |

### Requirement: Execution type support

The import engine SHALL handle the following myQA execution types:

| Type | myQA Tables | Handler |
|---|---|---|
| Numeric | `MQA_Numeric_TestConditionExecutions` | Map Name→slug, store Actual as value, apply tolerances |
| PassFail | `MQA_PassFail_TestExecutions` | Map to boolean test, store pass/fail |
| Profile | `MQA_Dosimetry_Profile_Results` | Map DisplayName+ProfileDirection→slug, store Actual |
| Energy | `MQA_Dosimetry_Energy_ChamberExecutions` | Map ChamberNumber→slug, store Actual |
| Wedge | `MQA_Dosimetry_Wedge_QueueItemExecutions` | Map WedgeType+WedgeAngle→slug, store ActualValue |
| Output | `MQA_Dosimetry_Output_QueueItemExecutions` | Check column structure, store value |
| MLC | `MQA_MDL_MlcQA_Results` + detail tables | Extract pass rates and leaf positions |
| CBCT | `MQA_MDL_Cbct_Results` + detail tables | Extract HU, contrast, resolution values |
| Planar | `MQA_MDL_Planar_Results` + detail tables | Extract contrast, scaling values |
| VMAT | `MQA_MDL_VmatDmlc_Results` | Extract gamma pass rate |
| WinstonLutz | `MQA_IsoCheck_WinstonLutz_TestDefinitions/Executions` | Extract isocentre radius, offsets |

## Non-goals

- Importing commissiong tasks (`Commissioning.*`, `Device.QA.Quarterly.*`)
- Importing legacy CT QA (CatPhan, Waterloo, etc. — these are manual in QATrack+)
- Importing Strontium Check, Well Chamber, or other non-linac QA tasks
- Removing or modifying existing manual test lists in QATrack+
- Writing to the myQA database (read-only always)
- Supporting real-time or sub-daily import intervals
- Retroactive backfill beyond the `--days` flag limit
