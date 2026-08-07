# Design: myqa-centre-trust-and-ops

## Context

After `myqa-centre-config-externalisation` (config portability) and `myqa-centre-onboarding` (bootstrap UX), the system is installable at another hospital. But "installed" is not "trusted." This change closes the trust gap with two artefacts:

1. A **diff command** (`myqa_validate`) that lets a centre compare QATrack+ state to myQA, surfacing the silent failures that are the engine's main risk.
2. A **deployment guide** that walks a centre from `git clone` to confident clinical use, with the tolerance-review warning delivered loudly at the moment of action.

Both artefacts are useful to BCHC operationally — `myqa_validate` is the missing observation layer for a system whose main failure mode is silence, and the operational scripts reference documents BCHC's existing maintenance cadence.

## Goals

1. A centre can answer "did the import capture all my data correctly?" with a single command.
2. A centre can deploy from `git clone` to clinical use by following one document.
3. The tolerance-review warning is delivered at-action-time (in the bootstrap banner, in the deployment guide, in the import command output) — defence in depth, not just a buried docs page.
4. BCHC gets operational value too (`myqa_validate` should run after every big import).

## Non-goals

- Automatic tolerance correction.
- Web UI for validation.
- Migration of BCHC's existing operational runbook.
- Localization.

## Design decisions

### D1: `myqa_validate` reuses engine SQL, doesn't reimplement

The engine already has all the SQL needed to inspect myQA. `myqa_validate` calls back into `qatrack.myqa_import`:

```
   For each (TaskName, unit) in scope:
   
   ┌─ Sessions expected ──────────────────────────────────┐
   │  query_sessions(conn, taskname, days)                │
   │  → list of {task_execution_id, unit_number, ...}     │
   │  Filter to those whose device maps to the unit.      │
   └──────────────────────────────────────────────────────┘
                          │
                          ▼
   ┌─ Sessions imported ──────────────────────────────────┐
   │  duplicate_check(taskname, exec_id, unit)            │
   │  → bool per session                                  │
   │  (existing helper — looks up the _taskid TI)         │
   └──────────────────────────────────────────────────────┘
                          │
                          ▼
   ┌─ Per-session fidelity ───────────────────────────────┐
   │  For each session that's "imported":                 │
   │    extract_all_types(conn, exec_id, multi_flags)     │
   │    → dict of {condition: {value, expected, ...}}     │
   │    Compare to QATrack+ TIs for that TLI.             │
   │    Report:                                           │
   │      - condition count match?                        │
   │      - per-condition value match (within rounding)?  │
   │      - tolerance match?                              │
   └──────────────────────────────────────────────────────┘
                          │
                          ▼
   ┌─ Categorise unimported sessions ─────────────────────┐
   │  For each session NOT imported:                      │
   │    extract_all_types(...)                            │
   │    If all values are None → valueless-skip (OK)      │
   │    Else → genuine-drop (BUG — investigate)           │
   └──────────────────────────────────────────────────────┘
```

This means the validate command stays in sync with the engine for free — if the engine's extractors are updated, validate automatically uses the new versions.

### D2: Output format — human by default, JSON on flag

```
$ uv run python manage.py myqa_validate --days 30

Validating last 30 days against myQA at 10.59.35.17...
─────────────────────────────────────────────────────────────
Daily Constancy Check  (unit 437, RFT26)
  Sessions: myQA 14  ↔  QATrack+ 14   ✓
  Conditions: myQA 73  ↔  QATrack+ 73   ✓
  Value mismatches: 0   ✓
  Tolerance diffs: 2   ⚠
    Output 6x:        myQA warn=±2%   QATrack+ warn=±1.5%
    Flatness 6x:      myQA warn=±2%   QATrack+ warn=±2%   (rounding)

5.Tmt.Linac.Monthly - MLC  (unit 437)
  Sessions: myQA 15  ↔  QATrack+ 4   ⚠
    11 unimported sessions:
      11 valueless-skip (myQA had no values — OK)
      0 genuine-drops (would indicate a bug)

─────────────────────────────────────────────────────────────
Summary: 47/48 TestLists pass validation.
1 needs review (see above).
```

`--json` emits a structured object for CI:

```json
{
  "window_days": 30,
  "summary": {"pass": 47, "needs_review": 1, "fail": 0},
  "testlists": [
    {
      "taskname": "Daily Constancy Check",
      "unit_number": 437,
      "unit_name": "RFT26 - H197686",
      "status": "needs_review",
      "sessions": {"myqa": 14, "qatrack": 14, "missing": 0, "valueless_skip": 0, "genuine_drop": 0},
      "conditions": {"myqa": 73, "qatrack": 73, "missing": []},
      "value_mismatches": [],
      "tolerance_diffs": [
        {"condition": "Output 6x", "myqa_warn": 2.0, "qatrack_warn": 1.5}
      ]
    },
    ...
  ]
}
```

### D3: Value-match tolerance

When comparing myQA `Actual` to QATrack+ `TI.value`, we accept a match if the values are equal within 4 decimal places (the engine's `_result()` rounding precision). This avoids reporting spurious mismatches from float representation.

Tolerance mismatches use the same rounding but always report (they're informational, not "the engine is broken").

### D4: Don't try to fix what validate finds

The decision (from exploration): "that's up to the centre to decide." `myqa_validate` reports findings; it doesn't auto-fix them. Centres decide what to do — re-import, adjust tolerances in admin, file a bug, ignore.

The deployment guide describes the common failure modes and their likely fixes, but the command itself is read-only.

### D5: Deployment guide structure — the "moment of action" pattern

The guide is structured around the moments where decisions happen, not around features:

```
   1. PREREQUISITES         "Before you touch anything"
   2. CONFIGURE             "Wire up your myQA"
   3. VALIDATE PRE          "myqa_doctor — confirm foundations"
   4. BOOTSTRAP             "bootstrap_myqa_centre — build the device map"
   5. FIRST IMPORT          "import_myqa --days 90 — pull historical data"
   6. ★ TOLERANCE REVIEW ★  "STOP. Read this before clinical use."
   7. VALIDATE POST         "myqa_validate --days 90 — does QATrack+ match myQA?"
   8. SCHEDULE              "Set up daily/weekly/monthly automation"
   9. OPERATE               "Ongoing cadence — what to run, when"
   10. CUSTOMISE            "Extending the system for your centre"
   11. TROUBLESHOOT         "Common failure modes and fixes"
```

The tolerance review (step 6) is between brackets in the source markdown so it renders as a prominent callout. The bootstrap banner (from Change B) and the import command's stdout also reference it — defence in depth.

### D6: Operational scripts reference — Layer 4 in scope

`docs/myqa_operational_scripts.md` covers every maintenance command with:
- **Purpose** (one sentence).
- **When to run** (cadence + triggering events).
- **What it does** (algorithm sketch).
- **Idempotency** (safe to re-run?).
- **Sample output**.
- **BCHC operational note** (how BCHC uses it; centres can ignore if not relevant).

Scripts covered:
- `clear_myqa_data` — full reset (destructive, manual only).
- `clear_stale_due_dates` — monthly hygiene (frequency-aware).
- `set_angular_wraparound` — after new angular tests created (idempotent).
- `auto_approve_tlis` — after import with new AutoReviewRuleSet (idempotent).
- `approve_myqa_taskids` — backfills dedup metadata (idempotent).
- `delete_empty_tlis` — purge valueless TLIs (idempotent + careful).
- `myqa_validate` — observation layer (new in this change).

### D7: AGENTS.md cross-link

The top-level `AGENTS.md` (developer-facing) gets a new section "Sharing with another centre" near the bottom that:
- Names the three-change portability programme.
- Points at `docs/myqa_deployment_guide.md` for new-centre onboarding.
- Lists the three centre-config files with one-line descriptions.
- Notes the latent UnitType bug fix shipped in Change A.

This keeps `AGENTS.md` as the authoritative dev reference while pointing other audiences at the right doc.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `myqa_validate` reports false-positive value mismatches due to float precision | Medium | Low (centre wastes time investigating) | 4-decimal rounding; deployment guide explains the threshold. |
| `myqa_validate` perf — iterating all sessions × all conditions is O(N×M) | Medium | Low (centre runs occasionally, not daily) | Default `--days 30`; `--summary-only` flag for fast counts-only mode (skips per-condition check). |
| Deployment guide becomes stale as engine evolves | High (over time) | Medium (centre follows outdated steps) | Guide lives in repo; change proposals that touch the engine update the guide as part of their tasks. |
| Centre ignores the tolerance-review warning | Medium | High (clinical safety) | Defence in depth: banner in bootstrap, banner in import stdout, dedicated guide section, `myqa_validate` flags tolerance diffs. |
| `myqa_validate` itself has a bug and reports "all clear" wrongly | Low | High (false trust) | Test suite covers happy path + each mismatch type; `myqa_validate` reuses engine SQL (so a SQL bug would also affect imports, caught earlier). |

## Test strategy

- Unit tests for `myqa_validate` with mocked myQA connection + fixture QATrack+ DB.
- Five scenarios: all-match, session-count mismatch, condition-count mismatch, value mismatch, valueless-skip vs genuine-drop distinction.
- Integration smoke: run `myqa_validate` against the BCHC DB + myQA; verify it produces a sensible report (matches expected session counts for the last 30 days).
- Docs tested by `openspec validate` (this proposal + deltas must validate).

## Open questions

None. The "what does a centre do with the report" question was explicitly punted to "centre decides" — the command surfaces information, doesn't prescribe action.
