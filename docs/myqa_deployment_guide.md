# myQA Import System — Deployment Guide for a New Centre

This guide walks you through deploying the myQA auto-detection import system at a new hospital, from `git clone` to confident clinical use. No Python or YAML knowledge is assumed.

For a visual overview of how the system fits together (data flow, config files, scheduling), see [myQA Architecture](myqa_architecture.md).

## At a glance

```
   ┌─────────────────────────────────────────────────────────────┐
   │  1. PREREQUISITES         Before you touch anything         │
   │  2. CONFIGURE             Wire up your myQA                 │
   │  3. VALIDATE PRE          myqa_doctor — confirm foundations │
   │  4. BOOTSTRAP             bootstrap_myqa_centre — build    │
   │  5. FIRST IMPORT          import_myqa --days 90 — history  │
   │  6. ★ TOLERANCE REVIEW ★  STOP. Read this before clinical  │
   │  7. VALIDATE POST         myqa_validate — does it match?   │
   │  8. SCHEDULE              Daily/weekly/monthly automation  │
   │  9. OPERATE               Ongoing cadence                  │
   │ 10. CUSTOMISE             Extending for your centre        │
   │ 11. TROUBLESHOOT          Common failure modes             │
   └─────────────────────────────────────────────────────────────┘
```

---

## 1. Prerequisites

Before you start, you need:

- A working **QATrack+** deployment (PostgreSQL backend recommended).
- A reachable **myQA SQL Server** database (IBA myQA product). The system uses the standard `MQA_*` schema; no myQA-side configuration changes are needed.
- myQA credentials with **SELECT permission** on the `MQA_*` tables. Read-only is sufficient and preferred.
- Python 3.12+ and [`uv`](https://github.com/astral-sh/uv) for dependency management.

Verify Python and pymssql are working:

```bash
uv run python -c "import pymssql; print('pymssql', pymssql.__version__)"
```

If that fails, run `uv sync` to install dependencies from `pyproject.toml`.

## 2. Configure

Copy the settings template and fill in your centre's details:

```bash
cp qatrack/local_settings.example.py qatrack/local_settings.py
$EDITOR qatrack/local_settings.py
```

Required settings (see the example file for full annotations):

- **`DATABASES`** — your QATrack+ PostgreSQL database (and a `readonly` alias pointing at a read-only role).
- **`MYQA_DB_SERVER`**, **`MYQA_DB_NAME`**, **`MYQA_DB_USERNAME`**, **`MYQA_DB_PASSWORD`** — your myQA SQL Server connection.
- **`TIME_ZONE`** — your centre's timezone (e.g. `"Australia/Sydney"`, `"Europe/London"`). This affects when the weekly setup schedule fires.
- **`ALLOWED_HOSTS`** — your server's hostnames/IPs.

Run migrations and load QATrack+ default fixtures:

```bash
uv run python manage.py migrate
uv run python manage.py loaddata fixtures/defaults/qa/categories.json
uv run python manage.py loaddata fixtures/defaults/qa/statuses.json
uv run python manage.py loaddata fixtures/defaults/qa/frequencies.json
```

## 3. Validate pre (myqa_doctor)

```bash
uv run python manage.py myqa_doctor
```

This runs 12 checks covering settings, myQA connectivity, fixtures, statuses, frequencies, user, categories, device-map integrity, and dependencies. Four soft preconditions (the "QATrack+ Internal" user, the "skipped" status, missing Frequencies, the "Uncategorised" Category) are auto-created on first run.

Expected output: **`✓ 12 OK`** (or warnings for items the bootstrap will fix in the next step).

If check 1 (settings) fails: edit `local_settings.py`.
If check 2 (connection) fails: confirm your myQA server is reachable and credentials are correct.
If check 12 (croniter) fails: `uv add croniter`.

JSON output for CI: `uv run python manage.py myqa_doctor --json`.

## 4. Bootstrap

The bootstrap command introspects your myQA and builds the device map interactively:

```bash
uv run python manage.py bootstrap_myqa_centre --scan
```

This connects to myQA, lists every distinct `RadiationDeviceName`, filters obvious test fixtures (`DUMMY*`, `test`, `tbd` — overridable via `--dummy-regex`), and writes a draft device map at `qatrack/qa/management/commands/myqa_device_map.draft.yaml` with auto-suggested unit numbers/types/sites based on your `myqa_centre_config.yaml`.

Review the draft:

```bash
$EDITOR qatrack/qa/management/commands/myqa_device_map.draft.yaml
```

Adjust unit numbers if you have an existing numbering convention. Remove any devices you don't want imported. Then apply:

```bash
uv run python manage.py bootstrap_myqa_centre --apply
```

This creates `Unit` rows, writes the production `myqa_device_map.yaml` atomically, and runs `setup_myqa_tests` automatically. **Read the warning banner it prints** (see step 6).

**Alternative (non-interactive):** if you prefer pure manual editing, run `bootstrap_myqa_centre --scan --non-interactive` to get a fully-commented skeleton. Uncomment the entries you want, fill in unit numbers, then run `--apply`.

## 5. First import

Pull 90 days of historical sessions:

```bash
uv run python manage.py import_myqa --days 90
```

Expected output: `Imported: N, Skipped (dup): 0, Skipped (empty): M, Skipped (err): 0, Total found: N+M`.

For the very first import, "Skipped (dup)" should be 0 (nothing imported yet). "Skipped (empty)" is normal — sessions myQA has but QATrack+ ignores because they have no readings. "Skipped (err)" should be 0; if not, see troubleshooting (section 11).

To import full history:

```bash
uv run python manage.py import_myqa --days 3650
```

This takes longer (potentially hours for 10 years of data) but is idempotent — re-running skips already-imported sessions via the `_taskid` dedup mechanism.

---

## 6. ★ TOLERANCE REVIEW ★

> **STOP. Read this section before clinical use.**

The import auto-configures **tolerances** on every `UnitTestInfo` based on your myQA `WarnOn` / `FailOn` values. These are myQA's vendor defaults and **may not match your centre's clinical protocols**.

Before relying on any pass/fail status from QATrack+:

1. **Review tolerances** for every UTI via the admin **Set References and Tolerances** page. The QATrack+ admin documentation covers this in detail:
   - [Setting Reference & Tolerance Values](admin/qa/setting_refs_and_tols.rst) — step-by-step with screenshots
   - [Tolerance Types](admin/qa/tolerances.rst) — absolute vs percent, how pass/fail is computed
   - [Auto Review Rules](admin/qa/auto_review.rst) — how TLIs auto-approve when all tests pass
2. **Adjust** any that don't match your protocols — the admin UI lets you set per-UTI tolerances independently.
3. **Run `myqa_validate`** (next step) to see a diff between QATrack+ tolerances and myQA's source-of-truth.

This is a clinical-safety responsibility. The system surfaces the data; your centre owns the decision.

---

## 7. Validate post

```bash
uv run python manage.py myqa_validate --days 90
```

This compares QATrack+ state to myQA's source-of-truth for the given window. For each `(TaskName, unit)` combination, it reports:

- **Session-count mismatch** — myQA has sessions QATrack+ doesn't.
- **Per-session condition-count mismatch** — TLI is missing conditions.
- **Per-condition value mismatch** — values differ beyond 4-decimal rounding.
- **Per-condition tolerance mismatch** — UTI tolerances differ from myQA's.
- **Categorisation of unimported sessions** as either:
  - `valueless_skip` (myQA had no readings — engine correctly skipped — **OK**)
  - `genuine_drop` (myQA had readings but no TLI — **investigate**)

Expected on a healthy system: `N pass, 0 needs review`. Any `needs_review` deserves attention — see troubleshooting (section 11).

For CI / scripted checks: `--json` emits a stable schema; `--summary-only` skips per-condition comparison for speed.

This command is also useful operationally — run it after every big import to catch silent drops.

## 8. Schedule

Register the automation schedules:

```bash
uv run python manage.py setup_myqa_setup_schedule   # weekly setup (Sundays 02:00 local)
```

The daily import schedule (`myQA Daily Import`) and autosave cleaner are auto-registered on `migrate`. If they're missing for any reason, `uv run python manage.py migrate` re-runs the `post_migrate` hook that creates them.

Monthly PDF archive schedules (optional, only if you use the linac QA archive):

```bash
uv run python manage.py setup_qa_report_schedules
```

Verify schedules are registered:

```bash
uv run python -c "
import django; django.setup()
from django_q.models import Schedule
for s in Schedule.objects.all().order_by('id'):
    print(s.id, s.name, s.func, s.cron or 'DAILY')"
```

## 9. Operate

Once deployed, the system runs itself: daily import, weekly setup for new units/TaskNames, monthly PDFs (optional). Here's the routine cadence:

| Cadence | Command | Purpose |
|---|---|---|
| **Daily** | (automatic — Schedule #7) | Import sessions from the last 2 days |
| **Weekly** | (automatic — Schedule "myQA Weekly Setup") | Detect new unit↔TaskName combinations |
| **Monthly** | `uv run python manage.py myqa_validate --days 30` | Catch silent drops before they matter |
| **Monthly** | `uv run python manage.py clear_stale_due_dates --linacs-only --apply` | Clear due_dates on UTCs that haven't run in `max(180d, 3× nominal_interval)` |
| **Quarterly** | `uv run python manage.py set_angular_wraparound` | Re-classify new angular tests to `wraparound` (idempotent — only new ones) |
| **After rebaselining** | `uv run python manage.py import_myqa --task-name "<TaskName>" --days 30` | Pull new tolerances after myQA reference values change |
| **Yearly (audit)** | `uv run python manage.py myqa_doctor` | Validate all preconditions still hold |

For the full reference of every maintenance command, see [`docs/myqa_operational_scripts.md`](myqa_operational_scripts.md).

## 10. Customise

The system is designed to be extended without code changes:

### `myqa_device_map.yaml`

Maps QATrack+ unit numbers to myQA RadiationDeviceNames. Edit when myQA adds or renames devices. List form (`[name1, name2]`) is supported for device-name variants.

### `myqa_centre_config.yaml`

Holds your centre's network name, site list (with device-prefix routing), device-class rules (regex → unit_type + category), linac unit-type allowlist, and optional frequency-inference overrides. Edit when your centre reorganises, renames a site, or adds a new device class. See the YAML header for schema docs.

### `myqa_name_overrides.yaml`

Maps myQA condition names to descriptive display names. Useful when myQA's raw condition names are cryptic (e.g. `"01.01 Output Constancy 6X"` → `"Output Constancy 6MV"`).

### Angular test wraparound

If your centre's myQA condition names for angular quantities (gantry/collimator/couch angles) don't match the curated patterns in `set_angular_wraparound.py`, edit that command's `INCLUDE` regex. Run `--dry-run` to preview, `--apply` to convert. Idempotent.

## 11. Troubleshoot

### Diagnostic commands quick reference

| Symptom | First command to run | What it tells you |
|---|---|---|
| Sessions not importing | `myqa_doctor` | Which preconditions are broken (settings, connection, fixtures) |
| Suspicious or missing data | `myqa_validate --days 30` | Session-count mismatches, valueless_skip vs genuine_drop, tolerance drift |
| New unit not picked up | `bootstrap_myqa_centre --scan` | Whether the device exists in myQA and how it would be classified |
| Stale due dates cluttering schedule | `clear_stale_due_dates --linacs-only` | Which UTCs haven't run in `max(180d, 3× nominal_interval)` |
| Angular tests showing huge differences | `set_angular_wraparound --dry-run` | Which angular tests are still `type=simple` (not wraparound) |
| TLI stuck in unreviewed queue | `auto_approve_tlis` | How many TLIs would be auto-approved by the Default AutoReviewRuleSet |
| Import errors with "unique constraint" | Check the error detail | Likely a Tolerance name collision — see Tolerance name collisions below |

### Detailed troubleshooting

### "No UTC for unit X / list Y" errors during import

**Symptom:** `import_myqa` reports `Skipped (err): N`, with reasons like `"No UTC for unit 437 / list daily_constancy_check"`.

**Cause:** A Unit/TaskList pair has no `UnitTestCollection`. Either the device isn't in `myqa_device_map.yaml`, or `setup_myqa_tests` hasn't been run since the unit started producing data for that TaskName.

**Fix:** Run `uv run python manage.py setup_myqa_tests` (or wait for the weekly schedule to fire). Confirm the device is mapped: `grep "<device_name>" qatrack/qa/management/commands/myqa_device_map.yaml`. If not, run `bootstrap_myqa_centre --scan` and add it.

### Valueless sessions (skipped_empty)

**Symptom:** `import_myqa` reports `Skipped (empty): N`.

**Cause:** Sessions myQA has but where every condition's value is `NULL`. This is normal — myQA sometimes creates a session entry that's started but never filled in. The engine correctly skips these (QATrack+ is a read-only duplicate; no values = nothing to store).

**Fix:** None needed. If you want to confirm, `myqa_validate --days 30` categorises them as `valueless_skip`.

### Genuine drops (genuine_drop in myqa_validate)

**Symptom:** `myqa_validate` reports `genuine_drop: N` for a TaskName/unit.

**Cause:** myQA has sessions with non-null values that QATrack+ didn't import. Likely causes: a recent outage of the daily import, a slug collision in the TestList, or a bug.

**Fix:** Try `uv run python manage.py import_myqa --task-name "<TaskName>" --days 7` to retry. If the drops persist, inspect the failing session's `TaskExecutionId` in myQA and compare to what the extractor returns.

### Tolerance name collisions

**Symptom:** `import_myqa` reports `Skipped (err): N`, error mentions `qa_tolerance_name_..._uniq`.

**Cause:** Two distinct numeric tolerance values (e.g. `warn=3e-06` vs `warn=5e-06`) truncate to the same display name (`Absolute(-0.000, …)`) via the model's `%.3f` formatting. The engine has a savepoint-based fallback that should handle this automatically.

**Fix:** Should be auto-handled. If errors persist, the fallback may be failing for a different reason — file an issue with the full error.

### Slug collisions (missing conditions in TLI)

**Symptom:** `myqa_validate` reports `condition-count mismatch` for a TLI.

**Cause:** Two myQA conditions in the same TaskName slugify to the same value (e.g. `"01. Pressure"` and `"07. Pressure"` both → `pressure`). The setup command disambiguates with `_2`, `_3` suffixes, but extract-time slug computation in the import may map both to the same Test, losing one value.

**Fix:** Add an entry to `myqa_name_overrides.yaml` to give one of them a distinct display name. Re-run `setup_myqa_tests` then `import_myqa`.

### "TestList with slug X doesn't exist"

**Symptom:** Setup or import fails mentioning a missing TestList.

**Cause:** The TaskName has no conditions discovered by any of the 11 execution-type discoverers. The TaskName exists in myQA as metadata but contains no quantitative data — typically a paperwork-only or audit workflow.

**Fix:** None — correctly skipped. The TaskName is in myQA for tracking purposes but has nothing for QATrack+ to import.

### Schedule not firing

**Symptom:** Daily import or weekly setup doesn't run when expected.

**Cause:** django-q2 croniter evaluates cron strings in `settings.TIME_ZONE`, not UTC. `0 2 * * 0` fires at 02:00 **local time** Sundays, not 02:00 UTC. Also check `qcluster` is running: `sudo systemctl status qatrack-qcluster`.

**Fix:** Confirm `TIME_ZONE` is set correctly. Restart qcluster after settings changes: `bash restart_qcluster.sh`.

---

## Need help?

This system is shared internally between hospitals. If you hit something not covered here, contact the sharing centre directly (the high-trust model means a phone call to a colleague is usually faster than filing an issue).

For developer-facing documentation (architecture, gotchas, schema references), see [`AGENTS.md`](../AGENTS.md) and [`docs/sql/`](sql/).
