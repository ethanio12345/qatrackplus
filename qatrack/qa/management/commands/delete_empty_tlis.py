"""Delete TestListInstances that were imported with no measurement values.

A TLI is "empty" if it has at least one non-taskid TestInstance but none of them
carry a value (numeric / string / date / datetime all NULL). These come from
myQA sessions that were started/finished without entering readings — QATrack+
is a read-only duplicate of results, so valueless TLIs add nothing and are
deleted here. The forward fix (qatrack.myqa_import.import_session) prevents new
ones; this command cleans up the legacy set.

TestInstances cascade-delete with the TLI (on_delete=CASCADE). A UTC whose
last_instance pointed at a deleted empty TLI is recomputed to its most-recent
remaining TLI. Idempotent.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Exists, OuterRef, Q

from qatrack.qa.models import TestInstance, TestListInstance, UnitTestCollection

NOT_TASKID = ~Q(unit_test_info__test__slug__endswith="_taskid")
HAS_DATA = (
    Q(value__isnull=False)
    | Q(string_value__isnull=False)
    | Q(date_value__isnull=False)
    | Q(datetime_value__isnull=False)
)


def empty_tli_qs():
    """TLIs that have >=1 non-taskid TI but none with any value."""
    has_real = TestInstance.objects.filter(test_list_instance=OuterRef("pk")).filter(
        NOT_TASKID
    )
    has_real_data = (
        TestInstance.objects.filter(test_list_instance=OuterRef("pk"))
        .filter(NOT_TASKID)
        .filter(HAS_DATA)
    )
    return TestListInstance.objects.filter(Exists(has_real)).exclude(
        Exists(has_real_data)
    )


class Command(BaseCommand):
    help = (
        "Delete TestListInstances imported with no measurement values (all tests NULL)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Delete (default: dry run).",
        )

    def handle(self, *args, **opts):
        qs = empty_tli_qs()
        pks = list(qs.values_list("pk", flat=True))
        if not pks:
            self.stdout.write("No empty TestListInstances found.")
            return

        self.stdout.write("Empty TLIs: %d" % len(pks))
        for row in (
            TestListInstance.objects.filter(pk__in=pks)
            .values("test_list__name")
            .annotate(c=Count("id"))
            .order_by("-c")[:12]
        ):
            self.stdout.write("  %-45s %d" % (row["test_list__name"][:43], row["c"]))

        if not opts["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run — no changes. Re-run with --apply to delete."
                )
            )
            return

        # UTCs whose last_instance is about to be cleared by the cascade
        # (on_delete=SET_NULL) — recompute them to the most-recent remaining TLI.
        affected_utc_ids = set(
            TestListInstance.objects.filter(
                pk__in=pks, unit_test_collection__last_instance__in=pks
            )
            .values_list("unit_test_collection_id", flat=True)
            .distinct()
        )

        deleted_n, _ = TestListInstance.objects.filter(pk__in=pks).delete()
        self.stdout.write(
            self.style.SUCCESS(
                "Deleted %d empty TLI(s) (cascade incl. TestInstances)." % len(pks)
            )
        )

        recomputed = 0
        for utc_id in affected_utc_ids:
            latest = (
                TestListInstance.objects.filter(unit_test_collection_id=utc_id)
                .order_by("-work_completed")
                .first()
            )
            UnitTestCollection.objects.filter(pk=utc_id).update(last_instance=latest)
            recomputed += 1
        if recomputed:
            self.stdout.write(
                "Recomputed last_instance for %d affected UTC(s)." % recomputed
            )
