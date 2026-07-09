## Context

QATrack+'s report framework (`qatrack/reports/`) already supports PDF/XLSX/CSV rendering via WeasyPrint, saved report configs (`SavedReport`), rrule-based scheduling + email (`ReportSchedule`), and four QC report types. The richest is `TestListInstanceDetailsReport` — per-UTC, full values/references/tolerances/pass-fail/comments/attachments. What's missing is (a) a way to bundle per-linac daily QA (constancy + MPC) and (b) a batch-archive across all meaningful suites.

An investigation of the live PostgreSQL DB surfaced the real shape of the problem:

```
185 active UnitTestCollections across 8 linacs
 ├──  25 never run (0 TestListInstances ever)
 ├──  81 stale (last TLI > 1 year ago)
 └──  79 recent — but polluted with:
        "Testing", "New Testing", "Testing OBK", "Repair Testing"
        "zIsocenters_Test", "MatrixX Calc Check"
        "...(any point tracking this?)"
        Once-Off commissioning lists, bracketed duplicates
```

The "daily constancy" lineage is itself fragmented across three concurrent TestList families:

```
TL 3327   "Daily Constancy Check"            legacy bulk data (last ~Sep 2025)
TL 3328-3331 "Daily Constancy Check[1..4]"   the CURRENT live one, per-unit split
TL 3275   "5.Tmt.Linac.D - myQA Daily Constancy Check"  myQA-sourced, ~0 TLIs
```

MPC is NOT in the Daily Constancy lists. It lives as a Test (`Tmt.Linac.D - Run MPC`) inside the "Daily QA (RTs)" UTCs (TL 3276/3278). So "daily constancy + MPC" is two UTCs per linac, bundled.

Charts: the standard run chart is JS-only (`BasicChartData` returns JSON consumed in-browser). The Pawlicki control chart is a server-rendered PNG endpoint (`/qa/charts/control_chart.png`). No existing PDF report embeds chart images; all are tabular.

## Goals / Non-Goals

**Goals:**
- Monthly PDF archive of every canonical linac QA suite, one PDF per UTC, delivered by email.
- Monthly per-linac daily QA report bundling Daily Constancy + Daily QA (RTs, incl. MPC).
- Tabular values plus clickable links to the live interactive charts (run + control).
- On-demand generation via management command and via the existing `/reports/` UI.
- Automatic exclusion of empty/junk/test/Once-Off UTCs without manual allowlist maintenance.

**Non-Goals:**
- Server-side rendering of standard run charts as embedded images (would require a new matplotlib renderer; deferred — links suffice for v1).
- Embedding control-chart PNGs directly in PDFs (the endpoint exists; not wired into reports yet).
- Automatic tolerance/review-state analysis or trend alerting in the email body.
- Curating a hand-maintained UTC allowlist (the structural rule replaces this).
- Changing the existing report framework's rendering pipeline or MAX_TLIS caps.

## Decisions

### D1: One PDF per UTC, not a combined mega-PDF

**Decision**: The archive produces one PDF per UnitTestCollection, zipped together for delivery.

**Rationale**: `TestListInstanceDetailsReport` is hard-capped at `REPORT_UTCREPORT_MAX_TLIS = 365` TLIs per render (WeasyPrint memory/time). A combined "all suites × full history" PDF blows past this and yields an enormous, slow, unreviewable file. Per-UTC PDFs stay tiny (monthly daily suite ≈ 30 TLIs; monthly suite = 1 TLI), each is individually reviewable/signable/fileable, and the cap is never approached.

**Alternative considered**: Single combined PDF (rejected — cap + size); per-unit PDFs containing all that unit's suites (middle ground, deferred — per-UTC is simpler and composes into per-unit naturally later).

### D2: Structural + has-data selection rule

**Decision**: `select_archive_utcs(window)` returns UTCs where `active=True`, `unit` is a linac, `frequency__name in {Daily, Weekly, Monthly, Quarterly, Semi Annual, Annual}`, AND the UTC has ≥1 TestListInstance with `work_completed` inside `window`.

**Rationale**: Frequency-based exclusion drops "Other"/"Once Off" junk (Testing, commissioning, one-offs). The has-data-in-window requirement drops the 25 never-run and stale suites automatically without a manual allowlist. This takes 185 active → a clean set of ~40-60 canonical suites per month, self-maintaining as suites come and go.

**Consequence**: A suite that didn't run in the window produces no PDF that cycle (expected). A junk suite mistakenly tagged with a real frequency would still sneak in — acceptable; the frequency tags on real suites are reliable in this DB.

**Alternative considered**: Hand-curated allowlist (rejected — maintenance burden); pure "ran in window" with no frequency filter (rejected — lets `Testing` suites through).

### D3: Charts as links, not rendered images

**Decision**: PDFs render tabular data (existing engine) plus a chart-links column with URLs to `/qa/charts/?units[]=<u>&tests[]=<t>&...` (run chart) and `/qa/charts/control_chart.png?tests[]=<t>&...` (control chart). No chart images are embedded.

**Rationale**: The standard run chart is JS-rendered from JSON; producing an image would need a new matplotlib renderer. The control chart IS a server PNG, but embedding it per-test across hundreds of rows would bloat PDFs and slow rendering. Links give the reader one click to the live interactive chart, which is strictly more capable than a static image. This is the lightest-touch path and keeps the PDF a self-contained value record while pointing to trend views.

**Alternative considered**: Embed control-chart PNGs only (deferred — possible future enhancement once link approach is validated); write a matplotlib run-chart renderer (rejected for v1 — scope).

### D4: Daily bundle = Daily Constancy physics tests only (RT/MPC deferred)

**Decision**: The daily QA report renders, per linac, only the TLIs from the unit's *current* Daily Constancy Check UTC — i.e. the physics constancy tests (output, field width/penumbra, flatness, symmetry, energy factor, center) with chart links. The "Daily QA (RTs)" UTC (which contains MPC plus safety/mechanical tests) is **not** included at this stage; only physics constancy tests are wanted.

**Rationale**: The RT daily list ("Daily QA (RTs)") is dominated by safety/mechanical/operational tests (lasers, door interlocks, ODI, audiovisual monitors, beam-on indicators, collision, MLC QA, "Task ID") plus MPC, and only 3 of 8 linacs even have one. The physicists want the physics constancy values; the RT/safety clutter and MPC are deferred until a filtering rule for which RT tests to keep (MPC vs the rest) is agreed.

**Consequence**: Each linac must resolve to exactly one "current" Daily Constancy UTC. Resolution rule: the Daily Constancy UTC on that unit with the most recent `work_completed` (handles the `[1]` vs legacy base ambiguity). Configurable override via a YAML map if the rule misfires. The `resolve_rt_daily_utc` / `resolve_daily_pair` helpers are retained in code so the RT/MPC section can be re-added later without re-deriving resolution.

**Previous (superseded) rationale**: Users originally described wanting "daily constancy + MPC results" as one bundle; the scoping was narrowed to physics constancy only after seeing the RT list contents (all tests share the "Dosimetry" category, so a clean category-based filter is not possible without a per-test rule).

### D5: Reuse TestListInstanceDetailsReport, add optional chart-link rendering

**Decision**: Both new reports reuse `TestListInstanceDetailsReport`'s render path. A template-level flag (`include_chart_links`, default off) adds the chart-link column. The archive sets it on; the daily bundle sets it on; existing saved reports are unaffected.

**Rationale**: The details report already produces exactly the per-UTC value record needed (values, refs, tolerances, pass/fail, comments, attachments, who/when). Rewriting it would duplicate a large, tested surface. The chart-link addition is a small, opt-in template change.

### D6: Dual entry — management command + django-q scheduled task

**Decision**: On-demand generation via `./manage.py archive_linac_qa --window month [--email group | --out-dir path]` (mirrors the `import_myqa` pattern). Scheduled generation via a django-q task entry point invoked by `ReportSchedule`/cron, rendering + zipping + emailing.

**Rationale**: Matches the established myQA workflow (command for ops/bulk, django-q for scheduled). Reuses existing django-q + email infrastructure rather than inventing a new scheduling mechanism. `--dry-run` on the command previews the selected UTC list without rendering (essential for trusting D2).

### D7: Monthly cadence, previous calendar month, for both reports

**Decision**: Both the archive and the daily-bundle report run monthly, each covering the previous calendar month (00:00 first day → 23:59 last day).

**Rationale**: Standard QA record-keeping rhythm. Monthly windows keep daily-suite PDFs at ~30 TLIs (well under cap) and monthly-suite PDFs at 1 TLI. A monthly daily-QA review (rather than weekly/daily) is the user's stated cadence.

## Risks / Open Items

- **Daily Constancy UTC resolution (D4)**: the "most recent work_completed" rule must be verified against all linacs; `[1]`/legacy/`[2..4]` ambiguity may need a per-unit YAML override. Resolve during task 1 dry-run.
- **PDF naming convention**: propose `{unit_slug}/{list_slug}_{YYYY-MM}.pdf` inside the zip (one subdir per unit). Confirm during implementation.
- **Email recipients + attachment size**: a month of per-UTC PDFs across 6 linacs × ~10 suites could be a large zip. Confirm recipient group and whether to attach vs. link to a stored artifact. May need a size guard.
- **ReportSchedule vs. custom django-q Schedule**: the existing `ReportSchedule` sends a single `SavedReport` render, not a zip-of-PDFs. The scheduled archive likely needs a plain django-q `Schedule` (like Schedule #7 for myQA) rather than a `ReportSchedule`. Confirm during task wiring.
