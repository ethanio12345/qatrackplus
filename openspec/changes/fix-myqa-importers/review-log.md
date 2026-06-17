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

### Status (end of Round 1)
- Frozen artifacts: **none**
- Round 1 blockers: 6 cross-cutting (see above)

---

## Round 1 follow-up — 2026-06-17 (after schema dump + setup reconcile)

**Trigger:** Production schema dump transcribed into `schema-reference.md`; 5
follow-up queries (Step 5) answered; `setup_myqa_tests.py` re-read against
verified schema. New `explore-brief.md` written with mapping tables.

### 🔴 Resolved (no longer outstanding)
- **`MQA_TestConditions` confirmed NOT to exist.** Round 1 issue #2 closed. The
  design's "TABLE MISSING" diagnosis was correct.
- **Numeric tolerance columns confirmed `WarnOn`/`FailOn`** (not
  `WarningTolerance`/`ErrorTolerance`). Round 1 design issue closed.
- **MLC FK confirmed `MlcQATestExecutionBase_Id` → `MQA_MDL_MlcQA_TestExecutions.Id`
  → TIE.** Neither current code (`MlcQAQueueItemExecution_Id`) nor the proposed
  spec (direct to TIE) matched; both were wrong. Round 1 specs/mlc R2 issue closed.
- **WinstonLutz columns confirmed** (`MaximumDeviation2D`, `Deviation3D`,
  `Tolerance_Warn`, `Tolerance_Fail`). 2 metrics are exhaustive (direct columns,
  not denormalized).
- **4 missing importer tables discovered** (PassFail, VMAT, CBCT, Planar) with
  full column lists. Round 1 cross-cutting #1 has the raw material to close.
- **VMAT measured-value gap closed** — `RoiMean`/`RoiStandardDeviation` live in
  child table `MQA_MDL_VmatDmlc_RoiResults` linked via `VmatDmlcResult_Id`.
- **Task-name pattern issue closed** — `.D` (Constancy) and `.D2` (Physics) both
  carry Numeric data; `.D%` cannot distinguish them.

### 🔴 New findings (worse than Round 1 thought)
- **`setup_myqa_tests.py:77-87` is triple-broken, not just incomplete.** The
  Numeric setup query references a non-existent table (`MQA_TestConditions`),
  non-existent columns (`tcne.WarningTolerance`/`ErrorTolerance`), and
  non-existent FK columns (`tcne.TestCondition_Id`,
  `tcne.TestImplementationExecution_Id`). Real columns: `tcne.WarnOn`/`FailOn`,
  `tcne.NumericTestExecution_Id`, `tcne.Name` (direct). Plus
  `setup_myqa_tests.py:148-150` explicitly SKIPs all non-Numeric types.
  Conclusion: setup needs a **rewrite** + new per-type code paths, not the
  proposal's "extend". (Decision D2 in explore-brief.)
- **VMAT is Pattern C (child-table fan-out), not Pattern B (wide-row).** The
  Round 1 assumption that all denormalized types share one pattern was wrong.
  VMAT design must iterate ROI child rows. (Decision in explore-brief mapping.)
- **`.D%` filter breadth.** `5.Tmt.Linac.D%` matches both Constancy (`.D`) and
  Physics (`.D2`). The schema-reference.md previously claimed `.` is a wildcard
  in LIKE — **corrected**: `.` is literal; `%` swallows the `2 - Daily QA
  (Physics)` suffix. Either way, `.D%` cannot split the two task types.

### 🟡 Decisions taken (documented in explore-brief.md, reversible via unfreeze)
- **D1 — Numeric split** into existing `myqa_daily_constancy` (`.D`) and
  `myqa_daily_physics` (`.D2`). `myqa_numeric` slug deleted. Resolves Round 1
  cross-cutting #4.
- **D2 — Setup rewrite**, not extend.
- **D3 — PassFail stores `AcceptanceCriteria` text** (no `PassStatus` column).
- **D4 — Read `*_Verdict` directly** (encoding 0/10/30/40/50/60).

### 🟡 Still outstanding (must be resolved during Round 2 batched revision)
- Proposal "Files Affected" still says "extend setup"; needs rewrite per D2.
- design.md Numeric query still in bulk form; needs per-`execution_id` rewrite.
- 4 missing specs (PassFail/VMAT/CBCT/Planar) not yet written.
- tasks.md: Phase 2/3 backfills still depend on Phase 5 setup; TBD columns
  (`...`) in Task 3.2; Task 5.1 still >2h bundled; no test tasks.
- Open questions in explore-brief.md (MLC tolerance-only columns, CBCT/Planar
  non-conforming columns, VMAT slugification, `IsDeleted` filter).

### Status (end of Round 1 follow-up)
- Frozen artifacts: **none**.
- Baseline artifacts now in place: `schema-reference.md` (verified schema),
  `explore-brief.md` (mapping tables + decisions D1–D4).
- Next action: Round 2 — revise `proposal.md` to reflect D1–D4 and the
  setup-rewrite reality, then send to `@openspec-reviewer` for the proposal
  batch freeze decision.

---

## proposal Round 2 — 2026-06-17 (Batch 1 of 4)

**Reviewer:** `@openspec-reviewer`
**Newly created this round:** `proposal.md` (revised per explore-brief
commitments D1–D4, four patterns, seven per-type scope rows, six deferred open
questions).
**Already frozen:** none (first batch of Round 2).
**Baseline:** `explore-brief.md`, `schema-reference.md`.
**Verdict:** **PASS — frozen** (no 🔴 blockers; three 🟡 accuracy fixes applied
pre-freeze).

### ✅ Confirmed resolved (from Round 1)
- Scope/spec mismatch (7 importers, 3 specs) → resolved via the in-scope table
  (`proposal.md:70-80`) + deferral of the 4 missing specs to the specs batch.
- `myqa_numeric` slug conflict → resolved via D1.

### 🟡 Fixed (pre-freeze, per reviewer)
- **D1 expanded from 2-way to 3-way split.** `5.Tmt.DXR.D` was wrongly mapped to
  `myqa_daily_constancy` (a Linac-only list, units 1–8); the frozen main spec
  (`openspec/specs/myqa-sync/spec.md:30`) defines `myqa_dxr_daily` for DXR
  (unit 50). D1 now reads: Linac.D → `myqa_daily_constancy`, Linac.D2 →
  `myqa_daily_physics`, DXR.D → `myqa_dxr_daily`. `explore-brief.md` updated to
  match (D1 + Numeric mapping table).
- **Energy/Wedge/Output "Working" claim softened** to "Out of scope — not
  re-verified" — their QueueItem/Chamber tables aren't in `schema-reference.md`,
  so "Working" was an unverified assertion.
- **Non-goals: data cleanup statement added.** Broken setup never created the
  `myqa_numeric` TestList, so `myqa_import.py:174` `TestList.objects.get(...)`
  would have raised `DoesNotExist`; no TestListInstance/TestInstance data is
  expected. Flagged "verify in production before `--force`".

### 🟢 Reviewer strengths noted
- All 7 Background bullets verified schema-accurate against `schema-reference.md`
  and `setup_myqa_tests.py`.
- Clean WHAT/HOW separation — no SQL, METRICS dict contents, or per-column
  mappings leaked into the proposal (all correctly deferred to design/specs).
- D2 "rewrite, not extend" correctly reflected in Decisions + Files Affected.
- Pattern labels (A/B/C/D) in scope table match `explore-brief.md` exactly,
  including VMAT as Pattern C.

### Commitment coverage
- 20/21 explore-brief items fully captured in the as-reviewed proposal.
- 21st item (D1 DXR.D reconciliation) captured via the 🟡 #1 pre-freeze fix.
- No silent omissions.

### Status (end of proposal Round 2)
- **`proposal.md`: FROZEN.**
- Frozen artifacts: `proposal.md`.
- Next action: Round 2, batch 2 — revise `design.md` (per-`execution_id` query
  shape, per-type `METRICS` dicts including VMAT child-table fan-out, per-type
  setup rewrite strategy, `--force` safety note), then `@openspec-reviewer`.

---

## design Round 1 — 2026-06-17 (Batch 2 of 4, Round 1)

**Reviewer:** `@openspec-reviewer`
**Newly created:** `design.md` (revised per explore-brief + frozen proposal).
**Already frozen:** `proposal.md`.
**Verdict:** **NEEDS REVISION** — three 🔴 blockers (the silent-failure mode
this change exists to prevent).

### 🔴 Outstanding (Round 1)
- **S1 — `execution_id` UUID mismatch.** Engine's `query_new_sessions` selects
  `te.TaskExecutionId` (`myqa_import.py:127`) and `import_session` passes it as
  `execution_id` (`myqa_import.py:163`). Every design query filtered on
  type-table `Id` directly via the `tie.Id = te.Id` chain, NOT on
  `te.TaskExecutionId`. Would return zero rows — exact failure mode of
  `full-myqa-sync`.
- **S2 — D4 verdict storage unimplementable.** Engine iterates `results.items()`
  as `{slug: val}` (`myqa_import.py:206`) and hardcodes `pass_fail='no_tol'`
  (`myqa_import.py:226`). Design claimed `extract_results` returns tuples and
  that D4 stores verdicts — both wrong.
- **S3 — Tolerance creation in Numeric import path.** Per-row processing listed
  `get_or_create_tolerance(...)` as an import-time output. Tolerances are
  setup-only; `import_session` doesn't process them.

### 🟡 Outstanding (Round 1)
- M1 `--force` safety argument wrong for D1 lists (main-spec lists at risk).
- M2 task_name_patterns not specified for 6 of 9 importers.
- M3 WL verdict claim contradicts engine `no_tol` hardcode.
- M4 `import_myqa_results` default + django-q schedule migration not addressed.
- M5 Numeric `Expected` selected but fate unspecified.
- M6 VMAT ROI slug example inaccurate (`slugify_name` preserves periods).
- M7 MLC METRICS dict schema doesn't fit edge-case columns.
- M8 Setup creates UTCs for all units regardless of D1 unit scoping.

### Bonus findings from source read
- Existing MLC/CBCT/Planar/VMAT importers JOIN through `*_QueueItemExecutions`
  tables NOT in the verified schema — confirms why they're broken (wrong JOIN
  path, separate from the wrong-column issue).
- Existing WL importer reads `DisplayName`/`Actual` — non-existent on
  `MQA_IsoCheck_WinstonLutz_TestExecutions` per verified schema.
- Existing PassFail reads `pfte.PassStatus` + `tc.Name` via `MQA_TestConditions`
  — both non-existent.

---

## design Round 2 — 2026-06-17 (Batch 2 of 4, Round 2)

**Reviewer:** `@openspec-reviewer`
**Newly revised:** `design.md` (comprehensive rewrite addressing S1/S2/S3 +
M1–M8). Also D4 soft-freeze amendments to `proposal.md` and `explore-brief.md`.
**Verdict:** **PASS — frozen.** No 🔴, no new issues, schema accuracy preserved.

### 🔴 Round 1 blockers — all RESOLVED
- **S1 RESOLVED.** Every `extract_results` query now JOINs through `te` and
  filters `WHERE te.TaskExecutionId = %s` (Numeric, WL, MLC, CBCT, Planar, VMAT
  parent, VMAT child, PassFail — all 8 verified at cited line numbers).
- **S2 RESOLVED.** `Dict[str, Any]` contract documented; D4 softened to
  "verdict read for logging, storage deferred" (proposal soft-freeze amendment).
- **S3 RESOLVED.** Numeric import query SELECTs only `Name, Actual`; no
  tolerance in import path. Tolerance columns read during setup only.

### 🟡 Round 1 should-fix — all RESOLVED (M1–M8)
- M1 `--force` per-list risk table calling out main-spec daily lists.
- M2 task_name_patterns populated for all 9 importers (PassFail marked
  "confirm from source" — acceptable).
- M3 WL verdict claim acknowledges `no_tol`.
- M4 `import_myqa_results` default + django-q schedule migration noted.
- M5 Numeric `Expected` removed from import SELECT.
- M6 VMAT ROI slug rule notes `slugify_name` preserves periods.
- M7 MLC METRICS has `STRING_COLS` mechanism for non-conforming entries.
- M8 Setup UTC applies per-list unit scoping (`UNITS_PER_LIST`).

### 🟡 Pre-freeze soft-freeze amendments (this round)
- VMAT parent extract query trimmed to value-only; tolerance columns annotated
  as setup-only.
- `import_myqa_results` default committed to `numeric_constancy` (no aggregate
  key — would require engine fan-out outside Non-goal).
- `proposal.md:83` "2 existing lists" → "3 existing lists (constancy/physics/
  dxr)" (declarative fix to match D1).
- `std dev` prose made consistent across `design.md`.

### 🟢 Reviewer-noted strengths
- Engine contract section ties query shape, return type, verdict handling to
  specific engine code locations — exemplary "why" documentation.
- Existing-importer breakage diagnosis gives implementer a clear "what to
  delete" list.
- METRICS dict schema is regular and transcribable; per-type counts match brief.
- All 6 open questions (O1–O6) closed with concrete dispositions.
- Backfill plan establishes setup-before-import per type (pre-empts the
  Round 1 tasks.md dependency-order critique).

### Deferred to specs batch (natural home)
- NULL handling for `Actual` / `AcceptanceCriteria` (edge-case scenarios).
- Per-type pass/fail behavior given D4 verdict storage is deferred.

### Status (end of design Round 2)
- **`design.md`: FROZEN.**
- Frozen artifacts: `proposal.md`, `design.md`.
- Next action: Round 2, batch 3 — write the 4 missing per-type specs
  (passfail, vmat, cbct, planar) + add edge-case scenarios to all 7; then
  `@openspec-reviewer`.
