# Tasks: Full myQA Sync

> Decisions and model facts in `explore-brief.md` are binding. Each task is
> scoped to ≤2 hours. Every task ends with a concrete Verification step.
> Python execution uses `uv run` (never bare `python`/`pip`). Logging via the
> `logging` module (percent-style lazy formatting), never `print()`.

## Task 1: Base import engine + mappers

**Files:** `qatrack/myqa_import.py` (new)

- Create `MyqaImportBase` mirroring `MatrixResultImporter` (`matrix_import.py:34`):
  - `connect()` — `pymssql.connect` from `settings.MYQA_DB_*`
  - `unit_to_device` map (mirror `matrix_import.py:386-400`)
  - `query_new_sessions(days, unit_numbers)` — date-bounded header query on
    `MQA_TestExecutions`, device-name filter resolved from unit numbers
  - `duplicate_check(execution_id, unit)` — ORM lookup against the de-dup slug
    (`myqa_taskid`, or `mtx_taskid` for the consolidated matrix type) +
    `string_value == str(execution_id)`
  - `import_session(myqa_exec, unit, day)` — `transaction.atomic()`; creates
    `TestListInstance` + `bulk_create(TestInstance[])` with `pass_fail='no_tol'`;
    writes one de-dup `TestInstance` (`string_value = str(TaskExecutionId)`)
  - `run(days, unit_numbers)` — orchestrate query→extract→de-dup→import, return
    summary `{found, imported, skipped, errors}`
- Create `myqa_to_qatrack_tolerance(warn_on, fail_on, is_relative, limit_tendency)`
  per the two-band offset table in `explore-brief.md` (warn→tol_*, fail→act_*).
- Create `myqa_name_to_slug(list_slug, name)` (dots stripped, `[^a-z0-9]+` → `_`).
- Define `DEDUP_SLUG = 'myqa_taskid'` constant + a subclass override hook for the
  matrix type to reuse `'mtx_taskid'`.
- `extract_results()` declared abstract.

**Verification:** `uv run python -c "from qatrack.myqa_import import MyqaImportBase, myqa_to_qatrack_tolerance, myqa_name_to_slug; assert myqa_name_to_slug('myqa_daily_physics','1.01 6MV Output')=='myqa_daily_physics_1_01_6mv_output'; print('OK')"`

## Task 2: Simple handlers (Numeric, PassFail, Output)

**Files:** `qatrack/myqa_import.py`

- `MyqaNumericImport(MyqaImportBase)` — reads `MQA_Numeric_TestConditionExecutions`;
  each condition → `(myqa_name_to_slug(list_slug, Name), Actual, None)`.
- `MyqaPassFailImport(MyqaImportBase)` — reads `MQA_PassFail_TestExecutions`; maps
  result to a value/string.
- `MyqaOutputImport(MyqaImportBase)` — reads `MQA_Dosimetry_Output_QueueItemExecutions`.
- Register the three in the handler registry (task-name pattern → class).

**Verification:** `uv run python -c "from qatrack.myqa_import import MyqaNumericImport; print(MyqaNumericImport().execution_type)"`

## Task 3: Dosimetry handlers (Profile, Energy, Wedge)

**Files:** `qatrack/myqa_import.py`

- `MyqaProfileImport` — `MQA_Dosimetry_Profile_Results`; slug key =
  `DisplayName`+`ProfileDirection` (multi-key composite).
- `MyqaEnergyImport` — `MQA_Dosimetry_Energy_ChamberExecutions`; slug key =
  `ChamberNumber`.
- `MyqaWedgeImport` — `MQA_Dosimetry_Wedge_QueueItemExecutions`; slug key =
  `WedgeType`+`WedgeAngle`.
- Register all three. Each emits a distinct, stable slug per natural-key row.

**Verification:** `uv run python -c "from qatrack.myqa_import import MyqaProfileImport, MyqaEnergyImport, MyqaWedgeImport; print('OK')"`

## Task 4: MDL sub-table handlers (MLC, CBCT, Planar, VMAT) + WinstonLutz

**Files:** `qatrack/myqa_import.py`

- `MyqaMlcImport` — `MQA_MDL_MlcQA_Results` (+ detail); one row per leaf-pair key.
- `MyqaCbctImport` — `MQA_MDL_Cbct_Results`; one row per slice/metric key.
- `MyqaPlanarImport` — `MQA_MDL_Planar_Results`.
- `MyqaVmatImport` — `MQA_MDL_VmatDmlc_Results` (gamma pass rate, etc.).
- `MyqaWinstonLutzImport` — `MQA_IsoCheck_WinstonLutz_TestExecutions`.
- Register all five. For tables whose exact column structure is not yet known,
  implement against the documented table name and add a `TODO` + log warning on
  unknown columns (schema introspection happens at apply time on production).

> **Scope note:** This is 5 handlers — the hardest mapping work. If it exceeds
> 2h, split at apply time into Task 4a (MDL: MLC/CBCT/Planar/VMAT) and
> Task 4b (IsoCheck: WinstonLutz). The TODO/log-warning escape hatch keeps the
> scaffolding shippable even with unknown schemas.

**Verification:** `uv run python -c "from qatrack.myqa_import import MyqaMlcImport, MyqaWinstonLutzImport; print('OK')"`

## Task 5: Task-name normalisation registry

**Files:** `qatrack/myqa_import.py`, `qatrack/qa/tests/test_myqa_normalisation.py` (new)

- Build a registry mapping compiled-regex variants of myQA `TaskName` to canonical
  handler classes (legacy casing, parenthetical suffixes, free-text notes — see
  the variant list captured in `explore-brief.md`).
- Unit tests covering: exact canonical names, legacy aliases, trailing `(1)` /
  `[1-4]` suffixes, free-text-note variants, and an unknown-name fallback that
  raises/log-warns.

**Verification:** `uv run pytest qatrack/qa/tests/test_myqa_normalisation.py -q`

## Task 6: `setup_myqa_tests.py` management command

**Files:** `qatrack/qa/management/commands/setup_myqa_tests.py` (new)

- Query myQA DISTINCT test names per task type.
- Create `Test` (`myqa_`-prefixed slug via `myqa_name_to_slug`), `Tolerance`
  (via `myqa_to_qatrack_tolerance`), `TestList` (×19), `TestListMembership`.
- Create `UnitTestCollection` per (unit, frequency), `active=True`.
- Create the single de-dup `Test` (slug `myqa_taskid`).
- Slug-collision detection: on collision, log a warning and append `_2`, `_3`, …
- Flags: `--dry-run` (print plan, write nothing), `--force` (re-create).

> **Scope note:** This covers a lot of ORM surface. If it exceeds 2h, split at
> apply time into (a) Test/Tolerance/TestList/Membership creation + collision
> detection, and (b) UnitTestCollection + dedup Test + flag wiring.

**Verification:** `uv run python manage.py setup_myqa_tests --dry-run` and review the printed plan (list counts, sample slugs, collision warnings).

## Task 7: `import_myqa.py` management command

**Files:** `qatrack/qa/management/commands/import_myqa.py` (new)

- Flags: `--task` (filter to one task type), `--unit` (filter to one unit),
  `--days` (lookback; default 30 for manual runs), `--dry-run`.
  > The default differs from the cron's `--days 2` intentionally: manual runs
  > use a wider window so an operator can inspect more history in one go, while
  > the cron keeps a tight idempotent window.
- Resolve handler via the normalisation registry; instantiate; call `run()`.
- Print summary `{found, imported, skipped, errors}`.

**Verification:** `uv run python manage.py import_myqa --task myqa_daily_physics --unit 3 --days 7 --dry-run`

## Task 8: Wire into `tasks.py` + `apps.py`

**Files:** `qatrack/qa/tasks.py` (modify), `qatrack/qa/apps.py` (modify)

- Add `import_myqa_all(days=2)` to `tasks.py` — iterate task types × units, call
  each handler's `run()`, aggregate summaries, log via `logging`.
- Register a django-q `Schedule` in `apps.py`: DAILY at **18:00 `Australia/Sydney`**
  (django-q resolves AEST/AEDT DST), func `qatrack.qa.tasks.import_myqa_all`.
- Consolidate: remove/redirect the existing "Matrix Monthly Import" schedule into
  the daily `import_myqa_all` run (matrix task type routes through the new engine).

**Verification:** `uv run python manage.py shell -c "from qatrack.qa.tasks import import_myqa_all; print(import_myqa_all.__name__)"` then confirm the new Schedule appears in `/admin/django_q/schedule/`.

## Task 9: Consolidate matrix import + migrate #133 data

**Files:** `qatrack/matrix_import.py` (modify), `qatrack/qa/management/commands/import_matrix_monthly.py` (modify)

- Route the monthly matrix task type through the new `MyqaProfileImport`/
  `MyqaEnergyImport`/`MyqaWedgeImport` handlers; reuse the `mtx_taskid` de-dup slug
  so historical `TestListInstance` rows under TestList #133 are never re-imported.
- Add a deprecation notice to `import_matrix_monthly.py` pointing at
  `import_myqa.py` (keep it functional as a shim during transition).
- Verify existing #133 `TestListInstance` rows remain visible after the
  consolidation (no data migration of historical rows is required — they stay
  under #133; only new imports flow through the new engine).

**Verification:** `uv run python manage.py import_matrix_monthly --help` shows a deprecation notice; existing #133 rows still render in QATrack+.

## Task 10: Import engine unit tests

**Files:** `qatrack/qa/tests/test_myqa_import.py` (new)

- Tests for `myqa_to_qatrack_tolerance` — all 6 cells of the
  `is_relative × limit_tendency` matrix (assert exact `tol_*`/`act_*` values).
- Tests for `myqa_name_to_slug` — including dot-stripping, double-underscore
  collapse, and a collision-suffix helper.
- Tests for `duplicate_check` using an in-memory/mock myQA execution id.
- Tests for `import_session` transactional behaviour (success path + a failure
  that leaves prior sessions intact).

**Verification:** `uv run pytest qatrack/qa/tests/test_myqa_import.py -q`

## Task 11: Tolerance validation against real myQA data

- Spot-check: pick 5–10 representative Numeric tests from myQA, run the setup
  script, and confirm the created `Tolerance` objects produce expected
  `ok`/`tolerance`/`action` statuses when fed known values (manual or scripted).
- Document any myQA tolerance shapes that don't map cleanly (e.g. `IsRelative`
  without a usable reference) and decide a fallback (default: skip tolerance,
  `type='absolute'` with no bounds).

**Verification:** A short written note in the change directory
(`tolerance-validation.md`) listing the spot-check cases and their mapped
tolerances, with sign-off that each behaves correctly.

## Task 12: Backfill historical data

- For each task type × unit: `uv run python manage.py import_myqa --task <t> --unit <u> --days 365`.
- Record per-run summaries; confirm imported counts are plausible vs. myQA.

**Verification:** QATrack+ admin shows the expected `TestListInstance` counts per unit/task; no errors in the run logs.

## Task 13: Final verification + operator docs

- Re-run the daily import window a second time → confirm **0 new imports**
  (de-dup holds).
- Confirm the django-q schedule fires at 18:00 Sydney time and the "Run" button
  in `/admin/django_q/schedule/` triggers the full import.
- Write `docs/myqa_sync.md`: the two management commands (flags, dry-run,
  rollback notes), the daily schedule, the de-dup mechanism, and how to add a
  new task type.

**Verification:** `uv run python manage.py import_myqa --days 2 --dry-run` reports `imported=0` on the second consecutive run; `docs/myqa_sync.md` exists and documents all commands.
