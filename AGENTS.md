# AGENTS.md

## Tooling

- **Python 3.12**. Dependencies managed with `uv`.
- **Lint:** `uv run ruff check <files>` (config in `pyproject.toml`, line length 120).
- **Format:** `uv run black --target-version py312 <files>`.
- **Pre-commit** (run locally with `uvx pre-commit run --all-files`): ruff (no auto-fix), YAML/TOML checks, django-upgrade (target 4.2), `manage.py check`. CI fails on these.
- **Django check:** `uv run python manage.py check`.
- **Always run ruff + black after editing Python files.**

## Commands

```bash
uv run ruff check .                    # lint
uv run black --target-version py312 .  # format
uv run python manage.py check          # Django system check
uv run pytest -x -m "not selenium"     # tests (CI uses this exact invocation)
uv run pytest qatrack/qa/tests/test_models.py::TestClass::test_method  # single test
uv run python manage.py runserver      # dev server
```

## Settings and database

- Settings chain: `qatrack/settings.py` → `qatrack/local_settings.py` (gitignored on production; committed in this dev env).
- `qatrack/local_settings.py` defines `DATABASES`. For SQLite dev/CI, copy from `deploy/sqlite/local_settings.py`.
- Production DB is PostgreSQL (`qatrackplus31`).
- The `readonly` DB alias is required — `settings.py` references it.
- `qatrack/test_settings.py` exists but pytest does **not** use it (`DJANGO_SETTINGS_MODULE=qatrack.settings` in pyproject.toml). Tests requiring specific overrides use `override_settings`.

## Testing

- `uv run pytest` (config in `pyproject.toml`); tests under `qatrack/<app>/tests/`.
- Selenium tests exist but are slow/require xvfb. Run without them: `-m "not selenium"`.
- No `conftest.py` — pytest-django auto-discovers the project via `django_find_project = true`.
- SQLite DB file `qatrackplus31` is created in the repo root if running with SQLite.

## Django app structure

| Directory | Purpose |
|-----------|---------|
| `qatrack/qa/` | Core QA: Test/TestList/TestInstance models, views, tasks, management commands |
| `qatrack/qatrack_core/` | Shared utilities, scheduling, homepage |
| `qatrack/accounts/` | Auth (custom backend in `accounts/backends.py`) |
| `qatrack/reports/` | PDF/report generation (WeasyPrint) |
| `qatrack/units/` | Linac/treatment unit models |
| `qatrack/service_log/` | Service log records |
| `qatrack/faults/` | Fault tracking |
| `qatrack/parts/` | Parts inventory |
| `qatrack/issue_tracker/` | Issue tracking |
| `qatrack/api/` | DRF REST API |
| `qatrack/attachments/` | File attachments |

Key files:
- `qatrack/qa/models.py` — Test/TestList/TestInstance/UTC/UTI models.
- `qatrack/qa/tasks.py` — django-q scheduled tasks (myQA import entry point).
- `qatrack/myqa_import.py` — myQA import engine (see below).
- `qatrack/qa/management/commands/` — all Django management commands.

## myQA import system

Built around **dynamic TaskName discovery** — no hardcoded importer classes.
Everything is driven by what's in the myQA database (SQL Server, accessed via `pymssql`).

### Key concepts

- `qatrack/myqa_import.py` is the engine. `slugify_name()` produces bare slugs (no list prefix) so the same condition across tasks shares one Test via `TestListMembership`.
- Slugs are derived from **raw** condition names; `enrich_test_name()` applies human-readable naming + YAML overrides (`myqa_name_overrides.yaml`) for display only.
- `compute_multi_flags(conn, taskname)` must be computed at **TaskName level** and passed to extractors via `multi_override`. Computing per-session causes silent data loss.
- One TestList per TaskName (D1). One TestListInstance per session, aggregating all execution types (D4). Tests shared by condition name (D2). No tolerances set during setup (D3).
- `import_session()` creates a `{list_slug}_taskid` TestInstance storing the myQA TaskExecutionId for dedup.
- **Valueless sessions are skipped.** A session where `extract_all_types` returns rows but every condition's value is NULL (started/finished in myQA without entering readings) is skipped as `skipped_empty` — QATrack+ is a read-only duplicate, so no value = no TLI. (The guard checks for any non-null value across all extractors, not just non-zero rows.)
- **`*_taskid` TestInstances are auto-approved** (Approved status, `requires_review=False`) — they are dedup metadata, not clinical data.
- **TLIs auto-approve when all tests pass.** After `bulk_create`, `import_session()` calls `tli.auto_approve(internal_user)`, which applies the Default AutoReviewRuleSet (`ok`/`tolerance`/`no_tol`/`not_done` → Approved) and marks the TLI reviewed iff every test is within tolerance. Any `action` (out-of-tolerance) or commented test leaves it unreviewed.
- `MYQA_DB_SETTINGS` is read lazily inside `get_connection()` (`_myqa_db_settings()`), so `myqa_import` imports cleanly in environments that don't configure `MYQA_*` (e.g. the test suite, which mocks the connection).

### Management commands

| Command | Purpose |
|---------|---------|
| `setup_myqa_tests` | Discover TaskNames + create TestLists/Tests/UTCs/UTIs. `--dry-run` to preview. |
| `import_myqa --days N` | Import sessions. `--task-name` for single TaskName. |
| `clear_myqa_data --yes` | Delete all myQA-sourced data in FK-safe order. |
| `import_old_qatrack --file` | Restore old QATrack+ backup (Solid Water, MPC, CatPhan). |
| `approve_myqa_taskids` | Set all `*_taskid` TestInstances to Approved (dedup metadata). Idempotent. |
| `auto_approve_tlis` | Bulk auto-approve TLIs where all tests pass (Default AutoReviewRuleSet). Idempotent. |
| `delete_empty_tlis` | Delete valueless TLIs (real tests but all values NULL); cascades TIs; recomputes `last_instance`. Idempotent. |
| `clear_stale_due_dates` | Frequency-aware (`max(180d, 3× nominal_interval)`) → `due_date=None` + `auto_schedule=False` on stale UTCs. `--linacs-only`, `--apply`. Idempotent. |
| `set_angular_wraparound` | Set angular tests (gantry/collimator/couch/etc.) to `type=wraparound` [0,360] + re-evaluate `pass_fail`. Idempotent. |
| `setup_myqa_setup_schedule` | Register a weekly django-q Schedule that runs `setup_myqa_tests` (Sunday 02:00 local time, cron `0 2 * * 0`) so new unit↔TaskName combos are picked up automatically. Idempotent. |

### Operational workflow

```bash
uv run python manage.py clear_myqa_data --yes
uv run python manage.py setup_myqa_tests --dry-run
uv run python manage.py setup_myqa_tests
uv run python manage.py import_myqa --days 90
uv run python manage.py import_myqa --days 3650
```

### Scheduling

`qatrack.myqa_import.import_myqa_results(META)` is the django-q entry point.
`META` accepts `task_name` (str|None) and `days` (int).
`qatrack.qa.tasks.import_myqa_all()` is the higher-level wrapper called from management commands.

`qatrack.qa.tasks.run_setup_myqa_tests(META)` is the django-q entry point for
weekly **setup** (creates TestLists/UTCs/UTIs for new unit↔TaskName
combinations). It spawns `manage.py setup_myqa_tests` as a detached process
because setup takes minutes and would otherwise exceed qcluster's 60 s
timeout. Register its Schedule (cron `0 2 * * 0`, Sunday 02:00 **local
time** — django-q2 croniter uses `settings.TIME_ZONE`, not UTC) with
`setup_myqa_setup_schedule`. Without this, a newly-commissioned unit (e.g.
RFT26) accumulates myQA data that the daily import can't ingest because no
UTCs exist yet — `import_session` rejects every session with
`"No UTC for unit X / list Y"` until `setup_myqa_tests` runs.

### Current data state

The production DB has already been cleaned up via the one-off commands above, so
re-running them is a no-op: valueless TLIs have been purged (`delete_empty_tlis`),
all `*_taskid` TIs are Approved, passing TLIs are auto-reviewed, stale UTCs have
no due date (`clear_stale_due_dates`), and angular tests use wraparound
(`set_angular_wraparound`). TLIs remaining unreviewed are ones with genuine
out-of-tolerance (`action`) or commented tests.

### Gotchas (prevent regressions)

1. **`multi` flag must be TaskName-level, not per-session.** `compute_multi_flags()` computes once per batch; passed to all extractors via `multi_override`. Extractors that use it: `extract_numeric`, `extract_profile`, `_extract_pattern_b`, `extract_vmat`, `extract_winston_lutz`.

2. **Discover functions must return `[]` when no data exists** for that execution type. `_discover_pattern_b_conditions` and `discover_winston_lutz_conditions` previously returned full metric lists, creating spurious tests in unrelated TestLists.

3. **VMAT "Normalization Value" is never prefixed** by test-step name, even when `multi=True`. `discover_vmat_conditions` emits it unprefixed (shared Test).

4. **Duplicate TaskNames in myQA** (e.g. `"Dosimetry - Monthly QA"` vs `"Dosimetry - Monthly QA (1)"`) are a myQA data issue. Each gets its own TestList.

5. **Naive datetime RuntimeWarnings** from myQA are harmless (Django auto-converts with `USE_TZ=True`).

6. **Wraparound (angular) values are per-Test DATA config, not auto-detected.** Circular angles (gantry/collimator/couch/table) use `Test.type='wraparound'` + `wrap_low`/`wrap_high`, evaluated by `difference_wraparound()` in `qatrack/qa/models.py`. Until `set_angular_wraparound` was run, every angular test here was `type=simple` (0 used wraparound), so 0.1° vs 359.9° showed as 359.8° apart. **New angular tests must be set to wraparound manually** (or re-run `set_angular_wraparound`, which matches by name and is idempotent).

7. **qcluster runs as `www-data` with `Q_CLUSTER['timeout'] = 60`.** Never do long work inline in a django-q task — it's killed at 60 s. Long jobs (e.g. the QA PDF renders) must `spawn manage.py …` as a detached background process and return immediately (see "Linac QA report archive"). django-q workers import task code fresh per run, so code changes need **no qcluster restart** (a restart is only needed for `Q_CLUSTER` setting changes).

8. **`pdf/` folder is chmod 0o777** by `default_out_dir()` so both `www-data` (qcluster) and admins can write to it regardless of who created it first.

9. **Running pytest requires SQLite.** The dev `local_settings.py` points at the shared production PostgreSQL cluster (no `CREATE DATABASE` permission). Before running tests: `cp deploy/sqlite/local_settings.py qatrack/local_settings.py`, run pytest, then restore the production `local_settings.py`.

10. **`uv.lock` is gitignored but still tracked** (it was tracked before the ignore line was added). `pyproject.toml` is the source of truth for dependencies; production runs `uv sync` on deploy, which regenerates `uv.lock` locally.

11. **`Tolerance.save()` overwrites `name` with `%.3f` / `%.2f%%` formatting** via `qatrack/qa/models.py:get_tolerance_name`. Distinct small numeric values (e.g. `warn=3e-06` vs `warn=5e-06`) truncate to the same name and hit the `Tolerance.name` UNIQUE constraint, which previously crashed the entire session import. `_get_or_create_tolerance` in `qatrack/myqa_import.py` now wraps `save()` in a savepoint and falls back to a name-based lookup on `IntegrityError` so the import continues. Don't reintroduce the bare `get_or_create`.

## Sharing with another centre

The myQA import system is portable across centres. The three-change
portability programme (`myqa-centre-config-externalisation`,
`myqa-centre-onboarding`, `myqa-centre-trust-and-ops`) externalises every
centre-specific value to YAML, adds an interactive bootstrap command, and
ships a deployment guide.

**New centre onboarding:** see [`docs/myqa_deployment_guide.md`](docs/myqa_deployment_guide.md) for the
step-by-step from `git clone` to confident clinical use. The TL;DR:

```bash
git clone <repo> && cd qatrackplus
cp qatrack/local_settings.example.py qatrack/local_settings.py   # fill in MYQA_*, TIME_ZONE, DATABASES
uv sync && uv run python manage.py migrate
uv run python manage.py myqa_doctor              # validate preconditions
uv run python manage.py bootstrap_myqa_centre    # interactive two-phase onboarding
uv run python manage.py import_myqa --days 90    # backfill
uv run python manage.py myqa_validate --days 90  # diff vs myQA
uv run python manage.py setup_myqa_setup_schedule  # weekly auto-setup
```

**Three centre-config files** (edit these, not the Python code):

| File | Purpose |
|---|---|
| `qatrack/qa/management/commands/myqa_device_map.yaml` | `unit_number → myQA RadiationDeviceName` |
| `qatrack/qa/management/commands/myqa_centre_config.yaml` | network name, multi-site list, device-class rules, linac unit-type allowlist, optional frequency overrides |
| `qatrack/qa/management/commands/myqa_name_overrides.yaml` | myQA condition-name → descriptive display-name overrides |

**Latent bug fixed by Change A:** the pre-refactor
`create_myqa_units.py` classified linacs by unit-number range, which
mis-classified RFT26 (unit 437) as `Audit / Safety / Security` because
435-441 was a Safety range. The new name-pattern classification correctly
identifies RFT26 as `Treatment LINAC`. `LINAC_UNIT_TYPE_NAMES` in
`reports/qa_selection.py` now includes `"Treatment LINAC"` so
myQA-created linacs are visible to `clear_stale_due_dates --linacs-only`
and the linac QA PDF archive.

For the operational scripts reference (clear_stale_due_dates,
set_angular_wraparound, etc.), see
[`docs/myqa_operational_scripts.md`](docs/myqa_operational_scripts.md).

## OpenSpec

```bash
openspec list --json
openspec status --change "<name>" --json
openspec instructions apply --change "<name>" --json
```

Active and archived changes under `openspec/changes/`. **There are currently no
active changes.** Design docs for the myQA redesign live in the archive at
`openspec/changes/archive/2026-07-09-myqa-dynamic-taskname-import/`; the linac
QA archive design is at `openspec/changes/archive/2026-07-09-linac-qa-report-archive/`.

Two older changes (`myqa-complete-coverage`, `fix-myqa-importers`) were
**archived without syncing their delta specs** — they describe the superseded
hardcoded importer-class architecture (pre-dynamic-redesign) and must not be
re-synced. The four completed current-architecture changes were synced, so
`openspec/specs/` holds the authoritative capability specs (dynamic-taskname
discovery, multi-type-session-import, myqa-device-expansion,
myqa-dosimetry-tolerances, old-db-restore, myqa-state-aware-import,
daily-qa-bundle-report, linac-qa-archive, qa-suite-selection, qc-pdf-reports)
alongside the historical `myqa-sync` and `descriptive-test-names` specs.

## Linac QA report archive

Periodic PDF record-keeping for linac QA (see `openspec/changes/linac-qa-report-archive/`).

| What | Where |
|------|-------|
| UTC selection rule | `qatrack/reports/qa_selection.py` (`select_archive_utcs`, `previous_month_window`, `LINAC_UNIT_TYPE_NAMES`) |
| Archive (per-UTC PDF → zip → email) | `qatrack/reports/qa_archive.py` (`generate_archive`, `render_utc_pdf`, `email_archive`, `copy_to_mirror`) |
| Daily QA bundle (constancy physics tests) | `qatrack/reports/qc/daily_bundle.py` (`generate_daily_bundles`, `resolve_current_daily_constancy_utc`) |
| Chart-link helper + templatetag | `qatrack/reports/chart_links.py`, `qatrack/reports/templatetags/chart_links.py` |
| Management commands | `archive_linac_qa` (render/email/dry-run), `daily_qa_bundle` (render/email/dry-run), `setup_qa_report_schedules` (register django-q Schedules) |
| django-q entry points | `qatrack/reports/tasks.py` (`run_linac_qa_archive`, `run_daily_qa_bundle`) |
| Daily-constancy UTC override | `qatrack/reports/daily_constancy_override.yaml` (optional, `{unit_name: utc_pk}`) |

### Operational workflow

```bash
uv run python manage.py archive_linac_qa --dry-run --window lastmonth      # preview selection
uv run python manage.py archive_linac_qa --window lastmonth --out-dir /tmp/qa  # render to zip
uv run python manage.py setup_qa_report_schedules --email-group physicists    # register monthly Schedules
```

### Output + mirror

By default zips are written to the `pdf` folder (`<repo>/pdf`, overridable via
`QA_REPORTS_OUT_DIR`) and **also copied** to the network drive
`/mnt/oncology_d/Physics Data/4. Software/QATrackPlus` (Windows
`P:\4. Software\QATrackPlus`) so physicists can retrieve them without logging
into the server. The mirror copy is best-effort (non-fatal if the drive is
unmounted); override or disable via the `QA_REPORTS_MIRROR_DIR` setting.

### Scheduling

Two django-q `Schedule` rows (cron `0 7 1 * *`, 1st of month 07:00) drive the
monthly cadence covering the previous calendar month, mirroring the myQA
Schedule #7 pattern. Register them with `setup_qa_report_schedules`. By default
no email is sent; pass `--email-group <group>` to also email. Both entry points
accept `META` (`{"window": ..., "email_group": ..., "out_dir": ...}`) or direct
kwargs (`window`, `email_group`, `out_dir`).

**Long renders run detached.** The render takes ~40-45 min (WeasyPrint on the
daily-constancy suites), far exceeding `Q_CLUSTER['timeout']` (60 s). The
django-q entry points therefore `spawn manage.py archive_linac_qa /
daily_qa_bundle as a detached background process` and return immediately;
the command does the render + mirror + (optional) email and logs to
`<repo>/pdf/{linac_qa_archive,daily_qa_bundle}.log`. No qcluster restart is
needed for code changes (workers import the entry point fresh per task).
Requires the `croniter` dependency for cron schedules.


## Ruff config

- Selects: `E, F, I, UP, DJ`.
- Ignores: `E501` (line length), `E741`, `DJ001`, `DJ006`, `DJ007`, `DJ008`, `UP031`.
- Excludes: `fixtures/`, `migration_data/`, `migrations/`, `south_migrations/`, `node_modules/`, `media/`, `static/`, `*tmp*`.

## Production deployment

- **Dev repo**: `/home/bchcphysics/Github/qatrackplus` (git clone, `develop` branch).
- **Production**: `/home/bchcphysics/web/qatrackplus` (git clone of same `origin/develop`).
- **Shared database**: Both dev and prod use the same PostgreSQL database
  (`qatrackplus31`). Running `manage.py` from either repo modifies the
  production database.
- **Deploy script**: `bash deploy_to_prod.sh` — fetches latest `origin/develop`,
  resets production, runs `uv sync`, restarts qcluster + apache.
  - `--first` for initial setup (recreates venv if root-owned).
  - `--code` for code-only deploys (skip deps/restart).
- **Scheduled task**: django-q Schedule #7 ("myQA Daily Import") runs
  `import_myqa_results({"days": 2})` daily at ~03:37 UTC. This is the **bulk
  data ingestion** from myQA (the data source for everything else) — not to be
  confused with the two monthly **PDF report** schedules ("Linac QA Archive
  Monthly" and "Daily Constancy PDF Bundle (Monthly)", cron `0 7 1 * *`), which
  render reports from already-imported data.
- **Pipeline command**: Run `/myqa-pipeline` in opencode for the full
  clear -> setup -> import -> deploy workflow.
- **Restart script**: `bash restart_qcluster.sh` — kills all stale qcluster
  processes and restarts the systemd service cleanly.
