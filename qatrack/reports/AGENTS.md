# AGENTS.md — Reports & Linac QA Archive

This directory holds the PDF/report framework **and** the monthly linac QA
archive system. The archive is built on top of the existing
`TestListInstanceDetailsReport` engine (no new render path).

## Quick reference

| What | Where |
|------|-------|
| Report framework (BaseReport, formats, scheduling) | `qatrack/reports/reports.py`, `qatrack/reports/tasks.py` |
| UTC selection rule | `qatrack/reports/qa_selection.py` (`select_archive_utcs`, `previous_month_window`, `resolve_window`, `LINAC_UNIT_TYPE_NAMES`) |
| Archive (per-UTC PDF → zip → email/mirror) | `qatrack/reports/qa_archive.py` (`generate_archive`, `render_utc_pdf`, `email_archive`, `copy_to_mirror`, `default_out_dir`) |
| Daily QA bundle (constancy physics tests) | `qatrack/reports/qc/daily_bundle.py` (`generate_daily_bundles`, `resolve_current_daily_constancy_utc`) |
| Chart-link helper + templatetag | `qatrack/reports/chart_links.py`, `qatrack/reports/templatetags/chart_links.py` |
| Management commands | `archive_linac_qa`, `daily_qa_bundle`, `setup_qa_report_schedules` (in `qatrack/qa/management/commands/`) |
| django-q entry points | `qatrack/reports/tasks.py` (`run_linac_qa_archive`, `run_daily_qa_bundle`) |
| Daily-constancy UTC override | `qatrack/reports/daily_constancy_override.yaml` (optional, `{unit_name: utc_pk}`) |
| Design docs | `openspec/changes/archive/2026-07-09-linac-qa-report-archive/` |

## Behaviour

- **One PDF per selected UTC** (archive) / **one PDF per linac** (daily bundle),
  zipped together, written to the `pdf` folder and mirrored to the network
  drive `P:\4. Software\QATrackPlus` (`/mnt/oncology_d/Physics Data/4. Software/QATrackPlus`).
- **Daily bundle is constancy-only.** It renders the unit's current Daily
  Constancy Check UTC (output/field-width/flatness/symmetry/energy/center). The
  RT/MPC daily list is intentionally excluded at this stage (RT resolution
  helpers are retained for a future revision). See design D4.
- **Chart links, not images.** PDFs render tabular data plus clickable links to
  the live `/qa/charts/` (run) and `/qa/charts/control_chart.png` (control)
  endpoints — gated by `include_chart_links` (off by default, so existing saved
  reports render byte-identically).

## Scheduling (read this before touching the entry points)

- The render takes ~40–45 min (WeasyPrint on daily-constancy suites), far over
  `Q_CLUSTER['timeout']` (60 s). **The django-q entry points spawn
  `manage.py archive_linac_qa` / `daily_qa_bundle` as detached background
  processes and return immediately.** The command does the render + mirror +
  (optional) email and logs to `<repo>/pdf/{linac_qa_archive,daily_qa_bundle}.log`.
- No qcluster restart is needed for code changes (workers import the entry
  point fresh per task). A restart is only needed for `Q_CLUSTER` setting changes.
- Two django-q `Schedule` rows (cron `0 7 1 * *`, 1st of month 07:00) drive the
  monthly cadence: "Linac QA Archive Monthly" and "Daily Constancy PDF Bundle
  (Monthly)". These are **PDF reports** — distinct from Schedule #7 ("myQA Daily
  Import"), which is bulk data ingestion. Register with `setup_qa_report_schedules`.
- Requires the `croniter` dependency for cron schedules.

## Gotchas

- **Don't run the heavy render inline in a django-q task** — it will be killed
  at the 60 s timeout. Always go through the detached-spawn entry points (or run
  the management command directly).
- **`default_out_dir()` chmods the `pdf` folder to 0o777** so both `www-data`
  (qcluster) and admins can write. The mirror copy is best-effort (non-fatal if
  the network drive is unmounted).
- **The chart-link column must stay opt-in.** `include_chart_links` defaults to
  False; existing `TestListInstanceDetailsReport` saved reports must render
  unchanged. Only the archive and daily bundle set it True.
- **Daily-constancy UTC resolution** picks the unit's "Daily Constancy…" UTC
  with the most recent `work_completed`; override per unit via
  `daily_constancy_override.yaml` if the rule misfires.

See the top-level `AGENTS.md` for the full command list and the qcluster/www-data timeout discussion.
