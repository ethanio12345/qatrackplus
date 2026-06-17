# Production Deployment Runbook — fix-myqa-importers

> **Audience:** QATrack+ production administrator with myQA SQL Server access.
>
> **Scope:** This runbook covers deployment of the `develop-myqa-fix-importers`
> branch to production, including the per-type data backfill and django-q
> Schedule migration. All 22 OpenSpec tasks are addressed (15 code tasks
> complete + verified; 7 operational tasks executed via this runbook).
>
> **Estimated time:** 2–4 hours (dominated by Numeric backfill of ~3,670 sessions).
>
> **Risk level:** Medium — touches main-spec daily lists (`myqa_daily_*`,
> `myqa_dxr_daily`). A database backup is required before starting.

---

## 1. Executive Summary

This change fixes all 7 broken myQA importers and rewrites the setup command
to actually create the QATrack+ objects the import engine needs (TestList,
Test, Tolerance, TestListMembership, UnitTestCollection, **and UnitTestInfo** —
the last was missing entirely and silently dropped 100% of imports).

After deployment, the import engine will correctly populate QATrack+ with
historical myQA data covering approximately:

| Type | Sessions | Priority |
|---|---|---|
| Numeric (Daily QA — 3 lists) | ~3,670 | High |
| Winston Lutz | ~400 | Medium |
| MLC | ~252 | Medium |
| VMAT | ~247 | Medium |
| CBCT | ~46 | Low |
| Planar | ~4 | Low |
| PassFail | (unknown) | Low |

The previously-broken `myqa_numeric` aggregate key is replaced by three
explicit keys: `numeric_constancy`, `numeric_physics`, `numeric_dxr`.

---

## 2. Pre-Deployment Checklist (REQUIRED)

Run **all** of these before touching production. Each is a hard prerequisite.

### 2.1 Database backup

```bash
# On the production database host (adjust per your DB engine):
# PostgreSQL example:
pg_dump -U qatrack qatrackplus > /backups/qatrackplus-pre-myqa-fix-$(date +%Y%m%d-%H%M).sql

# Verify the backup is non-trivial in size:
ls -lh /backups/qatrackplus-pre-myqa-fix-*.sql
```

If the backup step fails or the file is suspiciously small, **STOP**.

### 2.2 Confirm no in-flight django-q jobs

```bash
uv run python manage.py shell <<'EOF'
from django_q.models import Schedule, Task
# Show scheduled jobs
for s in Schedule.objects.all():
    print(f"  {s.func} | next_run={s.next_run} | owner={s.id}")
# Show recently-failed tasks (last 24h)
from django.utils import timezone
from datetime import timedelta
recent = Task.objects.filter(
    stopped__gte=timezone.now() - timedelta(days=1),
    success=False,
)
print(f"\nFailed tasks in last 24h: {recent.count()}")
EOF
```

If any `myqa_*` Schedule has `next_run` within the next hour, wait for it to
fire or disable it temporarily.

### 2.3 Confirm myQA SQL Server reachability

```bash
uv run python manage.py shell <<'EOF'
import pymssql
from django.conf import settings
conn = pymssql.connect(
    server=settings.MYQA_DB_SERVER,
    database=settings.MYQA_DB_NAME,
    user=settings.MYQA_DB_USERNAME,
    password=settings.MYQA_DB_PASSWORD,
)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM MQA_TestExecutions")
print(f"myQA TestExecutions count: {cur.fetchone()[0]}")
conn.close()
EOF
```

If this fails with a connection error, **STOP** — production QATrack+ cannot
reach the myQA database.

### 2.4 Pre-flight check for orphan TestInstances (Task 8.3 part 2)

```bash
uv run python manage.py shell <<'EOF'
from qatrack.qa.models import TestInstance, TestList

# Proposal Non-goal: broken setup never created the 'myqa_numeric' TestList,
# so the engine's get() would have raised DoesNotExist. Verify no orphan
# data exists from any earlier attempted runs.
try:
    bad_list = TestList.objects.get(slug='myqa_numeric')
    orphan_count = TestInstance.objects.filter(
        test_list_instance__test_list=bad_list
    ).count()
    print(f"WARN: 'myqa_numeric' TestList exists with {orphan_count} TestInstances")
    print("      Document this and decide cleanup before proceeding.")
except TestList.DoesNotExist:
    print("OK: no 'myqa_numeric' TestList — expected per proposal Non-goals.")
EOF
```

### 2.5 Confirm main-spec lists can be safely `--force`-d

```bash
uv run python manage.py shell <<'EOF'
from qatrack.qa.models import TestListInstance, TestList

# These three lists already exist in production (per frozen main spec).
# `--force` will delete their Tests and TestListMemberships.
main_spec_slugs = (
    'myqa_daily_constancy',
    'myqa_daily_physics',
    'myqa_dxr_daily',
)
for slug in main_spec_slugs:
    try:
        tl = TestList.objects.get(slug=slug)
        tli_count = TestListInstance.objects.filter(test_list=tl).count()
        print(f"  {slug}: {tli_count} existing TestListInstances")
        if tli_count > 0:
            print(f"    WARN: --force will DELETE {tli_count} TLIs' Tests (not the TLIs themselves)")
    except TestList.DoesNotExist:
        print(f"  {slug}: does not exist yet (safe to --force)")
EOF
```

If any of these lists have TestListInstances you can't afford to lose, **STOP**
and coordinate with the physicists before proceeding.

---

## 3. Deployment

### 3.1 Pull and migrate

```bash
# On the production QATrack+ host:
cd /path/to/qatrackplus
git fetch origin
git checkout develop-myqa-fix-importers
# OR if you've merged to develop per gitflow:
# git checkout develop && git pull --no-ff origin develop

# Verify branch:
git log --oneline -3
# Expect to see:
#   45cb79a6 feat(myqa): rewrite 7 importers + setup command per verified schema
#   6d67c2c1 fix(migrations): merge conflicting leaf nodes in parts/reports/units

# Apply migrations (the 3 merge migrations + any others pending):
uv run python manage.py migrate

# Run Django's system check:
uv run python manage.py check
```

### 3.2 Verify code deployed correctly

```bash
uv run python manage.py shell <<'EOF'
from qatrack.myqa_import import TASK_TYPE_REGISTRY, UNITS_PER_LIST

# Registry should have 13 entries, no 'myqa_numeric', 3 new 'numeric_*'
assert 'myqa_numeric' not in TASK_TYPE_REGISTRY, "old myqa_numeric key still present"
for key in ('numeric_constancy', 'numeric_physics', 'numeric_dxr',
            'myqa_passfail', 'myqa_mlc', 'myqa_cbct', 'myqa_planar',
            'myqa_vmat', 'myqa_winston_lutz'):
    assert key in TASK_TYPE_REGISTRY, f"missing {key}"

print(f"Registry OK ({len(TASK_TYPE_REGISTRY)} entries):")
for k, cls in sorted(TASK_TYPE_REGISTRY.items()):
    print(f"  {k:25s} -> {cls.__name__} (list={cls.list_slug})")

print(f"\nUNITS_PER_LIST has {len(UNITS_PER_LIST)} entries")
EOF
```

### 3.3 Verify tests pass on production host (optional but recommended)

```bash
uv run pytest qatrack/qa/tests/test_myqa_import.py qatrack/qa/tests/test_setup_myqa_tests.py -v
# Expect: 53 passed
```

---

## 4. Backfill Procedure

> **CRITICAL:** Run setup (`--force`) for each type BEFORE running the import.
> The import engine silently drops TestInstances for slugs lacking a Test or
> UTI (`myqa_import.py:209-213`); without setup, zero data would be imported.

### 4.1 Numeric (3 lists) — ~3,670 sessions, run first

```bash
for TYPE in numeric_constancy numeric_physics numeric_dxr; do
    echo ""
    echo "=========================================="
    echo "  Processing $TYPE"
    echo "=========================================="

    # Step 1: dry-run to preview discovered Tests
    uv run python manage.py setup_myqa_tests --dry-run --task-type $TYPE

    # Step 2: force setup (creates TestList, Tests, Tolerances, Memberships,
    # UTCs, UTIs). On main-spec lists this DELETES existing Tests by slug
    # prefix — that's expected; we verified preconditions in §2.5.
    uv run python manage.py setup_myqa_tests --force --task-type $TYPE

    # Step 3: backfill 365 days
    uv run python manage.py import_myqa_results --task $TYPE --days 365

    # Step 4: re-run to verify dedup (expect 0 new imports)
    echo "Verifying dedup for $TYPE (expect 0 new)..."
    uv run python manage.py import_myqa_results --task $TYPE --days 365
done
```

### 4.2 Winston-Lutz — ~400 sessions

```bash
uv run python manage.py setup_myqa_tests --dry-run --task-type myqa_winston_lutz
uv run python manage.py setup_myqa_tests --force --task-type myqa_winston_lutz
uv run python manage.py import_myqa_results --task myqa_winston_lutz --days 365
uv run python manage.py import_myqa_results --task myqa_winston_lutz --days 365  # expect 0 new
```

### 4.3 MLC — ~252 sessions

```bash
uv run python manage.py setup_myqa_tests --dry-run --task-type myqa_mlc
uv run python manage.py setup_myqa_tests --force --task-type myqa_mlc
uv run python manage.py import_myqa_results --task myqa_mlc --days 365
uv run python manage.py import_myqa_results --task myqa_mlc --days 365  # expect 0 new
```

### 4.4 VMAT — ~247 sessions

```bash
uv run python manage.py setup_myqa_tests --dry-run --task-type myqa_vmat
uv run python manage.py setup_myqa_tests --force --task-type myqa_vmat
uv run python manage.py import_myqa_results --task myqa_vmat --days 365
uv run python manage.py import_myqa_results --task myqa_vmat --days 365  # expect 0 new
```

### 4.5 CBCT — ~46 sessions

```bash
uv run python manage.py setup_myqa_tests --dry-run --task-type myqa_cbct
uv run python manage.py setup_myqa_tests --force --task-type myqa_cbct
uv run python manage.py import_myqa_results --task myqa_cbct --days 365
uv run python manage.py import_myqa_results --task myqa_cbct --days 365  # expect 0 new
```

### 4.6 Planar — ~4 sessions

```bash
uv run python manage.py setup_myqa_tests --dry-run --task-type myqa_planar
uv run python manage.py setup_myqa_tests --force --task-type myqa_planar
uv run python manage.py import_myqa_results --task myqa_planar --days 365
uv run python manage.py import_myqa_results --task myqa_planar --days 365  # expect 0 new
```

### 4.7 PassFail — count unknown

> **Verify before running:** the existing `task_name_patterns`
> (`['5.Tmt.Linac.P%', '5.Tmt.DXR.P%']`) was inherited unchanged. If these
> patterns don't match actual myQA PassFail TaskNames, the import will find
> zero sessions. Confirm by querying myQA first:

```bash
uv run python manage.py shell <<'EOF'
import pymssql
from django.conf import settings
conn = pymssql.connect(
    server=settings.MYQA_DB_SERVER,
    database=settings.MYQA_DB_NAME,
    user=settings.MYQA_DB_USERNAME,
    password=settings.MYQA_DB_PASSWORD,
)
cur = conn.cursor(as_dict=True)
cur.execute("""
    SELECT DISTINCT TaskName, COUNT(*) AS cnt
    FROM MQA_TestExecutions
    WHERE TaskName LIKE '5.Tmt.%P%' AND TaskName NOT LIKE '%Planar%'
    GROUP BY TaskName
    ORDER BY cnt DESC
""")
for row in cur.fetchall():
    print(f"  {row['cnt']:5d}  {row['TaskName']}")
conn.close()
EOF
```

If the output suggests different patterns are needed, update
`MyqaPassFailImport.task_name_patterns` in `qatrack/myqa_import.py` and
redeploy before running:

```bash
uv run python manage.py setup_myqa_tests --force --task-type myqa_passfail
uv run python manage.py import_myqa_results --task myqa_passfail --days 365
uv run python manage.py import_myqa_results --task myqa_passfail --days 365  # expect 0 new
```

---

## 5. django-q Schedule Migration (Task 8.3)

The previous `myqa_numeric` aggregate key is gone. Any django-q `Schedule`
rows referencing it must be migrated to the 3 new keys (one per Numeric list).

### 5.1 Inspect existing schedules

```bash
uv run python manage.py shell <<'EOF'
from django_q.models import Schedule
import json

print("Current django-q Schedules:")
for s in Schedule.objects.all():
    print(f"  id={s.id} name={s.name!r}")
    print(f"    func={s.func}")
    print(f"    args={s.args}")
    print(f"    kwargs={s.kwargs}")
    print(f"    cron={s.cron} | next_run={s.next_run}")
    print("")
EOF
```

### 5.2 Migrate myqa_numeric schedules

Locate any Schedule whose `args`/`kwargs` reference `task_type='myqa_numeric'`
or `myqa_numeric`. For each one found, you need **three** replacement
Schedules (one per Numeric list) running at the same cron.

Example migration script (review output before uncommenting the `.save()` lines):

```bash
uv run python manage.py shell <<'EOF'
from django_q.models import Schedule
from django.db.models import Q

# Find old schedules referencing the removed aggregate key
candidates = Schedule.objects.filter(
    Q(args__contains='myqa_numeric') |
    Q(kwargs__contains='myqa_numeric') |
    Q(name__icontains='myqa_numeric')
)
print(f"Found {candidates.count()} candidate schedule(s) to migrate:")
for s in candidates:
    print(f"  id={s.id} name={s.name!r} func={s.func} args={s.args} kwargs={s.kwargs}")

# For each candidate, create 3 new schedules (one per Numeric list):
NEW_KEYS = ('numeric_constancy', 'numeric_physics', 'numeric_dxr')
for s in candidates:
    for key in NEW_KEYS:
        new_name = f"{s.name} ({key})"
        if Schedule.objects.filter(name=new_name).exists():
            print(f"  SKIP {new_name} (already exists)")
            continue
        new_s = Schedule(
            name=new_name,
            func=s.func,
            args=s.args.replace('myqa_numeric', key),
            kwargs=s.kwargs.replace('myqa_numeric', key) if s.kwargs else s.kwargs,
            cron=s.cron,
            schedule_type=s.schedule_type,
            repeats=s.repeats,
        )
        # DRY RUN: comment out the next line after reviewing
        # new_s.save()
        print(f"  WOULD CREATE: {new_name}")

# After verifying the new schedules exist and fire correctly, delete the old ones:
# for s in candidates:
#     print(f"  DELETE {s.name} (id={s.id})")
#     # s.delete()
EOF
```

**Verify after migration** that the new schedules fire correctly (wait for the
next cron tick or trigger them manually from `/admin/django_q/schedule/`).

---

## 6. Success Criteria

After all backfills complete, verify the QATrack+ DB has the expected data:

```bash
uv run python manage.py shell <<'EOF'
from qatrack.qa.models import TestList, TestListInstance

expected = {
    'myqa_daily_constancy': 'part of ~3,670 total across 3 numeric lists',
    'myqa_daily_physics':   'part of ~3,670 total across 3 numeric lists',
    'myqa_dxr_daily':       'part of ~3,670 total across 3 numeric lists',
    'myqa_winston_lutz':    '~400',
    'myqa_mlc':             '~252',
    'myqa_vmat':            '~247',
    'myqa_cbct':            '~46',
    'myqa_planar':          '~4 (low volume)',
    'myqa_passfail':        'count depends on actual myQA data',
}

print(f"{'TestList':<28s} {'TLIs':>8s}  Expected")
print("-" * 70)
for slug, expected_str in expected.items():
    try:
        tl = TestList.objects.get(slug=slug)
        count = TestListInstance.objects.filter(test_list=tl).count()
        print(f"{slug:<28s} {count:>8d}  {expected_str}")
    except TestList.DoesNotExist:
        print(f"{slug:<28s} {'MISSING':>8s}  {expected_str}")

# Combined numeric total
numeric_total = sum(
    TestListInstance.objects.filter(
        test_list__slug=slug
    ).count()
    for slug in ('myqa_daily_constancy', 'myqa_daily_physics', 'myqa_dxr_daily')
)
print(f"\nNumeric combined TLIs: {numeric_total} (expected ~3,670)")
EOF
```

**Note:** Counts may differ from estimates based on:
- Actual `--days 365` window vs your myQA data age
- Whether all configured units have been performing each QA type
- `IsDeleted` filtering (deferred per O4 — see design.md)

---

## 7. Rollback Procedure

If anything goes wrong, the impact is scoped per list. Recovery options:

### 7.1 Per-list rollback (most common)

To undo a single type's setup + import:

```bash
uv run python manage.py shell <<'EOF'
from qatrack.qa.models import Test, TestList, TestListMembership, UnitTestInfo, TestListInstance

LIST_SLUG = 'myqa_mlc'  # CHANGE to the list you need to roll back

tl = TestList.objects.get(slug=LIST_SLUG)

# Delete all TLIs (and their TestInstances via cascade) imported for this list
deleted_tlis, _ = TestListInstance.objects.filter(test_list=tl).delete()
print(f"Deleted {deleted_tlis} TestListInstances for {LIST_SLUG}")

# Delete UTIs + Memberships + Tests created by setup (preserves any pre-existing data)
TestListMembership.objects.filter(test_list=tl).delete()
old_test_ids = Test.objects.filter(slug__startswith=f"{LIST_SLUG}_").values_list("pk", flat=True)
UnitTestInfo.objects.filter(test_id__in=old_test_ids).delete()
Test.objects.filter(slug__startswith=f"{LIST_SLUG}_").delete()
print(f"Rolled back setup for {LIST_SLUG}")
EOF
```

Then restore that list's setup + data from the backup if needed.

### 7.2 Full rollback to pre-deployment state

```bash
# Restore from the backup taken in §2.1
# PostgreSQL example:
dropdb qatrackplus && createdb qatrackplus
psql qatrackplus < /backups/qatrackplus-pre-myqa-fix-YYYYMMDD-HHMM.sql

# Revert the code:
git checkout develop  # or the previous production tag
uv run python manage.py migrate
```

### 7.3 Code-only rollback (keep data, revert just the importer code)

If you need to disable the new importers without losing the data already
imported (e.g., to investigate an issue):

```bash
git revert 45cb79a6  # the feat commit
git push origin develop-myqa-fix-importers
# Redeploy
```

The existing TestInstances remain in the DB; only future imports stop running
until you re-deploy the fix.

---

## 8. Known Caveats

These are documented in `design.md` Open Question resolutions and `tasks.md`
Status Summary, repeated here for production visibility.

### 8.1 VMAT ROI slugs contain periods

VMAT ROI slugs look like `myqa_vmat_2.0_cm_s_mean` — periods are preserved
by `slugify_name` (regex `[^a-z0-9.]+`). If QATrack+ URL routing rejects
periods in test slugs, edit `clean_roi_name()` in `qatrack/myqa_import.py`
to strip them:

```python
def clean_roi_name(name: str) -> str:
    return (name or "").strip("[]").replace(".", "_")
```

Then re-run the VMAT backfill with `--force`.

### 8.2 PassFail task_name_patterns unverified

The existing `['5.Tmt.Linac.P%', '5.Tmt.DXR.P%']` patterns were inherited
from the broken importer and may not match actual myQA PassFail TaskNames.
Run the verification query in §4.7 before backfilling PassFail.

### 8.3 Verdict not stored (D4 deferred)

The import engine hardcodes `pass_fail='no_tol'` for every TestInstance
(`myqa_import.py:226`). Source `*_Verdict` columns are not stored. This is a
deliberate Non-goal — verdict storage requires an engine write-path change
that's out of scope. Tolerances created during setup are not enforced on
imported data without a separate pass.

### 8.4 `IsDeleted` filter not applied (O4 deferred)

The engine does not filter `MQA_TestExecutions.IsDeleted`. If any deleted
executions exist in myQA, they will be imported. Documented as Open Question
O4 in `design.md`; deferred to a future change.

### 8.5 UTC (UnitTestCollection) scoping

Setup creates UTCs only for units listed in `UNITS_PER_LIST` (see
`qatrack/myqa_import.py`). DXR (unit 50) only gets the `myqa_dxr_daily` UTC;
other lists are linac-only (units 1, 2, 3, 4, 5, 7, 8). This is by design
(MLC/CBCT/Planar/VMAT/WL/PassFail are not performed on the orthovoltage unit).

---

## 9. Reference

- **OpenSpec change:** `openspec/changes/fix-myqa-importers/`
  - `proposal.md` — scope, data volumes, decisions D1–D4
  - `design.md` — full technical design, per-pattern query definitions
  - `specs/{numeric,winston-lutz,mlc,vmat,cbct,planar,passfail}/spec.md` — per-type requirements + scenarios
  - `tasks.md` — task checklist with status notes
  - `schema-reference.md` — verified myQA schema (source of truth for column names)
- **Frozen main spec:** `openspec/specs/myqa-sync/spec.md` (note: line 42
  scenario has an erroneous period-stripped slug — separate OpenSpec sync
  needed to correct it).
- **Tests:** `qatrack/qa/tests/test_myqa_import.py` (45 unit tests) +
  `qatrack/qa/tests/test_setup_myqa_tests.py` (8 integration tests).
- **Branch:** `develop-myqa-fix-importers`
- **Commits:** `6d67c2c1` (migration merge) + `45cb79a6` (implementation)

---

## 10. Quick Reference Command Summary

```bash
# Pre-flight (§2)
# 1. Backup DB
# 2. Confirm myQA reachable
# 3. Check for orphan myqa_numeric data
# 4. Check main-spec lists safe to --force

# Deploy (§3)
git fetch origin && git checkout develop-myqa-fix-importers
uv run python manage.py migrate
uv run python manage.py check

# Backfill per type (§4) — Numeric first
for TYPE in numeric_constancy numeric_physics numeric_dxr \
            myqa_winston_lutz myqa_mlc myqa_vmat \
            myqa_cbct myqa_planar myqa_passfail; do
    uv run python manage.py setup_myqa_tests --force --task-type $TYPE
    uv run python manage.py import_myqa_results --task $TYPE --days 365
done

# django-q migration (§5)
# Inspect, then create 3 new schedules per old myqa_numeric schedule

# Verify (§6)
uv run python manage.py shell -c "<see §6 script>"
```
