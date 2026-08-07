## Why

The first two changes in the portability programme (`myqa-centre-config-externalisation`, `myqa-centre-onboarding`) make the system **installable** at another hospital. They don't make it **trustworthy** there. Two gaps remain:

1. **The validation gap.** A new centre's first import is "trust me bro" — no reference to compare against. The engine's main failure mode is silence: valueless sessions are skipped, unmapped devices are dropped, slug collisions cause missing conditions, all without error. BCHC's import was validated over months of production use; Centre B doesn't have that runway. Without a way to diff QATrack+ against myQA, the centre is flying blind.

2. **The documentation gap.** Even with `bootstrap_myqa_centre` and `myqa_doctor`, a centre needs to know what to do after the import, when to run the operational scripts (`clear_stale_due_dates`, `set_angular_wraparound`, `auto_approve_tlis`, `delete_empty_tlis`, `approve_myqa_taskids`), how to interpret the silent-skip behaviours, and — most importantly — that **tolerances must be reviewed before clinical use**. There is no `docs/myqa_deployment_guide.md`. The `AGENTS.md` is developer-facing and BCHC-specific.

This change closes both gaps: a `myqa_validate` command provides the diff layer, and a deployment guide documents the full lifecycle from clone to confident clinical use. Both are useful to BCHC too — `myqa_validate` is a first-class operational tool that should run after every big import, not just at onboarding.

This is the third and final change in the myQA centre-portability programme. It depends on both prior changes for the config schema and bootstrap workflow.

## What Changes

- **NEW** `qatrack/qa/management/commands/myqa_validate.py` — read-only diff command comparing QATrack+ state to myQA for a given window. For each TestList+unit combo in scope:
  - Count mismatch: myQA sessions vs QATrack+ TLIs (uses the `_taskid` TestInstance dedup keys already stored).
  - Per-session condition-count mismatch: myQA conditions present vs QATrack+ TIs created.
  - Per-condition value mismatch: myQA Actual vs QATrack+ TI value (within rounding).
  - Per-condition tolerance mismatch: myQA WarnOn/FailOn vs the QATrack+ UTI's tolerance.
  - Categorise "missing" TLIs as either valueless-skip (myQA had no values — OK) or genuine-drop (myQA had values, no TLI — bug).
  - Output: human-readable report (default) or JSON (`--json`).
- **NEW** `docs/myqa_deployment_guide.md` — step-by-step guide for a new centre from `git clone` to confident clinical use. Sections: prerequisites, configure, validate (doctor), bootstrap, first import, schedule registration, tolerance review (LOUD), operating over time (cadence of `clear_stale_due_dates`, `set_angular_wraparound`, etc.), troubleshooting, customising further (name overrides, centre config, angular patterns).
- **NEW** `docs/myqa_operational_scripts.md` — reference for the Layer 4 operational scripts: what each does, when to run it, expected output, idempotency notes. Covers `clear_myqa_data`, `clear_stale_due_dates`, `set_angular_wraparound`, `auto_approve_tlis`, `approve_myqa_taskids`, `delete_empty_tlis`. Both new-centre and BCHC operational use cases documented.
- **MODIFIED** `AGENTS.md` — add a "Sharing with another centre" section pointing at the deployment guide, summarising the three-change portability programme, and listing the three centre-config files (`myqa_device_map.yaml`, `myqa_centre_config.yaml`, `myqa_name_overrides.yaml`).
- **MODIFIED** `qatrack/qa/management/commands/bootstrap_myqa_centre.py` (from Change B) — `--apply` finishes by suggesting the centre run `myqa_validate --days 30` once they've done their first `import_myqa`. (Cross-reference; this is a one-line touch in the printed banner, not a code-path dependency.)

## Capabilities

### New Capabilities
- `myqa-validation-diff`: A read-only management command (`myqa_validate`) that diffs QATrack+ state against myQA for a given TaskName/window, reporting session-count mismatches, condition-count mismatches, value mismatches, and tolerance mismatches. Categorises missing TLIs as valueless-skip vs genuine-drop. Useful both at onboarding (centre's first trust-building step) and operationally (BCHC running it after every big import to catch silent drops).
- `myqa-deployment-documentation`: A step-by-step deployment guide (`docs/myqa_deployment_guide.md`) covering clone → configure → validate → bootstrap → first import → schedule registration → tolerance review → ongoing operation. Plus a companion reference (`docs/myqa_operational_scripts.md`) for the Layer 4 maintenance commands. Closes the documentation gap for inter-hospital sharing.

### Modified Capabilities
- `myqa-sync`: The deployment guide documents the full scheduling lifecycle — daily import (Schedule #7), weekly setup (Schedule "myQA Weekly Setup"), monthly PDF archives (Schedules #9, #10) — and how a centre adjusts the cron strings for their timezone.

## Impact

- **Files added (3):** `qatrack/qa/management/commands/myqa_validate.py`, `docs/myqa_deployment_guide.md`, `docs/myqa_operational_scripts.md`.
- **Files modified (2):** `AGENTS.md` (new "Sharing with another centre" section), `qatrack/qa/management/commands/bootstrap_myqa_centre.py` (one-line banner update referencing `myqa_validate`).
- **Tests added (~5):**
  - `test_validate.py`: (a) all-match happy path; (b) session-count mismatch detected; (c) condition-count mismatch detected; (d) value mismatch detected; (e) valueless-skip distinguished from genuine-drop.
- **Database:** none. `myqa_validate` is strictly read-only (SELECTs against myQA, ORM reads against QATrack+).
- **Dependencies:** none.
- **Clinical safety:** positive. `myqa_validate` surfaces silent failure modes; deployment guide emphasises tolerance review. This change is the trust layer.
- **Backwards compatibility:** 100%. New additive command + docs; no existing behaviour changed.

## Non-goals

- Tolerance auto-configuration or correction — out of scope (decision: document loudly, ship anyway).
- Web UI for validation reports — out of scope; CLI + JSON output is sufficient for the inter-hospital use case.
- Localising the deployment guide — English only for v1.
- Migrating BCHC's existing operational runbook to the new docs — BCHC keeps using `AGENTS.md` for developer context; the new docs target other centres.
- Archiving the legacy `qatrack/matrix_import_old.py` — out of scope (already deprecated).
