"""Tests for the weekly ``setup_myqa_tests`` scheduling.

Covers:
- The django-q entry point spawns the management command detached (so the
  long setup isn't killed by the qcluster 60 s task timeout).
- The management command registers the Schedule row idempotently.
"""

from unittest import mock

from django.test import TestCase


class TestSetupMyqaSchedule(TestCase):
    def test_run_setup_myqa_tests_spawns_detached(self):
        from qatrack.qa import tasks

        with mock.patch.object(
            tasks, "_run_setup_detached", return_value={"spawned": True}
        ) as spawn:
            res = tasks.run_setup_myqa_tests()
        assert res["spawned"] is True
        spawn.assert_called_once()

    def test_setup_myqa_setup_schedule_creates_schedule(self):
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("setup_myqa_setup_schedule")
        s = Schedule.objects.get(name="myQA Weekly Setup")
        assert s.func == "qatrack.qa.tasks.run_setup_myqa_tests"
        assert s.schedule_type == Schedule.CRON
        assert s.cron == "0 2 * * 0"  # Sunday 02:00 local time
        assert s.repeats == -1

    def test_setup_myqa_setup_schedule_is_idempotent(self):
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("setup_myqa_setup_schedule")
        call_command("setup_myqa_setup_schedule")
        assert Schedule.objects.filter(name="myQA Weekly Setup").count() == 1
