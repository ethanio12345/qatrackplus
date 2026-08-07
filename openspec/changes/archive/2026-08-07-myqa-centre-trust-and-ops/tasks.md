## 1. `myqa_validate` command

- [x] 1.1 Create `qatrack/qa/management/commands/myqa_validate.py` with `BaseCommand` skeleton, args `--days` (default 30), `--task-name` (limit to one TaskName), `--unit` (limit to one unit number), `--json` (machine-readable output), `--summary-only` (skip per-condition check for speed)
- [x] 1.2 Implement `_query_myqa_sessions(conn, taskname, days, unit_number)`: reuse `qatrack.myqa_import.query_sessions`, filter to the requested unit
- [x] 1.3 Implement `_categorise_unimported(conn, taskname, sessions_not_imported, multi_flags)`: for each session not in QATrack+, call `extract_all_types`; if all values None → `"valueless_skip"`, else → `"genuine_drop"`
- [x] 1.4 Implement `_compare_session_fidelity(conn, taskname, exec_id, tli, multi_flags)`: call `extract_all_types` against myQA, read TIs from the TLI, return dict of `{conditions_match: bool, value_mismatches: [...], tolerance_diffs: [...]}`
- [x] 1.5 Implement `_format_human_report(results)`: print per-TestList block (sessions, conditions, mismatches with myQA/QATrack+ pairs), then summary line
- [x] 1.6 Implement `_format_json_report(results)`: emit the structured JSON object described in design D2
- [x] 1.7 Implement `--summary-only` mode: skip step 1.4 (no per-condition comparison), report counts only
- [x] 1.8 Verify: run against BCHC DB + myQA for the last 30 days; sanity-check the report (Daily Constancy Check for RFT26 should show 14/14 sessions imported, 73/73 conditions, 0 value mismatches)
- [x] 1.9 Verify: run with `--json` and pipe to `python -m json.tool` to confirm valid JSON

## 2. `docs/myqa_deployment_guide.md`

- [x] 2.1 Create the guide with the 11-section structure from design D5 (Prereqs → Configure → Validate Pre → Bootstrap → First Import → Tolerance Review → Validate Post → Schedule → Operate → Customise → Troubleshoot)
- [x] 2.2 Section 6 (Tolerance Review): use markdown blockquote-callout style (`> **STOP.** ...`) for the prominent warning; explain that myQA's WarnOn/FailOn become QATrack+ tolerances verbatim and may not match the centre's clinical protocols
- [x] 2.3 Section 7 (Validate Post): walk through reading a `myqa_validate` report, including "valueless_skip = OK" and "genuine_drop = investigate"
- [x] 2.4 Section 9 (Operate): table of monthly/quarterly/annual maintenance commands with cadence
- [x] 2.5 Section 11 (Troubleshoot): cover the four silent-failure modes — valueless sessions, unmapped devices, slug collisions, missing TestLists — with symptoms and fixes
- [x] 2.6 Verify: walk through the guide end-to-end against a clean test SQLite DB; every command should be runnable and produce sensible output

## 3. `docs/myqa_operational_scripts.md`

- [x] 3.1 Create the reference doc covering all 7 maintenance scripts (`clear_myqa_data`, `clear_stale_due_dates`, `set_angular_wraparound`, `auto_approve_tlis`, `approve_myqa_taskids`, `delete_empty_tlis`, `myqa_validate`)
- [x] 3.2 For each script document: Purpose, When to run, What it does (algorithm sketch), Idempotency, Sample output, BCHC operational note
- [x] 3.3 Verify: cross-check command signatures against actual `add_arguments()` implementations (no drift)

## 4. `AGENTS.md` cross-link

- [x] 4.1 Add a "Sharing with another centre" section to `AGENTS.md` after the "Production deployment" section
- [x] 4.2 Content: name the three-change portability programme, point at `docs/myqa_deployment_guide.md`, list the three centre-config files with one-line descriptions, note the latent UnitType bug fix shipped in Change A
- [x] 4.3 Verify: markdown renders cleanly; cross-links to the new docs work

## 5. `bootstrap_myqa_centre` banner update (cross-change)

- [x] 5.1 In `qatrack/qa/management/commands/bootstrap_myqa_centre.py:_print_tolerance_warning` (added in Change B), add a line suggesting the centre run `myqa_validate --days 30` after their first `import_myqa` to diff QATrack+ against myQA
- [x] 5.2 Verify: re-run `bootstrap_myqa_centre --apply` against a test fixture; confirm the banner now includes the `myqa_validate` suggestion

## 6. Tests

- [x] 6.1 Create `qatrack/qa/tests/test_validate.py` with five tests: (a) `test_all_match` — mocked myQA returns sessions+conditions that exactly match fixture QATrack+ TLIs; status `pass`; (b) `test_session_count_mismatch` — mocked myQA returns 5 sessions, QATrack+ has 3 TLIs; status `needs_review`, missing=2; (c) `test_condition_count_mismatch` — mocked myQA returns 10 conditions, QATrack+ TLI has 8 TIs; reports 2 missing condition names; (d) `test_value_mismatch` — myQA Actual=1.234, QATrack+ TI.value=1.235; reports mismatch; (e) `test_valueless_vs_genuine_drop` — 2 unimported sessions, one all-None (valueless_skip), one with values (genuine_drop); distinguished correctly in output
- [x] 6.2 Add `test_json_output_structure` — verify `--json` emits the expected schema (summary, testlists array, status enum)

## 7. Regression + lint

- [x] 7.1 Run `uv run ruff check .` — no new errors
- [x] 7.2 Run `uv run black --target-version py312 .` — all formatted
- [x] 7.3 Run `uv run python manage.py check` — no system check issues
- [x] 7.4 Run `uv run pytest -x -m "not selenium" qatrack/qa/tests/` — all pass (currently 403 + ~10 from Change A + ~10 from Change B + ~6 from this change)
- [x] 7.5 End-to-end smoke: run `myqa_validate --days 7 --json` against BCHC DB; confirm JSON parses, summary is sensible
