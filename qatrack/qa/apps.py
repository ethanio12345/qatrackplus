from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _l


def do_scheduling(sender, **kwargs):
    from django_q.models import Schedule

    from qatrack.qatrack_core.tasks import _schedule_periodic_task

    _schedule_periodic_task(
        "qatrack.qa.tasks.clean_autosaves",
        "QATrack+ Autosave Cleaner",
        schedule_type=Schedule.DAILY,
        next_run=timezone.localtime(
            timezone.now() + timezone.timedelta(hours=24)
        ).replace(hour=4),
    )

    _schedule_periodic_task(
        "qatrack.qa.tasks.import_myqa_all",
        "myQA Full Import",
        schedule_type=Schedule.DAILY,
        next_run=timezone.localtime(
            timezone.now() + timezone.timedelta(hours=24)
        ).replace(hour=18),
    )

    # Weekly setup: catches new unit↔TaskName combinations so the daily
    # import doesn't silently drop sessions for unmapped units. Spawns
    # ``manage.py setup_myqa_tests`` as a detached process (per AGENTS.md
    # gotcha #7 — setup takes minutes, exceeds qcluster's 60s timeout).
    # Cron evaluated in settings.TIME_ZONE (not UTC) by django-q2 croniter.
    # No try/except — django_q tables are ready here (django_q is listed
    # before qatrack.qa in INSTALLED_APPS so its migrations run first), and
    # silently swallowing failures would let the schedule quietly never
    # register, which manifests later as "No UTC for unit X / list Y" errors
    # when new units go live.
    Schedule.objects.update_or_create(
        name="myQA Weekly Setup",
        defaults={
            "func": "qatrack.qa.tasks.run_setup_myqa_tests",
            "schedule_type": Schedule.CRON,
            "cron": "0 2 * * 0",  # Sundays 02:00 local time
            "repeats": -1,
        },
    )


def rebuild_trees(sender, **kwargs):
    from qatrack.qa.models import Category

    Category.objects.rebuild()


class QAAppConfig(AppConfig):
    name = "qatrack.qa"
    verbose_name = _l("QC")

    def ready(self):
        post_migrate.connect(do_scheduling, sender=self)
        post_migrate.connect(rebuild_trees, sender=self)
