"""Restore TestLists / Tests / TestListInstances / TestInstances from an old
PostgreSQL backup (Oct 2022) into the current database.

The old backup contains manually-entered physics QA data (Solid Water, MPC,
CatPhan, etc.) that was never in myQA. It is imported as-is: old TestLists
retain their original names and test structures, and coexist with the
myQA-sourced TestLists from setup_myqa_tests (specs/old-db-restore).

Strategy (design D7):

1. Create a temporary database.
2. ``pg_restore`` the custom-format backup into it (preserves the original
   schema, including any columns that differ from the current schema).
3. Read rows from the temp DB via psycopg2 with explicit column lists, so
   missing/extra columns in the old schema are tolerated gracefully.
4. Bulk-insert into the current database via Django ORM in FK-safe order
   (TestList, Test, TestListMembership, UnitTestCollection, UnitTestInfo,
   TestListInstance, TestInstance). All primary keys are remapped to new
   auto-generated values; FK relationships are preserved through the
   remapping (specs/old-db-restore R3).
5. Unit references are validated against the current Unit table; rows
   pointing at units that no longer exist are skipped with a warning
   (specs/old-db-restore R4).
6. Drop the temporary database.

The import uses ``bulk_create(batch_size=5000)`` for the multi-million-row
TestInstance table (specs/old-db-restore R5).
"""

import os
import subprocess
import sys

import psycopg2
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from qatrack.qa.models import (
    Test,
    TestInstance,
    TestInstanceStatus,
    TestList,
    TestListInstance,
    TestListMembership,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.units.models import Unit

BATCH_SIZE = 5000
INTERNAL_USERNAME = "QATrack+ Internal"


def _admin_dsn() -> str:
    """Build a psycopg2 DSN for the postgres maintenance database.

    Uses the same host/user/password as ``settings.DATABASES['default']`` but
    targets the ``postgres`` maintenance DB (required for CREATE DATABASE).
    """
    cfg = settings.DATABASES["default"]
    host = cfg.get("HOST") or "localhost"
    user = cfg.get("USER") or ""
    password = cfg.get("PASSWORD") or ""
    return f"host={host} user={user} password={password} dbname=postgres"


def _temp_db_name() -> str:
    return f"qatrack_old_import_{os.getpid()}"


def _create_temp_db(name: str) -> None:
    conn = psycopg2.connect(_admin_dsn())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
            cur.execute(f'CREATE DATABASE "{name}"')
    finally:
        conn.close()


def _drop_temp_db(name: str) -> None:
    conn = psycopg2.connect(_admin_dsn())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Kick any lingering connections so DROP succeeds.
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        conn.close()


def _pg_restore(backup_file: str, db_name: str) -> None:
    """Run pg_restore to load ``backup_file`` into ``db_name``.

    Uses ``--no-owner --no-privileges`` so the restore doesn't fail on role
    mismatches. pg_restore exit code is intentionally not checked — the old
    schema may have minor incompatibilities (indexes, comments) that produce
    stderr warnings but still load all the data we care about.
    """
    cfg = settings.DATABASES["default"]
    host = cfg.get("HOST") or "localhost"
    user = cfg.get("USER") or ""
    password = cfg.get("PASSWORD") or ""
    env = dict(os.environ, PGPASSWORD=password)
    cmd = [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--host",
        host,
        "--username",
        user,
        "--dbname",
        db_name,
        backup_file,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)


def _temp_dsn(db_name: str) -> str:
    cfg = settings.DATABASES["default"]
    host = cfg.get("HOST") or "localhost"
    return (
        f"host={host} user={cfg.get('USER', '')} "
        f"password={cfg.get('PASSWORD', '')} dbname={db_name}"
    )


def _fetch_rows_with_id(temp_dsn: str, table: str, columns: list[str]) -> list[dict]:
    """Read ``id`` + ``columns`` from ``table`` in the temp DB.

    Always includes ``id`` as the first selected column so callers can build
    FK remap tables. Missing columns (relative to the old schema) are silently
    omitted from the SELECT — those fields will be absent from each row dict.
    Returns ``[]`` if the table doesn't exist.
    """
    conn = psycopg2.connect(temp_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s",
                (table,),
            )
            existing = {r[0] for r in cur.fetchall()}
            if not existing:
                return []
            select_cols = ["id"] + [c for c in columns if c in existing]
            col_sql = ", ".join(f'"{c}"' for c in select_cols)
            cur.execute(f'SELECT {col_sql} FROM public."{table}" ORDER BY id')
            return [
                {select_cols[i]: val for i, val in enumerate(row)}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


class Command(BaseCommand):
    help = (
        "Restore TestLists / Tests / TestListInstances / TestInstances from "
        "an old (Oct 2022) PostgreSQL custom-format backup into the current "
        "database. Old TestLists (Solid Water, MPC, CatPhan, etc.) are "
        "preserved as-is with ID remapping. Uses a temporary database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the pg_dump custom-format backup file (.custom / .backup)",
        )
        parser.add_argument(
            "--keep-temp-db",
            action="store_true",
            default=False,
            help="Keep the temporary database after import (for debugging)",
        )
        parser.add_argument(
            "--skip-confirm",
            action="store_true",
            default=False,
            help="Skip the interactive confirmation prompt",
        )

    def handle(self, *args, **options):
        backup_file = options["file"]
        if not os.path.exists(backup_file):
            raise CommandError(f"Backup file not found: {backup_file}")

        skip_confirm = options.get("skip_confirm", False)
        keep_temp = options.get("keep_temp_db", False)

        if not skip_confirm:
            self.stdout.write(
                self.style.WARNING(
                    f"\nAbout to restore old backup data from:\n  {backup_file}\n"
                    f"into the current database. Old TestLists/Tests will be "
                    f"re-created with new IDs.\n"
                )
            )
            answer = input("Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                self.stdout.write(self.style.NOTICE("Aborted."))
                return

        temp_db = _temp_db_name()
        self.stdout.write(f"Creating temporary database {temp_db} ...")
        _create_temp_db(temp_db)
        try:
            self.stdout.write(f"Restoring backup into {temp_db} ...")
            _pg_restore(backup_file, temp_db)
            self._do_import(_temp_dsn(temp_db))
        finally:
            if keep_temp:
                self.stdout.write(
                    self.style.NOTICE(
                        f"Keeping temporary database {temp_db} for debugging."
                    )
                )
            else:
                self.stdout.write(f"Dropping temporary database {temp_db} ...")
                _drop_temp_db(temp_db)

    @staticmethod
    def _val(row: dict, name: str, default=None):
        return row.get(name, default)

    def _do_import(self, temp_dsn: str) -> None:
        internal_user = User.objects.get(username=INTERNAL_USERNAME)
        default_status = TestInstanceStatus.objects.get(is_default=True)
        ct_testlist = ContentType.objects.get_for_model(TestList)

        current_unit_by_number = {u.number: u for u in Unit.objects.all()}
        self.stdout.write(
            f"Current DB has {len(current_unit_by_number)} units and "
            f"{TestList.objects.count()} TestLists."
        )

        # 1. TestLists ----------------------------------------------------
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_testlist",
            ["name", "slug", "description"],
        )
        if not rows:
            self.stdout.write(
                self.style.WARNING(
                    "No qa_testlist rows found in backup — nothing to import."
                )
            )
            return
        testlist_map: dict[int, int] = {}
        new_count = 0
        with transaction.atomic():
            for row in rows:
                old_id = row["id"]
                name = self._val(row, "name") or f"Old TestList {old_id}"
                slug = self._val(row, "slug") or f"old_testlist_{old_id}"
                existing = TestList.objects.filter(slug=slug).first()
                if existing is not None:
                    testlist_map[old_id] = existing.pk
                    continue
                tl = TestList(
                    name=name,
                    slug=slug,
                    description=self._val(row, "description") or "",
                    created_by=internal_user,
                    modified_by=internal_user,
                )
                tl.save()
                testlist_map[old_id] = tl.pk
                new_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"  TestLists: imported {new_count} new, {len(testlist_map)} total in remap."
            )
        )

        # 2. Tests --------------------------------------------------------
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_test",
            ["name", "slug", "description", "type", "category_id"],
        )
        test_map: dict[int, int] = {}
        new_count = 0
        with transaction.atomic():
            for row in rows:
                old_id = row["id"]
                name = self._val(row, "name") or f"Old Test {old_id}"
                slug = self._val(row, "slug") or f"old_test_{old_id}"
                # Slug / name collisions with existing Tests (e.g. from
                # setup_myqa_tests): append the old id so the import is
                # lossless. Test.name is UNIQUE so the name must change too.
                if Test.objects.filter(slug=slug).exists():
                    slug = f"{slug}_old{old_id}"
                if Test.objects.filter(name=name).exists():
                    name = f"{name} (old {old_id})"
                test = Test(
                    name=name,
                    slug=slug,
                    description=self._val(row, "description"),
                    type=self._val(row, "type") or "numerical",
                    category_id=self._val(row, "category_id") or 1,
                    created_by=internal_user,
                    modified_by=internal_user,
                )
                test.save()
                test_map[old_id] = test.pk
                new_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"  Tests: imported {new_count} new, {len(test_map)} total in remap."
            )
        )

        # 3. TestListMemberships -----------------------------------------
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_testlistmembership",
            ["test_list_id", "test_id", "order"],
        )
        if rows:
            buffer: list[TestListMembership] = []
            skipped = 0
            with transaction.atomic():
                for row in rows:
                    new_tl = testlist_map.get(row.get("test_list_id"))
                    new_t = test_map.get(row.get("test_id"))
                    if new_tl is None or new_t is None:
                        skipped += 1
                        continue
                    buffer.append(
                        TestListMembership(
                            test_list_id=new_tl,
                            test_id=new_t,
                            order=self._val(row, "order") or 0,
                        )
                    )
                    if len(buffer) >= BATCH_SIZE:
                        TestListMembership.objects.bulk_create(
                            buffer, batch_size=BATCH_SIZE
                        )
                        buffer = []
                if buffer:
                    TestListMembership.objects.bulk_create(
                        buffer, batch_size=BATCH_SIZE
                    )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Memberships: imported {len(rows) - skipped} (skipped {skipped} orphans)."
                )
            )

        # 4. UnitTestCollections -----------------------------------------
        # Build old_unit_id -> unit.number lookup from the temp DB.
        old_unit_id_to_number = self._fetch_unit_numbers(temp_dsn)
        utc_map: dict[int, int] = {}
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_unittestcollection",
            ["unit_id", "object_id", "frequency_id"],
        )
        skipped_units = 0
        for row in rows:
            old_utc_id = row["id"]
            unit_number = old_unit_id_to_number.get(row.get("unit_id"))
            unit = current_unit_by_number.get(unit_number) if unit_number else None
            new_tl = testlist_map.get(row.get("object_id"))
            if unit is None or new_tl is None:
                skipped_units += 1
                continue
            utc, _created = UnitTestCollection.objects.get_or_create(
                unit=unit,
                content_type=ct_testlist,
                object_id=new_tl,
                defaults={"active": True, "auto_schedule": True},
            )
            utc_map[old_utc_id] = utc.pk
        self.stdout.write(
            self.style.SUCCESS(
                f"  UTCs: mapped {len(utc_map)} (skipped {skipped_units} orphans "
                f"/ unknown units)."
            )
        )

        # 5. UnitTestInfos -----------------------------------------------
        uti_map: dict[int, int] = {}
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_unittestinfo",
            ["unit_id", "test_id"],
        )
        skipped_uti = 0
        with transaction.atomic():
            for row in rows:
                old_uti_id = row["id"]
                unit_number = old_unit_id_to_number.get(row.get("unit_id"))
                unit = current_unit_by_number.get(unit_number) if unit_number else None
                new_test = test_map.get(row.get("test_id"))
                if unit is None or new_test is None:
                    skipped_uti += 1
                    continue
                uti, _created = UnitTestInfo.objects.get_or_create(
                    unit=unit,
                    test_id=new_test,
                    tolerance=None,
                )
                uti_map[old_uti_id] = uti.pk
        self.stdout.write(
            self.style.SUCCESS(
                f"  UTIs: mapped {len(uti_map)} (skipped {skipped_uti} orphans)."
            )
        )

        # 6. TestListInstances -------------------------------------------
        tli_map: dict[int, int] = {}
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_testlistinstance",
            [
                "unit_test_collection_id",
                "test_list_id",
                "work_started",
                "work_completed",
                "day",
            ],
        )
        new_count = 0
        skipped_tli = 0
        with transaction.atomic():
            for row in rows:
                old_tli_id = row["id"]
                new_utc = utc_map.get(row.get("unit_test_collection_id"))
                new_tl = testlist_map.get(row.get("test_list_id"))
                if new_utc is None or new_tl is None:
                    skipped_tli += 1
                    continue
                tli = TestListInstance(
                    unit_test_collection_id=new_utc,
                    test_list_id=new_tl,
                    work_started=row.get("work_started"),
                    work_completed=row.get("work_completed"),
                    day=self._val(row, "day") or 0,
                    created_by=internal_user,
                    modified_by=internal_user,
                    modified=row.get("work_completed"),
                )
                tli.save()
                tli_map[old_tli_id] = tli.pk
                new_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"  TestListInstances: imported {new_count} (skipped {skipped_tli} orphans)."
            )
        )

        # 7. TestInstances — the big one (3.3M rows) ---------------------
        rows = _fetch_rows_with_id(
            temp_dsn,
            "qa_testinstance",
            [
                "test_list_instance_id",
                "unit_test_info_id",
                "value",
                "string_value",
                "pass_fail",
                "status_id",
                "work_started",
                "work_completed",
                "order",
            ],
        )
        if rows:
            buffer: list[TestInstance] = []
            imported = 0
            skipped = 0
            with transaction.atomic():
                for row in rows:
                    new_tli = tli_map.get(row.get("test_list_instance_id"))
                    new_uti = uti_map.get(row.get("unit_test_info_id"))
                    if new_tli is None or new_uti is None:
                        skipped += 1
                        continue
                    buffer.append(
                        TestInstance(
                            test_list_instance_id=new_tli,
                            unit_test_info_id=new_uti,
                            value=row.get("value"),
                            string_value=row.get("string_value"),
                            pass_fail=row.get("pass_fail") or "no_tol",
                            status=default_status,
                            work_started=row.get("work_started"),
                            work_completed=row.get("work_completed"),
                            created_by=internal_user,
                            modified_by=internal_user,
                            order=row.get("order") or 0,
                        )
                    )
                    if len(buffer) >= BATCH_SIZE:
                        TestInstance.objects.bulk_create(buffer, batch_size=BATCH_SIZE)
                        imported += len(buffer)
                        buffer = []
                if buffer:
                    TestInstance.objects.bulk_create(buffer, batch_size=BATCH_SIZE)
                    imported += len(buffer)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  TestInstances: imported {imported} (skipped {skipped} orphans)."
                )
            )

        self.stdout.write(self.style.SUCCESS("\nImport complete."))

    @staticmethod
    def _fetch_unit_numbers(temp_dsn: str) -> dict:
        """Return ``{old_unit_id: unit_number}`` from the temp DB."""
        conn = psycopg2.connect(temp_dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, number FROM public.qa_unit")
                return {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()
