# Design: Full myQA Sync

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐
│   myQA DB       │◄────│  myqa_import.py      │
│   (MSSQL)       │     │  - MyqaSessionCollector│
│   read-only     │     │  - Execution handlers  │
└─────────────────┘     │  - Tolerance mapper    │
                        └──────┬───────────────┘
                               │
                        ┌──────▼───────────────┐
                        │  QATrack+ ORM         │
                        │  - TestListInstance   │
                        │  - TestInstance       │
                        │  - de-dup by taskid   │
                        └──────────────────────┘

┌─────────────────┐     ┌──────────────────────┐
│  django-q        │────►│  import_myqa_all()   │
│  Schedule.DAILY  │     │  (qatrack/qa/tasks.py)│
│  6pm AEST        │     └──────────────────────┘
└─────────────────┘
```

## Import Engine (`myqa_import.py`)

Class-based, mirroring the existing `matrix_import.py` pattern:

```python
class MyqaImportBase:
    """Base class for myQA task type imports."""

    # Subclasses define:
    task_name_patterns: list[str]     # myQA TaskName LIKE patterns
    list_slug: str                     # QATrack+ test list slug
    frequency: str                     # Daily|Weekly|Monthly|...
    execution_type: str                # Numeric|PassFail|Profile|...

    def query_new_sessions(self, days, unit_numbers):
        """Query MQA_TestExecutions for new data."""

    def extract_results(self, execution_id):
        """Extract test results from the specific detail tables."""

    def import_session(self, myqa_execution, unit, day):
        """Create TLI + TIs in QATrack+."""

    def duplicate_check(self, execution_id):
        """Check mtx_taskid string_value."""
```

### Tolerance mapping

```python
def myqa_to_qatrack_tolerance(warn_on, fail_on, bounding_type, is_relative, limit_tendency):
    """Convert myQA tolerance spec to QATrack+ Tolerance object."""
    if is_relative:
        tol_type = 'percent'
    else:
        tol_type = 'absolute'

    if limit_tendency == 0:  # two-sided
        tol_lower = -warn_on
        tol_upper = +warn_on
    elif limit_tendency == 1:  # lower only
        tol_lower = -fail_on
        tol_upper = None
    elif limit_tendency == 2:  # upper only
        tol_lower = None
        tol_upper = fail_on
```

### Slug generation

```python
def myqa_name_to_slug(list_slug, name):
    """Convert myQA test name to QATrack+ slug."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9.]+', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_')
    return f'{list_slug}_{slug}'
```

## Setup script (`setup_myqa_tests.py`)

One-time management command that:
1. Queries myQA for DISTINCT test names per task type
2. Creates Test objects with `myqa_` prefixed slugs
3. Creates Tolerance objects from Warn/Fail values
4. Creates TestList + TestListMembership
5. Creates UnitTestCollection per unit

## Query strategy

Date-bounded queries using `te.FinishingDate` or `te.ReferenceDate`:

```sql
SELECT te.* FROM MQA_TestExecutions te
WHERE te.TaskName IN ({patterns})
AND te.RadiationDeviceName LIKE ?
AND te.ReferenceDate >= ?
AND te.ReferenceDate <= ?
AND NOT EXISTS (
    SELECT 1 FROM ...
    WHERE string_value = te.Id  -- de-dup
)
```

## Error handling

- Per-session transaction: each TLI creation wrapped in `atomic()`
- On failure: log error, continue to next session
- Collect summary: total found, total imported, total skipped, total errors
