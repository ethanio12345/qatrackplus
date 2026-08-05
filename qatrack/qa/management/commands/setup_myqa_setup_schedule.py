"""Register a weekly django-q Schedule for ``setup_myqa_tests``.

Creates/updates a single ``Schedule`` row that runs on Sundays at 02:00 UTC
(cron ``0 2 * * 0``). This catches newly-commissioned units (e.g. RFT26) and
new myQA TaskNames that have started accumulating data since the last setup
run, so their UTCs/UTIs exist before the daily import tries to fill them.

Without this, new unit↔TaskName combinations are invisible to the daily
import (``import_session`` returns ``"No UTC for unit X / list Y"`` for
every session until ``setup_myqa_tests`` is run manually).

``setup_myqa_tests`` is idempotent — existing TestLists/UTCs/UTIs are
no-ops via ``get_or_create``. The entry point spawns the management command
as a detached process (see ``qatrack.qa.tasks.run_setup_myqa_tests``)
because the run takes minutes and would otherwise exceed the 60 s qcluster
timeout.

Safe to re-run (idempotent upsert by name).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

SCHEDULE_NAME = "myQA Weekly Setup"
SCHEDULE_FUNC = "qatrack.qa.tasks.run_setup_myqa_tests"
CRON_STRING = "0 2 * * 0"  # Sundays at 02:00 UTC


class Command(BaseCommand):
    help = (
        "Create/update a django-q Schedule that runs setup_myqa_tests weekly "
        "(cron %s) to pick up new unit<->TaskName combinations." % CRON_STRING
    )

    def handle(self, *args, **opts):
        obj, created = Schedule.objects.update_or_create(
            name=SCHEDULE_NAME,
            defaults={
                "func": SCHEDULE_FUNC,
                "schedule_type": Schedule.CRON,
                "cron": CRON_STRING,
                "repeats": -1,
                "next_run": timezone.now(),
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "%s schedule %s (func=%s, cron=%s)"
                % (
                    "Created" if created else "Updated",
                    obj.name,
                    SCHEDULE_FUNC,
                    CRON_STRING,
                )
            )
        )
        self.stdout.write(
            "The schedule will run weekly via cron %s. Review in Django admin "
            "(/admin/django_q/schedule/)." % CRON_STRING
        )
