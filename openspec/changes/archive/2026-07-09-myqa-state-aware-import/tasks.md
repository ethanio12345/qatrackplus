## 1. State-aware extraction

- [x] 1.1 Add `MYQA_STATE_MAP` constant: `{10: "skip", 30: "unreviewed", 40: "unreviewed", 50: "unreviewed", 60: "skipped"}`
- [x] 1.2 Rewrite `extract_numeric` to filter out State=10 conditions and return `{"value": ..., "state": int}` dicts instead of bare values
- [x] 1.3 Rewrite `extract_passfail` to return ALL PassFail tests per session (not just `fetchone()`), keyed by TestExecution Name, each with `{"value": criteria, "state": int}`. Filter out State=10.
- [x] 1.4 Update `extract_all_types` to merge state-aware results. Non-Numeric/PassFail extractors (Profile, Wedge, etc.) wrap their values as `{"value": val, "state": 40}` (default completed state since these are automated measurements).
- [x] 1.5 Update `import_session` to read the new `{name: {"value", "state"}}` format and apply the state mapping: skip State=10, use `Unreviewed` for 30/40/50, use `Skipped` for 60.

## 2. PassFail discovery + setup

- [x] 2.1 Add `discover_passfail_conditions(conn, taskname)` that returns per-test PassFail condition names (from TestExecution Names), replacing the single "Acceptance Criteria" approach.
- [x] 2.2 Update `discover_conditions` to call `discover_passfail_conditions` instead of `has_passfail_data`. Each PassFail condition is `{"name": test_name, "type": "string", "source": "PassFail"}`.
- [x] 2.3 Remove `has_passfail_data` (no longer needed).
- [x] 2.4 Update `setup_myqa_tests` to create Tests/UTIs for the new per-test PassFail conditions.

## 3. Skipped status

- [x] 3.1 Add `ensure_statuses_exist()` function to `myqa_import.py` that creates the `Skipped` TestInstanceStatus (slug=`skipped`, valid=False, requires_review=False, export_by_default=False). Idempotent.
- [x] 3.2 Call `ensure_statuses_exist()` from `setup_myqa_tests.handle()` alongside `ensure_frequencies_exist()`.

## 4. Rebuild + verify

- [x] 4.1 Run `clear_myqa_data --yes` to wipe all myQA Tests/TestLists (old PassFail "Acceptance Criteria" tests will be removed).
- [x] 4.2 Run `setup_myqa_tests` to rebuild with new per-test PassFail conditions.
- [x] 4.3 Run `import_myqa --days 30` and verify: no State=10 empties, Skipped status appears, multiple PassFail tests per session.
- [x] 4.4 Verify TLI 153187 equivalent session now has all 10 PassFail tests instead of 1.

## 5. Final checks

- [x] 5.1 Run `uv run ruff check` and `uv run black --target-version py312` on all modified files.
- [x] 5.2 Run `uv run python manage.py check`.
- [x] 5.3 Update AGENTS.md with state-aware import notes.
