# Review Log: full-myqa-sync

## proposal Round 1 — 2026-06-17 (retroactive)

First review of all artifacts (proposal, design, specs, tasks) together. No
artifacts were frozen; no `explore-brief.md` existed yet. Review run by
`@openspec-reviewer` with codebase grounding from a parallel `explore` agent.

### 🔴 Found (serious, blocking `/opsx-apply`)
- Main-spec-vs-delta inversion: `openspec/specs/myqa-sync/spec.md` described the
  full proposed feature as current behavior
- Unit count 7 vs 8 inconsistent across artifacts
- De-dup key had 3 different names (`mtx_taskid` / `myqa_{list_slug}_taskid`)
- Slug regex kept dots, contradicting the spec scenario
- Tolerance mapper stored one band using WarnOn XOR FailOn; wrong field names
  (`tol_lower/tol_upper` vs actual `tol_low/tol_high`)
- Fabricated `MyqaSessionCollector` class (real class is `MatrixResultImporter`)
- myQA library stated/implied as `pyodbc` (actual: `pymssql`)
- 8 of 11 myQA detail tables unverified against codebase
- Task 1 was ~5–10× the 2-hour budget (base + 11 handlers bundled)
- Missing tasks: unit tests, normalization registry, #133 data migration,
  tolerance validation, command docs
- No design-level SQL / column mapping for the 11 detail tables
- Missing `explore-brief.md`; no prior review rounds logged

### Resolution
Maintainer answered blocking questions on 2026-06-17 (linac count + myQA tables
trusted from production; tolerance = warn→tol / fail→act; pymssql confirmed;
all design defaults B1–B8 confirmed). All artifacts rewritten; `explore-brief.md`
authored as the binding decision baseline.

## all-artifacts Round 2 — 2026-06-17

Full re-review of every artifact after Round-1 revisions. `explore-brief.md`
treated as binding baseline; all model facts re-verified against source
(`matrix_import.py`, `qa/models.py`).

### 🔴 Outstanding
None. All 13 Round-1 serious findings verified RESOLVED.

### 🟡 Fixed this round (documentation corrections, no decision changes)
- `design.md` slug-collision cross-reference: `Task 2` → `Task 6`
- `explore-brief.md` cross-module flow: clarified `import_myqa()` is the
  management command (Task 7), not a `tasks.py` function
- `design.md` illustrative SQL: `te.Id` → `te.TaskExecutionId`
- `tasks.md` Task 4 & Task 6: added ≤2h split guidance (apply-time split allowed)
- `tasks.md` Task 7: documented why `--days` default (30) differs from cron (2)
- `spec.md` Numeric scenario: added Output execution as covered case
- `spec.md` PassFail scenario: clarified value stored verbatim in `string_value`

### 🟢 Deferred (non-blocking polish)
- Per-execution-type detail-table column→slug mapping deferred to apply time
  (per maintainer decision D10: myQA schema trusted from production)

### Cross-consistency checks (all PASS)
Tolerance signs/bands/None identical across brief+design+spec; 19 TestLists
consistent (no artifact says 20); 11 handler classes match across
brief/design/tasks/spec; `--days 2` incremental consistent; 18:00 Sydney + DST
consistent; every task has a Verification step; #133 MODIFIED requirement ↔
Task 9 (no false data-migration claim); de-dup story end-to-end coherent;
field names `tol_low/tol_high/act_low/act_high` verified against
`qa/models.py:688-711`.

### Verdict
**READY TO FREEZE.** Zero 🔴. Batch (explore-brief, proposal, design, delta spec,
tasks, main spec) frozen as of this round.
