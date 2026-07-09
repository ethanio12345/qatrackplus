"""Register django-q Schedules for monthly PDF production (no email).

Creates/updates two ``Schedule`` rows that run on the 1st of each month
(cron ``0 7 1 * *``), mirroring the existing myQA Schedule #7 pattern. By
default the rendered zips are written to the ``pdf`` folder (see
``qatrack.reports.qa_archive.default_out_dir``) and **no email is sent**.

Safe to re-run (idempotent upsert by name).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

ARCHIVE_SCHEDULE = {
    "name": "Linac QA Archive Monthly",
    "func": "qatrack.reports.tasks.run_linac_qa_archive",
}

DAILY_SCHEDULE = {
    "name": "Daily Constancy PDF Bundle (Monthly)",
    "func": "qatrack.reports.tasks.run_daily_qa_bundle",
}

CRON_STRING = "0 7 1 * *"  # 07:00 on day 1 of each month


class Command(BaseCommand):
    help = (
        "Create/update django-q Schedules for monthly linac QA PDF production "
        "(cron %s). Writes zips to a pdf folder; no email unless --email-group."
    ) % CRON_STRING

    def add_arguments(self, parser):
        parser.add_argument(
            "--out-dir",
            type=str,
            default=None,
            help="Folder to write the zips into (default: <repo>/pdf).",
        )
        parser.add_argument(
            "--email-group",
            type=str,
            default=None,
            help="Also email the zip to this Group name (default: no email).",
        )
        parser.add_argument(
            "--window",
            type=str,
            default="lastmonth",
            help="Window arg passed to the tasks (default: lastmonth).",
        )

    def _kwargs(self, opts):
        # Only bake out_dir into the schedule if explicitly given; otherwise let
        # the entry point resolve default_out_dir() at runtime so each
        # environment (dev/prod) writes to its own <repo>/pdf folder.
        parts = ['"window": "%s"' % opts["window"]]
        if opts.get("out_dir"):
            parts.append('"out_dir": "%s"' % opts["out_dir"])
        if opts.get("email_group"):
            parts.append('"email_group": "%s"' % opts["email_group"])
        return "{%s}" % ", ".join(parts)

    def _upsert(self, cfg, kwargs):
        obj, created = Schedule.objects.update_or_create(
            name=cfg["name"],
            defaults={
                "func": cfg["func"],
                "schedule_type": Schedule.CRON,
                "cron": CRON_STRING,
                "repeats": -1,
                "kwargs": kwargs,
                "next_run": timezone.now(),
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "%s schedule %s (kwargs=%s)"
                % ("Created" if created else "Updated", obj.name, kwargs)
            )
        )

    def handle(self, *args, **opts):
        kwargs = self._kwargs(opts)
        self._upsert(ARCHIVE_SCHEDULE, kwargs)
        self._upsert(DAILY_SCHEDULE, kwargs)
        self.stdout.write(
            "Both schedules will run monthly via cron %s. Review in Django admin "
            "(/admin/django_q/schedule/)." % CRON_STRING
        )
