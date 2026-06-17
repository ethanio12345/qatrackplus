# Tasks: Fix myQA Importers

> Implementation tasks derived from frozen `proposal.md`, `design.md`, and
> `specs/`. Each task ≤ 2 hours. Per-type setup-before-backfill ordering kills
> the Round 1 dependency inversion.
>
> **Branch:** `develop-myqa-fix-importers` (create from `develop` before Task 0.1).
> **Verification pipeline per task touching `.py` files:** `uv run ruff format &&
> uv run ruff check --fix && rm -rf .mypy_cache && uv run mypy &&
> uv run pytest`.
> **All management commands via:** `uv run python manage.py <command>`.

## Phase 0: Shared prerequisites

- [ ] **Task 0.1: Refactor Numeric importers per D1 (3-way split)**
  Replace `MyqaNumericImport` (`myqa_import.py:245-269`) with
  `MyqaNumericImportBase` (shared `extract_results`) + 3 subclasses setting only
  `list_slug`, `task_name_patterns` (full strings per `specs/numeric/spec.md`
  R3), and `frequency`. Slugs: `myqa_daily_constancy`, `myqa_daily_physics`,
  `myqa_dxr_daily`. No `myqa_numeric` slug anywhere.
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run python manage.py shell -c "from qatrack.myqa_import import TASK_TYPE_REGISTRY; assert 'myqa_numeric' not in TASK_TYPE_REGISTRY; assert 'numeric_constancy' in TASK_TYPE_REGISTRY"`

- [ ] **Task 0.2: Update registry + import_myqa_results default + UNITS_PER_LIST**
  - Update `TASK_TYPE_REGISTRY` (`myqa_import.py:560`): remove `'myqa_numeric'`,
    add `'numeric_constancy'`, `'numeric_physics'`, `'numeric_dxr'`.
  - Update `import_myqa_results` default (`myqa_import.py:583`):
    `task_type='myqa_numeric'` → `task_type='numeric_constancy'`.
  - Add `UNITS_PER_LIST` mapping to `setup_myqa_tests.py` (per design M8):
    `{'myqa_daily_constancy': [1,2,3,4,5,7,8], 'myqa_daily_physics': [1,2,3,4,5,7,8],
    'myqa_dxr_daily': [50], 'myqa_mlc': [1,2,3,4,5,7,8], 'myqa_cbct': [1,2,3,4,5,7,8],
    'myqa_planar': [1,2,3,4,5,7,8], 'myqa_vmat': [1,2,3,4,5,7,8],
    'myqa_winston_lutz': [1,2,3,4,5,7,8], 'myqa_passfail': [1,2,3,4,5,7,8]}`.
    DXR (unit 50) is excluded from MLC/CBCT/Planar/VMAT/WL/PassFail — those QA
    types are linac-specific (an orthovoltage unit doesn't perform them). The
    dual-pattern `task_name_patterns` (Linac + DXR) on these importers exist for
    forward-compat but DXR executions are not expected in practice. Drive UTC
    creation from this map (replaces the blanket `for unit_num in LINAC_MAP` at
    `setup_myqa_tests.py:232`).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run pytest qatrack/myqa_import/` (if existing); `uv run python manage.py shell -c "from qatrack.myqa_import import TASK_TYPE_REGISTRY; assert set(TASK_TYPE_REGISTRY) >= {'numeric_constancy','numeric_physics','numeric_dxr','myqa_mlc','myqa_cbct','myqa_planar','myqa_vmat','myqa_winston_lutz','myqa_passfail'}"`

## Phase 1: Numeric (Daily QA) — 3,670 sessions, high priority

- [ ] **Task 1.1: Rewrite Numeric `extract_results`**
  Per `specs/numeric/spec.md` R1-R2: `SELECT tcne.Name, tcne.Actual` with JOIN
  chain `tcne.NumericTestExecution_Id → tie.Id → te.Id`, filter
  `WHERE te.TaskExecutionId = %s`. No tolerance columns in import path (setup-
  only per S3). No `MQA_TestConditions` JOIN.
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run pytest tests/myqa_import/test_numeric.py -k test_extract_results` (write in Task 8.1)

- [ ] **Task 1.2: Rewrite Numeric setup discovery query (per D2)**
  Replace triple-broken query (`setup_myqa_tests.py:77-87`) with corrected
  query per `specs/numeric/spec.md` R4. Run once per `task_name_pattern`,
  writing into each respective list. Tolerance via `get_or_create_tolerance`
  with `WarnOn`/`FailOn`/`BoundingType`/`IsRelative`/`LimitTendency`.
  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run` (shows discovered Names per list)

- [ ] **Task 1.3: Backfill Numeric**
  For each of the 3 lists: `setup_myqa_tests --force` then `import_myqa_results
  --task <key> --days 365`. Re-run import; assert 0 new (dedup via taskid).
  **Verify:** TLI count across the 3 lists ≈ 3,670 (per `proposal.md` Data Volumes).
  **Rollback note:** `--force` on `myqa_daily_constancy`/`myqa_daily_physics`/
  `myqa_dxr_daily` deletes existing main-spec Tests (design `--force` safety
  table). Verify no production TestListInstances reference these slugs first.

## Phase 2: Winston Lutz — 400 sessions, medium priority

- [ ] **Task 2.1: Rewrite WL `extract_results` + setup**
  Per `specs/winston-lutz/spec.md`: `SELECT MaximumDeviation2D, Deviation3D,
  Tolerance_Warn, Tolerance_Fail` JOIN `wl.Id → tie.Id → te.Id` filter
  `te.TaskExecutionId = %s`. Setup: hardcoded 2 Tests, 1 shared two-sided
  absolute Tolerance (no `LimitTendency` → assume 0).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`; `uv run python manage.py import_myqa_results --task myqa_winston_lutz --days 30`

- [ ] **Task 2.2: Backfill WL**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_winston_lutz
  --days 365`; re-run for dedup.
  **Verify:** TLI count ≈ 400.

## Phase 3: MLC — 252 sessions, medium priority

- [ ] **Task 3.1: Rewrite MLC `extract_results`**
  Per `specs/mlc/spec.md` R1-R2: METRICS dict (5 prefixes: FailingPeaks,
  MaximumDeviation, InterstripRatio, StandardDeviation, IsocenterToStripDistance
  — each 4-tuple) + STRING_COLS (`TotalPeaks` value-only; `LeavesThatFailed`
  string; `TestResult` verdict-only logged). JOIN chain `r.MlcQATestExecutionBase_Id
  → mte.Id → tie.Id → te.Id`, filter `te.TaskExecutionId = %s`. Replaces broken
  `MlcQAQueueItemExecution_Id` path (`myqa_import.py:446-448`).
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run pytest tests/myqa_import/test_mlc.py`

- [ ] **Task 3.2: MLC setup (7 Tests — every emitted slug)**
  Per `specs/mlc/spec.md` R3: create Test+UTI for ALL 7 emitted slugs (5 prefixes
  with tolerance + `myqa_mlc_total_peaks` value-only + `myqa_mlc_leaves_that_failed`
  type='string'). Engine silently drops slugs lacking a Test
  (`myqa_import.py:209-211`). `Test.type='string'` for LeavesThatFailed (engine
  `isinstance(val,str)` routing at `myqa_import.py:219-220`).
  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`; confirm 7 Tests listed.

- [ ] **Task 3.3: Backfill MLC**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_mlc --days 365`;
  re-run for dedup.
  **Verify:** TLI count ≈ 252.

## Phase 4: VMAT — 247 sessions, medium priority

- [ ] **Task 4.1: Rewrite VMAT `extract_results` (parent + child fan-out)**
  Per `specs/vmat/spec.md` R1-R4: parent query (`NormalizationValueResult_Value_Value`
  from `MQA_MDL_VmatDmlc_Results`) + child query (iterate
  `MQA_MDL_VmatDmlc_RoiResults` via `VmatDmlcResult_Id`, emit `{roi}_mean` +
  `{roi}_std_dev` per row). Both filter `te.TaskExecutionId = %s`. ROI slug rule:
  strip brackets, `slugify_name` (preserves periods — verify URL safety).
  **Decision (O3):** if QATrack+ URL routing rejects periods in slugs, pre-strip
  periods in the `clean()` helper before slugify; both outcomes (periods kept or
  stripped) are acceptable per O3. Verify with a quick URL render test first.
  Replaces broken `VmatDmlcQueueItemExecution_Id` path (`myqa_import.py:524-526`).
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run pytest tests/myqa_import/test_vmat.py`

- [ ] **Task 4.2: VMAT setup (static parent + ROI discovery)**
  Per `specs/vmat/spec.md` R5: static `NormalizationValue` Test + discovery
  query `SELECT DISTINCT rr.Name` from child table (JOIN through parent + te,
  filter `te.TaskName LIKE %s`). Each distinct Name → 2 Tests (Mean + StdDev)
  with shared tolerances from parent (`RoiMean*`, `RoiStd*`).
  **Files:** `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run python manage.py setup_myqa_tests --dry-run`

- [ ] **Task 4.3: Backfill VMAT**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_vmat --days 365`;
  re-run for dedup.
  **Verify:** TLI count ≈ 247.

## Phase 5: CBCT — 46 sessions, low priority

- [ ] **Task 5.1: Rewrite CBCT `extract_results` + setup**
  Per `specs/cbct/spec.md`: 9 METRICS prefixes (4-tuple each) +
  `SliceWidthDifference` value-only. Same-UUID JOIN (`r.Id → cte.Id → tie.Id →
  te.Id`), filter `te.TaskExecutionId = %s`. Setup: 10 Tests (9 prefixes with
  tolerance + `SliceWidthDifference` value-only). Replaces broken
  `CbctQueueItemExecution_Id` path (`myqa_import.py:474-476`).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run pytest tests/myqa_import/test_cbct.py`; `setup_myqa_tests --dry-run` (10 Tests)

- [ ] **Task 5.2: Backfill CBCT**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_cbct --days 365`;
  re-run for dedup.
  **Verify:** TLI count ≈ 46.

## Phase 6: Planar — 4 sessions, low priority

- [ ] **Task 6.1: Rewrite Planar `extract_results` + setup**
  Per `specs/planar/spec.md`: 7 METRICS prefixes (4-tuple each). Same-UUID JOIN
  (`r.Id → pte.Id → tie.Id → te.Id`), filter `te.TaskExecutionId = %s`. Setup:
  7 Tests with tolerance. Replaces broken `PlanarQueueItemExecution_Id` path
  (`myqa_import.py:499-501`).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run pytest tests/myqa_import/test_planar.py`; `setup_myqa_tests --dry-run` (7 Tests)

- [ ] **Task 6.2: Backfill Planar**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_planar --days 365`;
  re-run for dedup.
  **Verify:** TLI count ≈ 4.

## Phase 7: PassFail — low priority

- [ ] **Task 7.1: Rewrite PassFail `extract_results` + setup**
  Per `specs/passfail/spec.md`: `SELECT AcceptanceCriteria` JOIN
  `pfte.Id → tie.Id → te.Id` filter `te.TaskExecutionId = %s`. Single Test
  `myqa_passfail_acceptance_criteria` type='string', no tolerance. Removes
  broken `PassStatus` + `MQA_TestConditions` reads (`myqa_import.py:282-291`).
  **Confirm:** verify `task_name_patterns` (currently `['5.Tmt.Linac.P%',
  '5.Tmt.DXR.P%']` at `myqa_import.py:273`) against actual myQA PassFail
  TaskName values; correct if the `P%` prefix is wrong (else import finds zero
  sessions).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** `uv run pytest tests/myqa_import/test_passfail.py`

- [ ] **Task 7.2: Backfill PassFail**
  `setup_myqa_tests --force`; `import_myqa_results --task myqa_passfail --days 365`;
  re-run for dedup.

## Phase 8: Tests + migration

- [ ] **Task 8.1: pytest for all 7 importers**
  Per `specs/` scenarios: happy path + NULL value + empty-result-set for each
  importer. Tests in `tests/myqa_import/` mirroring package structure. Mock the
  myQA DB connection (pymssql cursor) with fixture rows from
  `schema-reference.md`. Assert emitted slugs + values + `pass_fail='no_tol'`.
  **Files:** `tests/myqa_import/test_numeric.py`, `test_mlc.py`, `test_cbct.py`,
  `test_planar.py`, `test_vmat.py`, `test_winston_lutz.py`, `test_passfail.py`
  **Verify:** `uv run pytest tests/myqa_import/ -v`

- [ ] **Task 8.2: pytest for setup command**
  Per `specs/` setup requirements: assert Test + UTI + Tolerance + UTC creation
  for every emitted slug (including value-only and string types — the silent-drop
  trap). Assert `UNITS_PER_LIST` scoping (no spurious DXR UTC on Linac lists).
  **Files:** `tests/myqa_import/test_setup.py`
  **Verify:** `uv run pytest tests/myqa_import/test_setup.py -v`

- [ ] **Task 8.3: django-q Schedule migration + production pre-flight**
  - Migrate existing django-q `Schedule` rows passing `task_type='myqa_numeric'`
    to the 3 new keys (`numeric_constancy`, `numeric_physics`, `numeric_dxr`).
  - Production pre-flight: confirm no orphan `myqa_numeric_*` TestInstances
    exist (proposal Non-goal: broken setup → engine `get()` raised
    `DoesNotExist` → expected no data). If any exist, document + decide cleanup.
  **Files:** data migration script or admin walk-through; `django_q_schedule` table.
  **Verify:** `uv run python manage.py shell -c "from django_q.models import Schedule; print([(s.name, s.func) for s in Schedule.objects.all()])"`

## Cross-cutting

- **Idempotency:** every backfill task re-runs safely via `mtx_taskid` /
  `{list_slug}_taskid` dedup (`myqa_import.py:150-156`). Re-importing the same
  execution is a no-op.
- **Rollback:** `--force` only affects the target list's Tests/Memberships
  (design `--force` safety table). Main-spec daily lists (`myqa_daily_constancy`,
  `myqa_daily_physics`, `myqa_dxr_daily`) require production verification before
  `--force`. New lists (`myqa_mlc`, etc.) are safe — no existing data.
- **No engine refactor:** `query_new_sessions`, `extract_results` base class,
  and `import_session` write path are unchanged (per proposal Non-goal). D4
  verdict storage deferred — `pass_fail='no_tol'` everywhere.
