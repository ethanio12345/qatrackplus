"""Set every myQA/matrix ``taskid`` TestInstance to the Approved status.

The ``*_taskid`` Tests (e.g. ``<list>_taskid``, ``mtx_taskid``) store the
myQA TaskExecutionId purely for dedup — they are metadata, not clinical data,
so they should not sit in the unreviewed queue. New imports now set them to
Approved automatically (see qatrack.myqa_import); this command backfills the
ones imported before that change. Idempotent.
"""

from django.core.management.base import BaseCommand

from qatrack.qa.models import TestInstance, TestInstanceStatus


class Command(BaseCommand):
    help = "Approve all taskid TestInstances (metadata dedup tests, not clinically relevant)."

    def handle(self, *args, **opts):
        try:
            approved = TestInstanceStatus.objects.get(slug="Approved")
        except TestInstanceStatus.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    "No TestInstanceStatus with slug='Approved' exists; nothing done."
                )
            )
            return

        taskid_tis = TestInstance.objects.filter(
            unit_test_info__test__slug__endswith="_taskid"
        ).exclude(status=approved)
        n = taskid_tis.update(status=approved)
        self.stdout.write(self.style.SUCCESS("Approved %d taskid TestInstance(s)." % n))
