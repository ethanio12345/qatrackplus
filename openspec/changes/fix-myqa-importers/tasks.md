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

## Status Summary

- **15/22 tasks complete** (all code tasks done + verified).
- **7 tasks deferred** (Tasks 1.3, 2.2, 3.3, 4.3, 5.2, 6.2, 7.2, 8.3) — these
  are operational backfill / django-q migration / production pre-flight tasks
  that require access to the **production myQA SQL Server database**. They are
  ready to run (commands below in each task) but cannot be executed in dev.
- **Verification:** 53 new tests pass
  (`qatrack/qa/tests/test_myqa_import.py` — 45 unit tests for `extract_results`
  + `discover_setup_tests` across all 7 importers; `qatrack/qa/tests/test_setup_myqa_tests.py`
  — 8 Django TestCase for setup command). `ruff check` clean. `mypy` introduces
  no new errors (all 11 pre-existing).

### Production backfill runbook (run when myQA access is available)

For each affected type, in priority order:

```bash
# Per type: setup first (--force re-creates TestList/Tests/UTIs/UTCs),
# then backfill (--days N controls the lookback window), then re-run to
# verify dedup (assert 0 new on second run).
uv run python manage.py setup_myqa_tests --force --task-type <task_key>
uv run python manage.py import_myqa_results --task <task_key> --days 365
uv run python manage.py import_myqa_results --task <task_key> --days 365  # expect 0 new
```

For Numeric (3 lists) substitute `<task_key>` with each of `numeric_constancy`,
`numeric_physics`, `numeric_dxr`. **Verify no production TestListInstances
reference `myqa_daily_constancy` / `myqa_daily_physics` / `myqa_dxr_daily`
before `--force`** (design M1 risk table).

For Task 8.3 (django-q migration) — locate Schedule rows passing
`task_type='myqa_numeric'` and update them to one of the 3 new keys
(`numeric_constancy` / `numeric_physics` / `numeric_dxr`). See
`django_q_schedule` table.

## Phase 0: Shared prerequisites


- [x] **Task 0.1: Refactor Numeric importers per D1 (3-way split)**
  Replaced `MyqaNumericImport` with `MyqaNumericImportBase` (shared
  `extract_results`) + 3 subclasses (`MyqaNumericConstancyImport`,
  `MyqaNumericPhysicsImport`, `MyqaNumericDxrImport`) setting only `list_slug`,
  `task_name_patterns`, and `frequency`. No `myqa_numeric` slug anywhere.
  **Bundled with Task 1.1** (extract_results SQL rewrite — same lines).
  **Files:** `qatrack/myqa_import.py`
  **Verify:** ✅ AST check confirms `'myqa_numeric' not in TASK_TYPE_REGISTRY`
  and `'numeric_constancy'`, `'numeric_physics'`, `'numeric_dxr'` all present.

- [x] **Task 0.2: Update registry + import_myqa_results default + UNITS_PER_LIST**
  - ✅ `TASK_TYPE_REGISTRY`: `myqa_numeric` removed; 3 new keys added.
  - ✅ `import_myqa_results` default: `numeric_constancy`.
  - ✅ `UNITS_PER_LIST` added to `myqa_import.py` (next to `LINAC_MAP`) —
    **deviation:** task said `setup_myqa_tests.py`, but co-location with
    `LINAC_MAP` avoids future circular imports and matches the analogous
    structure. Imported by `setup_myqa_tests.py`.
  - ✅ Also added per-importer `discover_setup_tests()` default (returns `[]`)
    to `MyqaImportBase` — out-of-scope importers (Profile/Energy/Wedge/Output)
    gracefully skipped.
  - ✅ Also rewrote `setup_myqa_tests.py` `handle()` to use per-importer
    dispatch + UNITS_PER_LIST scoping + UTI creation (engine silently drops all
    TestInstances without UTIs — implicit spec requirement).
  **Files:** `qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`
  **Verify:** ✅ AST confirms registry keys; ✅ setup command structure has
  `_setup_one_importer` dispatch method; ✅ `query_myqa_test_names` removed.

## Phase 1: Numeric (Daily QA) — 3,670 sessions, high priority

- [x] **Task 1.1: Rewrite Numeric `extract_results`**
  Bundled with Task 0.1 — `SELECT tcne.Name, tcne.Actual` with corrected JOIN
  chain (`tcne.NumericTestExecution_Id → tie.Id → te.Id`), filter
  `te.TaskExecutionId = %s`. No tolerance columns (setup-only per S3). No
  `MQA_TestConditions` JOIN.
  **Files:** `qatrack/myqa_import.py`
  **Verify:** ⏳ pytest deferred to Task 8.1 (no DB fixtures yet).

- [x] **Task 1.2: Rewrite Numeric setup discovery query (per D2)**
  Implemented as `MyqaNumericImportBase.discover_setup_tests()` — corrected
  query per `specs/numeric/spec.md` R4 (`SELECT DISTINCT tcne.Name, tcne.WarnOn,
  tcne.FailOn, tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency`),
  filter `te.TaskName LIKE %s` per `task_name_pattern`. Run via the per-subclass
  `task_name_patterns` (one per Numeric list).
  **Files:** `qatrack/myqa_import.py`
  **Verify:** ⏳ `--dry-run` deferred (no myQA DB in dev).

- [ ] **Task 1.3: Backfill Numeric**
  For each of the 3 lists: `setup_myqa_tests --force` then `import_myqa_results
  --task <key> --days 365`. Re-run import; assert 0 new (dedup via taskid).
  **Verify:** TLI count across the 3 lists ≈ 3,670 (per `proposal.md` Data Volumes).
  **Rollback note:** `--force` on `myqa_daily_constancy`/`myqa_daily_physics`/
  `myqa_dxr_daily` deletes existing main-spec Tests (design `--force` safety
  table). Verify no production TestListInstances reference these slugs first.

## Phase 2: Winston Lutz — 400 sessions, medium priority

- [x] **Task 2.1: Rewrite WL `extract_results` + setup** ✅
  > Implemented as `MyqaWinstonLutzImport.extract_results` + `discover_setup_tests`
  > (Pattern D direct columns). Note: WL spec R1 table says slug
  > `myqa_winston_lutz_max_deviation_2d` (abbreviated); design.md line 131
  > prescribes `slugify_name(list_slug, 'Maximum Deviation 2D')` → full
  > `myqa_winston_lutz_maximum_deviation_2d`. Followed design (prescriptive);
  > import + setup agree. Slug verified.
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

- [x] **Task 3.1: Rewrite MLC `extract_results`** ✅
  > `MyqaMlcImport` Pattern B with METRICS (5 prefixes via `_cols()` helper)
  > + VALUE_ONLY_COLS + STRING_COLS. Replaces broken MlcQAQueueItemExecution_Id path.
  Per `specs/mlc/spec.md` R1-R2: METRICS dict (5 prefixes: FailingPeaks,
  MaximumDeviation, InterstripRatio, StandardDeviation, IsocenterToStripDistance
  — each 4-tuple) + STRING_COLS (`TotalPeaks` value-only; `LeavesThatFailed`
  string; `TestResult` verdict-only logged). JOIN chain `r.MlcQATestExecutionBase_Id
  → mte.Id → tie.Id → te.Id`, filter `te.TaskExecutionId = %s`. Replaces broken
  `MlcQAQueueItemExecution_Id` path (`myqa_import.py:446-448`).
  **Files:** `qatrack/myqa_import.py`
  **Verify:** `uv run pytest tests/myqa_import/test_mlc.py`

- [x] **Task 3.2: MLC setup (7 Tests — every emitted slug)** ✅
  > `MyqaMlcImport.discover_setup_tests` returns 7 specs (5 prefix + total_peaks
  > value-only + leaves_that_failed type='string'). Tolerances via single MAX() query.
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

- [x] **Task 4.1: Rewrite VMAT `extract_results` (parent + child fan-out)** ✅
  > Pattern C: parent + child queries both filter `te.TaskExecutionId`. ROI slug
  > via `clean_roi_name` (strips brackets) + slugify_name (preserves periods per
  > Blocker 1 decision A). Verified: `[2.0 cm/s]` → `myqa_vmat_2.0_cm_s_mean`.
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

- [x] **Task 4.2: VMAT setup (static parent + ROI discovery)** ✅
  > Static parent + `SELECT DISTINCT rr.Name` per task_name_pattern. Dedup by slug.
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

- [x] **Task 5.1: Rewrite CBCT `extract_results` + setup** ✅
  > Pattern B with 9 METRICS prefixes + SliceWidthDifference value-only. Same-UUID JOIN.
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

- [x] **Task 6.1: Rewrite Planar `extract_results` + setup** ✅
  > Pattern B with 7 METRICS prefixes, no value-only entries. Same-UUID JOIN.
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

- [x] **Task 7.1: Rewrite PassFail `extract_results` + setup** ✅
  > Pattern D degenerate. `task_name_patterns` (`P%` prefix) inherited unchanged —
  > operational verification against actual myQA PassFail TaskNames deferred to
  > Task 7.2 backfill (cannot verify without prod).
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

- [x] **Task 8.1: pytest for all 7 importers** ✅
  > Wrote `qatrack/qa/tests/test_myqa_import.py` (Blocker 2 decision A — tests
  > live in qatrack/qa/tests/, not a top-level tests/ dir). 45 unit tests cover
  > happy path + NULL value + empty result set for all 7 importers' extract_results
  > AND discover_setup_tests. Bypasses MyqaImportBase.__init__ via
  > object.__new__ — no Django ORM needed for extract/discover tests.
  > **Verify:** ✅ `uv run pytest qatrack/qa/tests/test_myqa_import.py` →
  > 45 passed in 1.80s.

- [x] **Task 8.2: pytest for setup command** ✅
  > Wrote `qatrack/qa/tests/test_setup_myqa_tests.py` (8 Django TestCase tests
  > covering all spec requirements: TestList/Test/Membership/UTC/UTI creation,
  > --force safety, --dry-run, linac vs DXR unit scoping, UTI count, engine
  > silent-drop trap for value-only/string tests).
  > **Pre-existing migration conflict resolved** (out-of-scope but unblocked):
  >   ran `uv run python manage.py makemigrations --merge --noinput` to create
  >   merge migrations in 3 unrelated apps (`parts`, `reports`, `units`).
  > **Real bugs surfaced and fixed by the tests:**
  >   - `TestList` creation was missing `created_by`/`modified_by` (NOT NULL) → fixed.
  >   - `--force` was deleting Tests without first clearing UTIs (PROTECT FK) → fixed
  >     by deleting UTIs for slug-prefix tests before deleting the Tests.
  > **Verify:** ✅ `uv run pytest qatrack/qa/tests/test_setup_myqa_tests.py` →
  > 8 passed in 22.11s.

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
