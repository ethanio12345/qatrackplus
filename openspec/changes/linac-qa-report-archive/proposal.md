## Why

QATrack+ has a mature PDF report framework (`qatrack/reports/`) with four QC report types, `SavedReport`/`ReportSchedule` models, and WeasyPrint rendering — but no capability today to (a) bundle a linac's QA results into a reviewable PDF record, or (b) generate a comprehensive archive across all meaningful QA suites. Two clinical needs are unmet:

1. **Daily QA review**: Physicists need a periodic PDF of daily constancy results (outputs, energies, flatness, symmetry) plus MPC pass/fail — currently spread across multiple TestLists with no rollup. The data needed to spot trends lives in the interactive charts (`/qa/charts/`), but those are JS-only and produce no PDF.
2. **QA record archive**: A periodic, comprehensive PDF record per linac QA suite is needed for documentation/retention. A blanket "all active UnitTestCollections" approach is unworkable: there are 185 active linac UTCs, of which ~25 have never run, ~81 are stale (>1yr), and many are junk/test/duplicate suites (`Testing`, `zIsocenters_Test`, `(any point tracking this?)`, Once-Off commissioning lists).

## What Changes

- **NEW**: Selection function `select_archive_utcs()` that picks canonical QA suites by structural rule: frequency in {Daily, Weekly, Monthly, Quarterly, Semi Annual, Annual}, excluding "Other" / "Once Off", AND requiring ≥1 TestListInstance in the report window. This cleans the 25 empty + junk suites automatically.
- **NEW**: Linac QA archive — renders one PDF per selected UTC (via the existing `TestListInstanceDetailsReport` engine), packages into a zip, emails to a group. Monthly cadence covering the previous calendar month.
- **NEW**: Daily QA report — per linac, bundles the Daily Constancy UTC + the "Daily QA (RTs)" UTC (the latter carries the MPC test) into one PDF, tabular values + links to live charts. Monthly cadence covering the previous month.
- **NEW**: Chart-link helper that emits `/qa/charts/?...` URLs (run chart) and `/qa/charts/control_chart.png?...` URLs (control chart) for embedding as clickable links in PDF report templates. No server-side rendering of run charts (they remain JS-only); links point to the live interactive charts.
- **NEW**: `archive_linac_qa` management command for on-demand/bulk generation (mirrors the myQA command pattern).
- **NEW**: django-q entry points wiring both reports to `ReportSchedule`-style scheduled email delivery.
- **REUSE**: `TestListInstanceDetailsReport` render engine, WeasyPrint, `SavedReport`/`ReportSchedule`, django-q + email infra, management-command pattern.

## Capabilities

### New Capabilities
- `qa-suite-selection`: Structurally select canonical linac QA UnitTestCollections for a given time window, excluding empty/junk/Once-Off suites.
- `linac-qa-archive`: Generate one PDF per selected UTC for a time window, package as a zip, and deliver via email or filesystem.
- `daily-qa-bundle-report`: Per-linac PDF bundling Daily Constancy + Daily QA (RTs, with MPC) UTCs, tabular values plus chart links.

### Modified Capabilities
- `qc-pdf-reports`: Existing `TestListInstanceDetailsReport` gains optional chart-link rendering in its template, reused by both new reports.

## Impact

- **qatrack/reports/qa_selection.py** (NEW): `select_archive_utcs(window, freqs, exclude_freqs)` + helpers.
- **qatrack/reports/qa_archive.py** (NEW): per-UTC PDF → zip loop, `generate_archive(...)` entry point.
- **qatrack/reports/qc/daily_bundle.py** (NEW): daily-bundle report class + per-linac bundle logic.
- **qatrack/reports/templatetags/** or utils: `chart_url(test, unit, ...)` link helper.
- **qatrack/reports/templates/reports/qc/testlistinstance_details.html**: add chart-link column/section (gated, off by default for existing reports).
- **qatrack/qa/management/commands/archive_linac_qa.py** (NEW): on-demand command.
- **qatrack/reports/tasks.py** (or `qatrack/qa/tasks.py`): django-q scheduled entry points for both cadences.
- **MAX_TLIS**: per-UTC rendering stays well under the 365 cap for monthly windows (~30 TLIs for daily suites, 1 for monthly). No cap change needed.
- **Test strategy**: unit tests for selection rules (empty/junk/stale exclusion, frequency filtering, window coverage), rendering smoke tests (PDF bytes non-empty, expected sections present), packaging test (zip contains expected per-UTC PDFs with correct naming), and a dry-run command mode to preview the selected UTC list without rendering.
