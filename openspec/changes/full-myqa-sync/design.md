# Design: Full myQA Sync

> Decisions, model facts, and tolerance tables in `explore-brief.md` are
> binding on this document. This design extends the existing
> `MatrixResultImporter` pattern in `qatrack/matrix_import.py` (class at
> line 34, entry point `import_matrix_results` at line 532).

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐
│   myQA DB       │◄────│  myqa_import.py      │
│   (MSSQL)       │     │  - MyqaImportBase     │
│   read-only     │     │  - 11 type handlers   │
│   (pymssql)     │     │  - tolerance mapper   │
└─────────────────┘     └──────┬───────────────┘
                               │
                        ┌──────▼───────────────┐
                        │  QATrack+ ORM         │
                        │  - TestListInstance   │
                        │  - TestInstance       │
                        │  - de-dup by single   │
                        │    shared slug +      │
                        │    string_value=      │
                        │    TaskExecutionId    │
                        └──────────────────────┘

┌─────────────────┐     ┌──────────────────────┐
│  django-q       │────►│  import_myqa_all()    │
│  DAILY          │     │  (qatrack/qa/tasks.py)│
│  18:00          │     └──────────────────────┘
│  Australia/Sydney│
└─────────────────┘
```

## Import Engine (`myqa_import.py`)

Class-based, mirroring the existing `MatrixResultImporter` pattern
(`matrix_import.py:34`). The base class holds the shared myQA-connect,
query, de-dup, and ORM-persistence logic; subclasses implement only the
detail-table extraction that differs per execution type.

```python
class MyqaImportBase:
    """Base class for myQA task type imports."""

    # Subclasses define:
    task_name_patterns: list[str]     # myQA TaskName LIKE/IN patterns
    list_slug: str                     # QATrack+ TestList slug
    frequency: str                     # 'daily' | 'weekly' | ... (Frequency.slug)
    execution_type: str                # Numeric|PassFail|Profile|...

    def __init__(self):
        # unit number -> myQA RadiationDeviceName (mirror matrix_import.py:386-400)
        self.unit_to_device = { ... }

    def connect(self):
        """pymssql.connect(server=MYQA_DB_SERVER, database=MYQA_DB_NAME,
                           user=MYQA_DB_USERNAME, password=MYQA_DB_PASSWORD)."""

    def query_new_sessions(self, days, unit_numbers):
        """Date-bounded query on MQA_TestExecutions (see SQL below).
        Returns rows not yet imported (de-duped by NOT EXISTS subquery)."""

    def extract_results(self, execution_id):
        """ABSTRACT — subclass reads its detail table and returns
        [(test_slug, value, string_value), ...]."""

    def duplicate_check(self, execution_id):
        """Return True if already imported. Looks up TestInstance where
        unit_test_info__test__slug == DEDUP_SLUG
        AND unit_test_info__unit__number == unit
        AND string_value == str(execution_id)."""

    def import_session(self, myqa_execution, unit, day):
        """Create TLI + TIs in a per-session transaction.atomic()."""
```

`DEDUP_SLUG` is the single shared slug `'myqa_taskid'` for new task types,
reusing the existing `'mtx_taskid'` slug for the consolidated monthly matrix
task type (see "De-duplication" below).

### Tolerance mapping

QATrack+ `Tolerance` values are **offsets from the reference value** and the
engine stores **two bands**: `tol_*` (warn → "TOLERANCE" status when breached)
and `act_*` (fail → "ACTION" status when breached). See `explore-brief.md` for
the full evaluation pseudocode. Per maintainer decision: `WarnOn → tol_*`,
`FailOn → act_*`.

```python
def myqa_to_qatrack_tolerance(warn_on, fail_on, is_relative, limit_tendency):
    """Convert a myQA tolerance spec to a QATrack+ Tolerance (two-band offsets).

    limit_tendency: 0 = two-sided, 1 = lower-only, 2 = upper-only
    is_relative:    0 = absolute,                1 = percent (base = reference.value)
    """
    tol_type = 'percent' if is_relative else 'absolute'

    if limit_tendency == 0:          # two-sided
        tol_low,  tol_high  = -warn_on,  +warn_on
        act_low,  act_high  = -fail_on,  +fail_on
    elif limit_tendency == 1:        # lower-only (value must not fall below ref)
        tol_low,  tol_high  = -warn_on,  None
        act_low,  act_high  = -fail_on,  None
    elif limit_tendency == 2:        # upper-only (value must not rise above ref)
        tol_low,  tol_high  = None,      +warn_on
        act_low,  act_high  = None,      +fail_on
    return Tolerance(type=tol_type,
                     tol_low=tol_low, tol_high=tol_high,
                     act_low=act_low, act_high=act_high)
```

Unset bounds become ±1E99 inside `TestInstance.float_pass_fail`
(`models.py:2137-2157`), i.e. no bound on that side. The full mapping table
(including the `is_relative` × `limit_tendency` matrix) is in `explore-brief.md`.

### Slug generation

```python
def myqa_name_to_slug(list_slug, name):
    """Convert a myQA test name to a QATrack+ slug (dots stripped)."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)   # NOTE: dots are NOT preserved
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_')
    return f'{list_slug}_{slug}'
```

`1.01 6MV Output` → `myqa_daily_physics_1_01_6mv_output`. Dots are collapsed to
underscores (matches the spec scenario and standard slug conventions; avoids any
QATrack+ slug-field validation surprise).

### De-duplication

One shared QATrack+ `Test` object per import family acts as the de-dup marker:

- Slug `mtx_taskid` (existing) for the consolidated monthly matrix task type.
- Slug `myqa_taskid` (new, created by the setup script) for all other task types.

On import, one extra `TestInstance` per session is written with
`string_value = str(myQA TaskExecutionId)` against that Test. The next run's
`NOT EXISTS` subquery (below) and `duplicate_check()` skip already-imported
sessions. This reuses the exact pattern at `matrix_import.py:361-373` and
`tasks.py:137-141`.

> myQA `TaskExecutionId` is an **integer**, cast to `str` for storage. It is not
> a UUID despite the original draft's wording.

### Unit → device-name mapping

myQA filters on `RadiationDeviceName` (a string), but QATrack+ keys on
`Unit.number`. The base class carries the map (mirroring
`matrix_import.py:386-400`), e.g. `{3: 'LA317 - H192972', ..., 50: 'DXR - GM0191'}`.
`query_new_sessions` resolves `unit_numbers` to device names before binding the
SQL parameter.

## Setup script (`setup_myqa_tests.py`)

One-time management command that:
1. Queries myQA for DISTINCT test names per task type.
2. Creates `Test` objects with `myqa_name_to_slug(...)` slugs (`myqa_`-prefixed).
3. Creates `Tolerance` objects via `myqa_to_qatrack_tolerance(...)` (two-band).
4. Creates `TestList` + `TestListMembership`.
5. Creates `UnitTestCollection` per (unit, frequency), `active=True`.
6. Creates the single de-dup `Test` (slug `myqa_taskid`).
7. Supports `--dry-run` (print plan, write nothing) and `--force` (re-create).

## Query strategy

Date-bounded queries on the header table `MQA_TestExecutions`, filtered by
device name and de-duplicated by a `NOT EXISTS` subquery against the de-dup
slug's `string_value`:

```sql
SELECT te.*
FROM MQA_TestExecutions te
WHERE te.TaskName IN ({patterns})
  AND te.RadiationDeviceName = ?        -- resolved from unit_number
  AND te.ReferenceDate >= ?
  AND te.ReferenceDate <= ?
  AND NOT EXISTS (
        SELECT 1
        FROM QATrack+ TestInstance join ...   -- evaluated in ORM via duplicate_check()
        WHERE de_dup_test_slug == ...
          AND string_value == CAST(te.TaskExecutionId AS VARCHAR)
      )
```

(In practice the `NOT EXISTS` is performed in Python via `duplicate_check()`
against the ORM, matching the existing `MatrixResultImporter` approach — kept as
a SQL comment here for clarity.)

## Detail-table parsing (per execution type)

Each handler implements `extract_results(execution_id)` to read its detail table
and emit `(test_slug, value, string_value)` tuples. The 11 detail tables are
listed in `explore-brief.md` (treated as authoritative, per maintainer decision).
The header → detail join key is the myQA execution id.

Because each detail table has distinct columns, every handler is responsible for:
1. Its own `SELECT` against its detail table (date/id-bounded).
2. Column → slug mapping (stable, deterministic — see "Task name normalisation"
   requirement).
3. Aggregation of sub-tables where a single execution fans out to many rows
   (e.g. MLC leaf pairs, CBCT slices, profile points).

Slug-collision detection is part of the setup script (Task 6): if two distinct
myQA names collapse to the same slug, the script logs a warning and appends a
numeric suffix.

## Task name normalisation

myQA `TaskName` values vary across legacy data (parenthetical suffixes, free-text
notes, casing). A registry maps variant patterns to canonical handler classes.
The registry is data (a dict of compiled-regex → handler), built in its own task
(Task 3) with unit tests, because it is the single most error-prone mapping.

## Error handling

- Per-session transaction: each TLI creation wrapped in `transaction.atomic()`.
- On failure: log the error (Python `logging`, percent-style lazy formatting) and
  continue to the next session.
- Collect a summary: total found, total imported, total skipped (duplicates),
  total errors. Printed by the management command; logged by the cron task.

## Incremental run semantics

Stateless (decision D4). The daily cron calls `import_myqa_all()` with `--days 2`
default, so a missed day is recovered on the next run. De-duplication guarantees
idempotency: re-running a window imports nothing new. The `--days` flag is the
only lookback control; there is no "last successful import" table.

## Scheduling

django-q `Schedule.DAILY` at **18:00 `Australia/Sydney`** (decision D5). django-q
resolves the IANA timezone, so AEST (UTC+10) / AEDT (UTC+11) DST is handled
automatically — the job always fires at 6pm local Sydney time.
