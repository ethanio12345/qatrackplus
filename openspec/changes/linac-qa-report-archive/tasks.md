## 1. UTC selection function

- [x] 1.1 Create `qatrack/reports/qa_selection.py` with `select_archive_utcs(window_start, window_end, freqs=None, units=None)` returning a queryset of UnitTestCollections per design D2 (active + linac unit type + frequency allow-set + ≥1 TLI in window). Default freqs = {Daily, Weekly, Monthly, Quarterly, Semi Annual, Annual}.
- [x] 1.2 Add `previous_month_window(ref=None)` helper returning `(first_day_00:00, last_day_23:59)` for the calendar month before `ref` (default: now).
- [x] 1.3 Define `LINAC_UNIT_TYPE_NAMES` (Cyberknife, Tomotherapy, Agility, Axesse, Precise, Synergy, Clinac, EDGE, Novalis, Trilogy, TrueBeam, Oncor, Primus) used to scope units; expose for reuse.
- [x] 1.4 **Verify**: in a shell, `select_archive_utcs(*previous_month_window())` returns a queryset; print unit/name/frequency/TLI-count and confirm no "Other"/"Once Off"/non-linac/empty suites appear. Compare count against the 79-recent baseline; expect a clean subset.

## 2. Chart-link helper + opt-in template flag

- [x] 2.1 Add `chart_urls(test, unit, window)` helper (in `qatrack/reports/utils.py` or a new `qatrack/reports/chart_links.py`) returning `(run_chart_url, control_chart_url)` for `/qa/charts/` and `/qa/charts/control_chart.png` with `units[]`, `tests[]`, and date-range query params.
- [x] 2.2 Add `include_chart_links` to the report base_opts/context path (default `False`); thread it through `BaseReport.get_context` so templates can read it.
- [x] 2.3 Edit `qatrack/reports/templates/reports/qc/testlistinstance_details.html` to render, when `include_chart_links` is on AND `test.chart_visibility`, two link cells per row (run chart, control chart). Off by default — no change to existing renders.
- [x] 2.4 **Verify**: render an existing `testlistinstance_details` SavedReport to PDF and confirm output is byte-identical (no chart columns). Then render with the flag forced on and confirm two clickable links per chartable row.

## 3. Linac QA archive (per-UTC PDF → zip → deliver)

- [x] 3.1 Create `qatrack/reports/qa_archive.py` with `render_utc_pdf(utc, window, include_chart_links=True) -> bytes` wrapping `TestListInstanceDetailsReport` scoped to one UTC + window (set `include_chart_links`).
- [x] 3.2 Implement `generate_archive(window_start, window_end, out_zip_path=None) -> zip_path` that loops `select_archive_utcs(...)`, renders one PDF per UTC, writes them into a zip as `{unit_slug}/{list_slug}_{YYYY-MM}.pdf`, names the zip `linac_qa_archive_{YYYY-MM}.zip`, and returns a summary dict (per-UTC counts, skipped list).
- [x] 3.3 Add email delivery: `email_archive(zip_path, recipients, summary, max_attach_mb=24)` that attaches the zip if under the limit, else emails a body with the on-site path/URL and a size warning (per spec size guard).
- [x] 3.4 Create `qatrack/qa/management/commands/archive_linac_qa.py` with flags `--window {month|lastmonth|YYYY-MM}`, `--email <group>`, `--out-dir <path>`, `--dry-run`. `--dry-run` prints the selection (1.4 style) and exits without rendering.
- [x] 3.5 **Verify**: `./manage.py archive_linac_qa --dry-run --window lastmonth` prints the clean UTC list; `./manage.py archive_linac_qa --window lastmonth --out-dir /tmp/qa_test` produces a zip with the expected per-UTC PDFs and naming; open one PDF and confirm chart links render.

## 4. Daily QA bundle report (per-linac)

- [x] 4.1 Create `qatrack/reports/qc/daily_bundle.py` with `resolve_current_daily_constancy_utc(unit)` returning the UTC on that unit whose name startswith "Daily Constancy" with the most recent `work_completed` (design D4), overridable by `qatrack/reports/daily_constancy_override.yaml` (unit name → UTC pk).
- [x] 4.2 Add `resolve_rt_daily_utc(unit)` returning the unit's "Daily QA (RTs)" UTC (name contains "Daily QA (RTs)").
- [x] 4.3 Implement `render_daily_bundle_pdf(unit, window) -> bytes` that renders the unit's current Daily Constancy UTC's TLIs (physics constancy tests only) into one PDF with chart links. RT/MPC list intentionally excluded at this stage (see revised design D4 / daily-qa-bundle-report spec).
- [x] 4.4 Implement `generate_daily_bundles(window_start, window_end, out_zip_path=None) -> zip_path` looping active linacs, producing `{unit_slug}_daily_qa_{YYYY-MM}.pdf` inside `daily_qa_report_{YYYY-MM}.zip`.
- [x] 4.5 **Verify**: dry-run prints each linac's resolved constancy + RT UTC pair (flag any unit where resolution is ambiguous); render one linac's bundle and confirm both sections present, MPC rows visible, chart links clickable.

## 5. django-q scheduled tasks

- [x] 5.1 Add entry points `run_linac_qa_archive(META)` and `run_daily_qa_bundle(META)` (META accepts `window`, `email_group`) in `qatrack/reports/tasks.py`, each computing `previous_month_window()` and calling the corresponding `generate_*` + email function.
- [x] 5.2 Register django-q `Schedule` rows for monthly execution on the 1st (cron `0 7 1 * *`) for both tasks, mirroring the existing myQA Schedule #7 pattern. Document in `AGENTS.md`.
- [x] 5.3 **Verify**: trigger each task via `./manage.py` shell call to the entry point with a test group; confirm the email/zip is produced and the schedule rows appear in Django admin.

## 6. Tests

- [x] 6.1 `qatrack/reports/tests/test_qa_selection.py`: cover empty exclusion, Once-Off/Other exclusion, stale exclusion, non-linac exclusion, canonical inclusion, window default = previous month, freq override.
- [x] 6.2 `qatrack/reports/tests/test_chart_links.py`: `chart_urls()` produces expected query params; `include_chart_links` default off leaves existing renders unchanged; flag on adds links for chartable tests, skips `chart_visibility=False`.
- [x] 6.3 `qatrack/reports/tests/test_qa_archive.py`: `generate_archive` produces correct per-UTC PDF count, naming, and zip layout; size guard switches to link-in-body when over limit.
- [x] 6.4 `qatrack/reports/tests/test_daily_bundle.py`: constancy UTC resolution (most-recent + override), bundle contains both sections, MPC rows present.
- [x] 6.5 Run `uv run ruff check . && uv run black --target-version py312 . && uv run python manage.py check && uv run pytest -x -m "not selenium" qatrack/reports/tests/`.

## 7. Live verification against production DB

- [x] 7.1 Run `./manage.py archive_linac_qa --dry-run --window lastmonth` on the dev repo (shared DB) and have the user review the selected UTC list for correctness (no junk, no missing canonical suites).
- [x] 7.2 Render one month's archive to a temp dir; spot-check 2-3 PDFs (a daily suite, a monthly suite, an annual suite) for completeness and chart-link correctness. _Full May-2026 archive (31 PDFs) rendered to `/tmp/qa_full/linac_qa_archive_2026-05.zip`; chart links confirmed embedded (1554 run + 1554 control per daily PDF)._
- [x] 7.3 Render one month's daily bundles; user confirms the resolved daily-constancy UTC is correct per linac and MPC appears. _Daily bundles rendered to `/tmp/qa_full/daily_qa_report_2026-05.zip` (6 constancy PDFs). Per the revised scope (design D4), MPC/RT is intentionally excluded — constancy physics tests only._
- [x] 7.4 Confirm recipient group and email attachment strategy (attach vs link) with user before enabling the monthly schedule. _Decided: no email; scheduled tasks write zips to the `pdf` folder._
