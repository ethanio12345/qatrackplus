---
description: Run the full myQA setup + import pipeline (clear, setup, import)
---

Run the full myQA pipeline to refresh TestLists, Tests, UTCs, UTIs, and session data from the myQA database.

**Input**: Optionally specify a lookback window in days (default: 3650 for full history, or 30 for a quick test).

**Steps**

1. **Confirm with the user**

   Ask the user to confirm. This deletes ALL existing myQA TestListInstances and rebuilds the TestLists/Tests from scratch. The user should take a DB backup first:
   ```
   pg_dump qatrackplus31 > backup_pre_myqa_refresh.sql
   ```

2. **Determine the lookback window**

   If the user specified a number of days, use that. Otherwise ask:
   - `30` — quick test (last month only)
   - `3650` — full history (~10 years, takes ~10-15 min)

3. **Clear existing myQA data**

   ```bash
   uv run python manage.py clear_myqa_data --yes
   ```

   This deletes all TestLists/Tests/UTCs/UTIs/TestListInstances/TestInstances created by the myQA import system in FK-safe order.

4. **Discover and create TestLists/Tests/UTCs/UTIs**

   ```bash
   uv run python manage.py setup_myqa_tests
   ```

   This connects to the myQA database, discovers all TaskNames and conditions, and creates one TestList per TaskName with shared Tests. Generates `docs/myqa_test_mapping.{csv,md}`.

   **Fresh DB note**: If the QATrack+ `Unit` table doesn't yet contain the
   units referenced in `myqa_device_map.yaml`, setup will create
   TestLists/Tests but **zero UTCs/UTIs** (it prints "Unit number N not
   found — skipping"). Run this first to populate units:
   ```bash
   uv run python manage.py create_myqa_units
   uv run python manage.py setup_myqa_tests
   ```

   **Optional**: Run with `--dry-run` first to preview:
   ```bash
   uv run python manage.py setup_myqa_tests --dry-run
   ```

5. **Import session data**

   ```bash
   uv run python manage.py import_myqa --days {days}
   ```

   This imports all sessions within the lookback window. Expect:
   - Thousands of sessions imported
   - Many duplicates (sessions shared across TaskNames)
   - Some empty sessions (no extractable data)
   - Some errors (pre-existing myQA data issues — review if count changes)

6. **Verify the import**

   Check the summary line for `Skipped (err)`. If error count is unexpectedly high, investigate:
   ```bash
   uv run python manage.py shell -c "
   from qatrack.qa.models import TestListInstance, TestInstance
   from django.contrib.contenttypes.models import ContentType
   from qatrack.qa.models import UnitTestCollection, TestList
   ct = ContentType.objects.get_for_model(TestList)
   utc_ids = UnitTestCollection.objects.filter(content_type=ct).values_list('pk', flat=True)
   tlis = TestListInstance.objects.filter(unit_test_collection_id__in=utc_ids)
   tis = TestInstance.objects.filter(test_list_instance__in=tlis)
   print(f'{tlis.count()} TLIs, {tis.count()} TIs')
   "
   ```

7. **Deploy to production (if working in dev)**

   If the user is working in the dev repo and wants to push to production.
   Production is a git clone at `/home/bchcphysics/web/qatrackplus/` tracking
   `origin/develop`.

   **First-time only** (fixes venv ownership — requires sudo password):
   ```bash
   bash /home/bchcphysics/Github/qatrackplus/deploy_to_prod.sh --first
   ```

   **Routine deploys** (code changes only):
   ```bash
   bash /home/bchcphysics/Github/qatrackplus/deploy_to_prod.sh
   ```

   The script does: `git fetch` → `git reset --hard origin/develop` →
   `uv sync` → `manage.py check` → restart qcluster + apache.

   Then run steps 3-5 against the production directory using the production
   venv: `cd /home/bchcphysics/web/qatrackplus && .venv/bin/python manage.py ...`

8. **Restart services (production only)**

   The deploy script (`deploy_to_prod.sh`) handles this automatically. If you
   ran the pipeline manually against production:
   ```bash
   sudo systemctl restart qatrack-qcluster
   sudo systemctl reload apache2
   ```
