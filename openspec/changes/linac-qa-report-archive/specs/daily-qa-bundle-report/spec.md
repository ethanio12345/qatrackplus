## ADDED Requirements

### Requirement: Per-linac daily constancy bundle
The daily QA report SHALL produce, per linac, a single PDF of the unit's current Daily Constancy Check UTC's TestListInstances for the window — i.e. the physics constancy tests (output, field width/penumbra, flatness, symmetry, energy factor, center) with chart links.

> **Scope note (revised):** the original design called for a second section from the "Daily QA (RTs)" UTC (which carries MPC). At this stage only the physics constancy tests are wanted; the RT/MPC section is deferred. The RT-resolution helpers remain in the code for a future revision.

#### Scenario: Bundle contains the Daily Constancy section
- **WHEN** the daily report renders for unit "Coast: 2361" for June 2026
- **THEN** the PDF contains the Daily Constancy Check TLIs scoped to the window, and no RT daily QA / safety / mechanical tests

### Requirement: Current daily constancy UTC resolution
For each linac, the current Daily Constancy UTC SHALL be resolved as the UTC whose name starts with "Daily Constancy" on that unit with the most recent `work_completed`. A YAML override map (`daily_constancy_override.yaml`) keyed by unit name SHALL take precedence when present.

#### Scenario: Resolution by most-recent
- **WHEN** unit "LA224" has both "Daily Constancy Check" (last 2025-09-21) and "Daily Constancy Check[3]" (last 2026-06-28)
- **THEN** "Daily Constancy Check[3]" is selected as the current UTC

#### Scenario: Override applied
- **WHEN** `daily_constancy_override.yaml` maps "LA224" to UTC pk 7810
- **THEN** that UTC is used regardless of most-recent rule

### Requirement: MPC / RT section deferred
MPC pass/fail and the "Daily QA (RTs)" tests SHALL NOT appear in the daily bundle at this stage. A linac that resolves to a Daily Constancy UTC renders a constancy-only bundle; linacs with no Daily Constancy UTC are skipped. The `resolve_rt_daily_utc` helper is retained for the future RT/MPC revision.

#### Scenario: No RT tests in bundle
- **WHEN** a "Daily QA (RTs)" TLI exists in the window alongside the Daily Constancy TLIs
- **THEN** the bundle PDF does not include any RT daily QA test rows

### Requirement: Tabular values plus chart links
Each test row in the daily bundle SHALL include clickable links to the live run chart and control chart for that test/unit, scoped to the report window. Links SHALL point at `/qa/charts/?...` and `/qa/charts/control_chart.png?...`.

#### Scenario: Chart link present per test
- **WHEN** the bundle renders a row for test "10MV Dose Output" on unit "LA317"
- **THEN** the row includes a link to `/qa/charts/?units[]=<LA317 pk>&tests[]=<test pk>&...` and a control-chart link

### Requirement: Daily bundle packaging and delivery
Daily bundles SHALL be packaged one PDF per linac, named `{unit_slug}_daily_qa_{YYYY-MM}.pdf`, zipped together as `daily_qa_report_{YYYY-MM}.zip`, and delivered via email or filesystem identically to the archive (size guard applies).

#### Scenario: One PDF per linac
- **WHEN** the daily report runs for 6 active linacs with Daily Constancy data for June 2026
- **THEN** the zip contains 6 PDFs, one per linac

### Requirement: Scheduled monthly daily-bundle generation
The daily bundle SHALL be invocable as a django-q scheduled task covering the previous calendar month, runnable on the 1st of each month (alongside the archive).

#### Scenario: Monthly daily-bundle schedule
- **WHEN** the django-q schedule fires on 2026-07-01
- **THEN** daily constancy bundles render for window 2026-06-01 to 2026-06-30 for all active linacs with Daily Constancy data
