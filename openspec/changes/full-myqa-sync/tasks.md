# Tasks: Full myQA Sync

- [x] **Task 1: Create `myqa_import.py` — Import engine**

  **Files:** `qatrack/myqa_import.py` (new)

  - Create base class `MyqaImportBase` with:
    - `query_new_sessions(days, unit_numbers)`
    - `duplicate_check(execution_id)` — checks `myqa_{list_slug}_taskid` string_value
    - `import_session(myqa_exec, unit, day)` — creates TLI + TIs
    - `myqa_to_qatrack_tolerance()` — tolerance converter
  - Create handler classes for each execution type:
    - `MyqaNumericImport(MyqaImportBase)` — reads `MQA_Numeric_TestConditionExecutions`
    - `MyqaPassFailImport(MyqaImportBase)` — reads `MQA_PassFail_TestExecutions`
    - `MyqaProfileImport(MyqaImportBase)` — reads `MQA_Dosimetry_Profile_Results`
    - `MyqaEnergyImport(MyqaImportBase)` — reads `MQA_Dosimetry_Energy_ChamberExecutions`
    - `MyqaWedgeImport(MyqaImportBase)` — reads `MQA_Dosimetry_Wedge_QueueItemExecutions`
    - `MyqaOutputImport(MyqaImportBase)` — reads `MQA_Dosimetry_Output_QueueItemExecutions`
    - `MyqaMlcImport(MyqaImportBase)` — reads `MQA_MDL_MlcQA_Results`
    - `MyqaCbctImport(MyqaImportBase)` — reads `MQA_MDL_Cbct_Results`
    - `MyqaPlanarImport(MyqaImportBase)` — reads `MQA_MDL_Planar_Results`
    - `MyqaVmatImport(MyqaImportBase)` — reads `MQA_MDL_VmatDmlc_Results`
    - `MyqaWinstonLutzImport(MyqaImportBase)` — reads `MQA_IsoCheck_WinstonLutz_TestExecutions`
  - Create task-to-handler registry dict
  - Create `import_myqa_results(META)` entry point for web UI manual trigger
  - Create `slugify_name(list_slug, name)` helper

  **Verification:** `python -c "from qatrack.myqa_import import MyqaImportBase; print('OK')"`

- [x] **Task 2: Create `setup_myqa_tests.py` — One-time setup**

  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py` (new)

  - Query myQA for DISTINCT test names per task type
  - Generate Test objects with slugs
  - Create Tolerance objects from Warn/Fail values
  - Create TestList + TestListMembership objects
  - Create UnitTestCollection per unit/frequency
  - Support `--dry-run` flag
  - Support `--force` to re-create

  **Verify:** Run `python manage.py setup_myqa_tests --dry-run`, review output

- [x] **Task 3: Create `import_myqa.py` management command**

  **Files:** `qatrack/qa/management/commands/import_myqa.py` (new)

  - `--task` flag: filter to specific task type
  - `--unit` flag: filter to specific unit
  - `--days` flag: lookback window (default 30)
  - `--dry-run` flag: preview without writing
  - Calls the appropriate `MyqaImportBase` subclass
  - Reports summary (found/imported/skipped/errors)

  **Verify:** `python manage.py import_myqa --task myqa_daily_physics --unit 3 --days 7 --dry-run`

- [x] **Task 4: Wire into `tasks.py` + `apps.py`**

  **Files:** `qatrack/qa/tasks.py` (modify), `qatrack/qa/apps.py` (modify)

  - Add `import_myqa_all()` to `tasks.py` — iterates all task types/units
  - Register Schedule entries in `apps.py`:
    - Daily import: `import_myqa_all` at 6pm AEST
  - Consolidate existing `import_matrix_monthly` schedule into the new daily import

  **Verify:** Check `/admin/django_q/schedule/` for the new schedule entry

- [x] **Task 5: Consolidate existing matrix import**

  **Files:** `qatrack/matrix_import.py` (modify), `qatrack/qa/management/commands/import_matrix_monthly.py` (deprecate)

  - Rename test list #133 from `Monthly Matrix Dosimetry Import` to `myqa_monthly_dosimetry`
  - Have the existing matrix import call through to the new `MyqaProfileImport`/`MyqaEnergyImport`/`MyqaWedgeImport`
  - Deprecation notice on old management command pointing to `import_myqa.py`

  **Verify:** Run old command with `--help`, confirm it mentions deprecation

- [x] **Task 6: Backfill historical data**

  - Run `python manage.py import_myqa --days 365 --task myqa_daily_physics --unit 3`
  - Run for each task type and unit
  - Verify counts match expected from myQA

  **Verify:** Check QATrack+ admin for imported TestListInstances

- [x] **Task 7: Run automated verification**

  - Run a second time to confirm de-duplication works (0 new imports)
  - Check that django-q schedule fires correctly
  - Test manual trigger from `/admin/django_q/schedule/`
