# Review Log — fix-myqa-importers

## Round 1 (comprehensive pre-freeze pass) — 2026-06-17 14:23 AEST

**Reviewer:** `@openspec-reviewer` (deleged critical review)
**Baseline:** No `explore-brief.md` exists; no prior review rounds; nothing
frozen. Review was run against the actual source
(`qatrack/myqa_import.py`, `qatrack/qa/management/commands/setup_myqa_tests.py`)
and the published main spec `openspec/specs/myqa-sync/spec.md`.
**Verdict:** **NOT READY for implementation. Do not freeze any artifact.**

### proposal.md — 🔴 NEEDS REVISION
Outstanding:
- Scope/spec mismatch: proposal says "7 importers" but only 3 spec dirs exist
  (`mlc`, `numeric`, `winston-lutz`). PassFail, VMAT, CBCT, Planar have no spec.
  Either add the 4 missing specs or explicitly descope in a Non-goals section.
- `myqa_numeric` list slug conflicts with the frozen main spec's
  `myqa_daily_physics` / `myqa_daily_constancy`. Must decide: new list, rename,
  or subset — in the proposal, not specs.

### design.md — 🔴 NEEDS REVISION (architectural errors)
Outstanding:
- Numeric "fixed" query is a bulk `WHERE TaskName LIKE` shape, but the engine's
  `extract_results` runs once per `execution_id` (`myqa_import.py:251`). Query
  must be rewritten in per-`execution_id` form.
- `WarnOn`/`FailOn` (proposed) vs `WarningTolerance`/`ErrorTolerance`
  (`setup_myqa_tests.py:78-79`) on the same table — unverified, contradictory.
- `MQA_TestConditions` is labelled "TABLE MISSING" in design.md:33, yet
  `setup_myqa_tests.py:80-82` uses that exact JOIN and the design relies on it
  for backfill. Either setup is also broken (needs rewrite, not extend) or the
  diagnosis is wrong.
- Denormalized `METRICS` dict specified only for MLC, and truncated (`...`).
  CBCT/Planar/VMAT have no design content — no JOIN path, no per-metric
  tolerance-column pattern, no wide-row→N-slugs mapping.
- Setup strategy for denormalized types is conceptually wrong: metric names are
  hardcoded (no `Name` column to `SELECT DISTINCT`), so there is no "discovery
  query" — setup must iterate the same `METRICS` dict.

### specs/ — 🔴 NEEDS REVISION (all three)
`specs/numeric/spec.md`:
- R3 task-name patterns `5.Tmt.Linac.D%` / `5.Tmt.DXR.D%` contradict source
  (`myqa_import.py:246` uses `.N%`) and main spec (`.D2%`). Must be verified.
- Inherits WarnOn/FailOn contradiction.
- `BoundingType` silently dropped — confirm intentional.

`specs/mlc/spec.md`:
- R2 JOIN path invents `MlcQATestExecutionBase_Id` with no schema evidence;
  current code uses `MlcQAQueueItemExecution_Id` → `QueueItemExecutions` table.
- Per-metric tolerance columns under-specified; doesn't state which metrics get
  tolerances vs which are "(simple)".

`specs/winston-lutz/spec.md`:
- Hardcoding 2 metrics may drop data — current code reads `DisplayName`/`Actual`
  dynamically. Confirm `MaximumDeviation2D` + `Deviation3D` are exhaustive.
- Two-sided symmetric tolerance is an unverified assumption (no `LimitTendency`).
- Column names unverified.

All specs: happy-path only. Missing scenarios: NULL tolerance, missing column,
empty result set, slug collision, out-of-range `LimitTendency`.

### tasks.md — 🔴 NEEDS REVISION
Outstanding:
- Dependency order broken: Phase 2/3 backfills depend on Phase 5 setup work;
  responsibilities overlap (WL setup in 2.2 vs 5.1).
- Task 3.2 (VMAT) columns are literally `...` (TBD); Task 4.x (CBCT) lists
  "10+ metrics" with `+` admitting incompleteness.
- Tasks 3.2, 4.1, 4.2, 4.3 have no spec backing.
- Task 4.3 (PassFail) silently changes semantics: stores `AcceptanceCriteria`
  text as string_value, but current code stores `PassStatus` as boolean via the
  same `MQA_TestConditions` JOIN the design calls broken.
- Task 5.1 is >2h bundled across 5 types — split per type.
- No test tasks anywhere; no rollback/idempotency plan.
- Acceptance criteria uneven (no expected row counts from data-volumes table).

### Cross-cutting
1. 🔴 Missing specs for 4 of 7 in-scope importers (PassFail, VMAT, CBCT, Planar).
2. 🔴 `MQA_TestConditions` "missing" diagnosis is self-contradictory — must be
   settled before any freeze.
3. 🔴 Column-name verification absent everywhere. This is the exact failure mode
   that broke the original `full-myqa-sync`. → Action: produce
   `explore-brief.md` from a verified schema dump (see
   `schema-dump-request.md`) before re-proposing.
4. 🔴 `myqa_numeric` vs `myqa_daily_physics` slug/list conflict with main spec.
5. 🟡 No error/edge-case scenarios anywhere.
6. 🟡 No tests, no rollback.

### Path forward (order)
1. Run schema verification per `schema-dump-request.md`; transcribe into a new
   `explore-brief.md`.
2. Re-revise `proposal.md` (per-importer diagnosis, slug decision,
   include/exclude PassFail/VMAT/CBCT/Planar). Freeze.
3. Rewrite `design.md` (per-`execution_id` query shape, verified columns, full
   `METRICS` dicts for all 4 denormalized types, hardcoded-name setup strategy,
   `--force` safety note). Freeze.
4. Add 4 missing specs + edge-case scenarios to all. Freeze.
5. Re-order `tasks.md` (setup-before-backfill per type, fill TBDs, split 5.1,
   add test tasks). Freeze.

### Status
- Frozen artifacts: **none**
- Next action: await schema dump from production, write `explore-brief.md`, then
  begin proposal revision (Round 2 review of `proposal.md`)
