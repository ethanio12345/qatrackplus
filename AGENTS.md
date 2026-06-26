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

### Management commands

| Command | Purpose |
|---------|---------|
| `setup_myqa_tests` | Discover TaskNames + create TestLists/Tests/UTCs/UTIs. `--dry-run` to preview. |
| `import_myqa --days N` | Import sessions. `--task-name` for single TaskName. |
| `clear_myqa_data --yes` | Delete all myQA-sourced data in FK-safe order. |
| `import_old_qatrack --file` | Restore old QATrack+ backup (Solid Water, MPC, CatPhan). |

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

### Gotchas (prevent regressions)

1. **`multi` flag must be TaskName-level, not per-session.** `compute_multi_flags()` computes once per batch; passed to all extractors via `multi_override`. Extractors that use it: `extract_numeric`, `extract_profile`, `_extract_pattern_b`, `extract_vmat`, `extract_winston_lutz`.

2. **Discover functions must return `[]` when no data exists** for that execution type. `_discover_pattern_b_conditions` and `discover_winston_lutz_conditions` previously returned full metric lists, creating spurious tests in unrelated TestLists.

3. **VMAT "Normalization Value" is never prefixed** by test-step name, even when `multi=True`. `discover_vmat_conditions` emits it unprefixed (shared Test).

4. **Duplicate TaskNames in myQA** (e.g. `"Dosimetry - Monthly QA"` vs `"Dosimetry - Monthly QA (1)"`) are a myQA data issue. Each gets its own TestList.

5. **Naive datetime RuntimeWarnings** from myQA are harmless (Django auto-converts with `USE_TZ=True`).

## OpenSpec

```bash
openspec list --json
openspec status --change "<name>" --json
openspec instructions apply --change "<name>" --json
```

Active and archived changes under `openspec/changes/`. Design docs for the myQA redesign at `openspec/changes/myqa-dynamic-taskname-import/`.

## Ruff config

- Selects: `E, F, I, UP, DJ`.
- Ignores: `E501` (line length), `E741`, `DJ001`, `DJ006`, `DJ007`, `DJ008`, `UP031`.
- Excludes: `fixtures/`, `migration_data/`, `migrations/`, `south_migrations/`, `node_modules/`, `media/`, `static/`, `*tmp*`.
