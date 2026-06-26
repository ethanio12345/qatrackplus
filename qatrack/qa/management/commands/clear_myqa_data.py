"""Clear all myQA-sourced data so the new dynamic-discovery system can rebuild.

Implements the FK-safe delete order from design D8 of the
myqa-dynamic-taskname-import change. Deletes:

* TestLists whose slug starts with ``myqa_``, equals ``matrix-dosimetry-import``,
  OR whose description matches the dynamic-discovery pattern
  (``Auto-created TestList for myQA TaskName …``).
* Tests that are members of those TestLists, or whose slug starts with
  ``myqa_`` / ``mtx_``.
* All TestInstances / TestListInstances / UnitTestCollections / UnitTestInfos
  attached to the above

The delete order avoids FK constraint violations:

1. Null out ``UnitTestCollection.last_instance`` for affected UTCs.
2. Delete ``TestInstance`` rows under affected TestListInstances.
3. Delete ``TestListInstance`` rows for affected TestLists.
4. Delete ``UnitTestInfo`` rows for affected Tests.
5. Delete ``UnitTestCollection`` rows pointing at affected TestLists.
6. Delete ``TestListMembership`` rows for affected TestLists.
7. Delete ``Test`` rows by membership / slug prefix.
8. Delete ``TestList`` rows by slug / description pattern.

ALWAYS take a PostgreSQL backup before running this (task 1.3):
``pg_dump qatrackplus31 > backup_pre_redesign.sql``
"""

from django.core.management.base import BaseCommand

from qatrack.qa.models import (
    Test,
    TestInstance,
    TestList,
    TestListInstance,
    TestListMembership,
    UnitTestCollection,
    UnitTestInfo,
)

# Description pattern set by setup_myqa_tests for dynamically-discovered lists.
_MYQA_DESC_PREFIX = "Auto-created TestList for myQA TaskName"


def _affected_test_list_ids() -> set[int]:
    ids = set(
        TestList.objects.filter(slug__startswith="myqa_").values_list("pk", flat=True)
    )
    ids.update(
        TestList.objects.filter(slug="matrix-dosimetry-import").values_list(
            "pk", flat=True
        )
    )
    # Dynamic discovery: identify by description pattern (TaskName-based slugs
    # have no consistent prefix, so the description is the reliable marker).
    ids.update(
        TestList.objects.filter(description__startswith=_MYQA_DESC_PREFIX).values_list(
            "pk", flat=True
        )
    )
    return ids


def _affected_test_ids() -> set[int]:
    # Tests that are members of affected TestLists (catches taskid tests too).
    ids = set(
        TestListMembership.objects.filter(
            test_list_id__in=_affected_test_list_ids()
        ).values_list("test_id", flat=True)
    )
    # Also old slug-prefix tests (legacy importer era).
    ids.update(
        Test.objects.filter(slug__startswith="myqa_").values_list("pk", flat=True)
    )
    ids.update(
        Test.objects.filter(slug__startswith="mtx_").values_list("pk", flat=True)
    )
    return ids


class Command(BaseCommand):
    help = (
        "Delete all myQA-sourced TestLists/Tests/TestInstances/UTCs/UTIs "
        "(slugs starting with myqa_/mtx_ or equal to matrix-dosimetry-import). "
        "DANGEROUS: take a pg_dump backup before running."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report counts that would be deleted, no DB writes",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Skip the interactive confirmation prompt",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        skip_confirm = options.get("yes", False)

        test_list_ids = _affected_test_list_ids()
        test_ids = _affected_test_ids()

        if not test_list_ids and not test_ids:
            self.stdout.write(
                self.style.NOTICE(
                    "No myQA-sourced TestLists/Tests found (nothing to clear)."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {len(test_list_ids)} affected TestList(s) and "
                f"{len(test_ids)} affected Test(s)."
            )
        )

        # Pre-compute counts for the dry-run / confirm prompt.
        tli_ids = set(
            TestListInstance.objects.filter(test_list_id__in=test_list_ids).values_list(
                "pk", flat=True
            )
        )
        ti_count = TestInstance.objects.filter(
            test_list_instance_id__in=tli_ids
        ).count()
        utc_count = UnitTestCollection.objects.filter(
            object_id__in=test_list_ids
        ).count()
        uti_count = UnitTestInfo.objects.filter(test_id__in=test_ids).count()
        membership_count = TestListMembership.objects.filter(
            test_list_id__in=test_list_ids
        ).count()

        self.stdout.write(
            f"  TestListInstances: {len(tli_ids)}\n"
            f"  TestInstances:     {ti_count}\n"
            f"  UTCs:              {utc_count}\n"
            f"  UTIs:              {uti_count}\n"
            f"  Memberships:       {membership_count}\n"
            f"  Tests:             {len(test_ids)}\n"
            f"  TestLists:         {len(test_list_ids)}"
        )

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry-run only — no deletes performed."))
            return

        if not skip_confirm:
            answer = input("\nType 'yes' to confirm deletion of ALL the above data: ")
            if answer.strip().lower() != "yes":
                self.stdout.write(self.style.NOTICE("Aborted."))
                return

        # D8 delete order. Uses raw SQL (not ORM .delete()) because:
        #   1. ORM cascade pre-checks on 200K+ rows are extremely slow.
        #   2. The ORM missed the UnitTestCollection.visible_to M2M through
        #      table, causing FK violations.
        # The order is FK-safe (children before parents). Each DELETE
        # auto-commits, releasing locks between steps.
        from django.db import connection

        with connection.cursor() as cur:
            # Pre-compute affected IDs into temp tables BEFORE any deletes.
            # Otherwise the membership-dependent subquery returns nothing
            # after memberships are deleted.
            cur.execute(
                "CREATE TEMP TABLE _tl_ids AS "
                "SELECT id FROM qa_testlist "
                "WHERE slug LIKE 'myqa_%%' "
                "  OR slug = 'matrix-dosimetry-import' "
                "  OR description LIKE 'Auto-created TestList for myQA TaskName%%'"
            )
            cur.execute(
                "CREATE TEMP TABLE _test_ids AS "
                "SELECT DISTINCT test_id AS id FROM qa_testlistmembership "
                "WHERE test_list_id IN (SELECT id FROM _tl_ids) "
                "UNION "
                "SELECT id FROM qa_test "
                "WHERE slug LIKE 'myqa_%%' OR slug LIKE 'mtx_%%'"
            )
            cur.execute(
                "CREATE TEMP TABLE _tli_ids AS "
                "SELECT id FROM qa_testlistinstance "
                "WHERE test_list_id IN (SELECT id FROM _tl_ids)"
            )

            def _tl_ids() -> str:
                return "SELECT id FROM _tl_ids"

            def _test_ids() -> str:
                return "SELECT id FROM _test_ids"

            def _tli_ids() -> str:
                return "SELECT id FROM _tli_ids"

            self.stdout.write("Step 1/11: nulling UTC.last_instance references...")
            cur.execute(
                f"UPDATE qa_unittestcollection SET last_instance_id = NULL "
                f"WHERE last_instance_id IN ({_tli_ids()})"
            )

            self.stdout.write("Step 2/11: deleting TestInstances...")
            cur.execute(
                f"DELETE FROM qa_testinstance "
                f"WHERE test_list_instance_id IN ({_tli_ids()})"
                f"   OR unit_test_info_id IN ("
                f"     SELECT id FROM qa_unittestinfo"
                f"     WHERE test_id IN ({_test_ids()})"
                f"   )"
            )
            self.stdout.write(f"  deleted {cur.rowcount} TestInstance rows")

            self.stdout.write("Step 3/11: deleting TestListInstances...")
            cur.execute(f"DELETE FROM qa_testlistinstance WHERE id IN ({_tli_ids()})")
            self.stdout.write(f"  deleted {cur.rowcount} TestListInstance rows")

            self.stdout.write("Step 4/11: deleting UnitTestInfoChanges...")
            cur.execute(
                f"DELETE FROM qa_unittestinfochange "
                f"WHERE unit_test_info_id IN ("
                f"  SELECT id FROM qa_unittestinfo"
                f"  WHERE test_id IN ({_test_ids()})"
                f")"
            )
            self.stdout.write(f"  deleted {cur.rowcount} UTIChange rows")

            self.stdout.write("Step 5/11: deleting UnitTestInfos...")
            cur.execute(f"DELETE FROM qa_unittestinfo WHERE test_id IN ({_test_ids()})")
            self.stdout.write(f"  deleted {cur.rowcount} UnitTestInfo rows")

            self.stdout.write("Step 6a/11: clearing UTC.visible_to M2M...")
            cur.execute(
                f"DELETE FROM qa_unittestcollection_visible_to "
                f"WHERE unittestcollection_id IN ("
                f"  SELECT id FROM qa_unittestcollection"
                f"  WHERE object_id IN ({_tl_ids()})"
                f")"
            )
            self.stdout.write(f"  deleted {cur.rowcount} visible_to rows")

            self.stdout.write("Step 6/11: deleting UnitTestCollections...")
            cur.execute(
                f"DELETE FROM qa_unittestcollection "
                f"WHERE object_id IN ({_tl_ids()})"
            )
            self.stdout.write(f"  deleted {cur.rowcount} UTC rows")

            self.stdout.write("Step 7/11: deleting TestListMemberships...")
            cur.execute(
                f"DELETE FROM qa_testlistmembership "
                f"WHERE test_list_id IN ({_tl_ids()})"
            )
            self.stdout.write(f"  deleted {cur.rowcount} Membership rows")

            self.stdout.write("Step 8/11: deleting Attachments...")
            cur.execute(
                f"DELETE FROM attachments_attachment "
                f"WHERE test_id IN ({_test_ids()})"
            )
            self.stdout.write(f"  deleted {cur.rowcount} Attachment rows")

            self.stdout.write("Step 9/11: deleting Tests...")
            cur.execute(f"DELETE FROM qa_test WHERE id IN ({_test_ids()})")
            self.stdout.write(f"  deleted {cur.rowcount} Test rows")

            self.stdout.write("Step 10/11: deleting TestLists...")
            cur.execute(f"DELETE FROM qa_testlist WHERE id IN ({_tl_ids()})")
            self.stdout.write(f"  deleted {cur.rowcount} TestList rows")

            self.stdout.write("Step 11/11: vacuuming (optional, skipped)...")
            # VACUUM can't run inside a transaction; skip it. The user can
            # run `VACUUM ANALYZE qa_testinstance;` manually after.

        self.stdout.write(
            self.style.SUCCESS(
                "Cleared all myQA-sourced data. Ready to run setup_myqa_tests."
            )
        )
