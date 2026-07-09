"""Auto-approve TestListInstances where all tests are within tolerance.

Two paths exist:
  * import-time (``qatrack.myqa_import`` calls ``TestListInstance.auto_approve``)
    handles new imports per-TLI.
  * this command backfills TLIs imported before that, in bulk (fast).

Bulk strategy: for each AutoReviewRule (pass_fail -> status) in each
AutoReviewRuleSet, update the matching TestInstances (whose test uses that
ruleset) in one query, then mark TLIs with no review-required TestInstance as
reviewed. Idempotent.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from qatrack.qa.models import AutoReviewRuleSet, TestInstance, TestListInstance


class Command(BaseCommand):
    help = (
        "Auto-approve TestListInstances where all tests are within tolerance "
        "(per the configured AutoReviewRuleSet)."
    )

    def handle(self, *args, **opts):
        now = timezone.now()
        internal_user = User.objects.filter(username="QATrack+ Internal").first()

        before = TestListInstance.objects.filter(all_reviewed=False).count()
        if before == 0:
            self.stdout.write("No unreviewed TestListInstances to process.")
            return

        # 1. Bulk-apply AutoReviewRule mappings to TestInstances in unreviewed
        #    TLIs. auto_review() skips TIs that have a comment (and aren't
        #    skipped), so we mirror that here.
        tis_updated = 0
        for rs in AutoReviewRuleSet.objects.prefetch_related("rules").iterator():
            for rule in rs.rules.all():
                tis_updated += (
                    TestInstance.objects.filter(
                        test_list_instance__all_reviewed=False,
                        unit_test_info__test__autoreviewruleset=rs,
                        pass_fail=rule.pass_fail,
                    )
                    .exclude(Q(comment__gt="") & Q(skipped=False))
                    .update(status=rule.status, review_date=now)
                )

        # 2. Mark TLIs that now have no review-required TestInstance as reviewed.
        newly_reviewed = TestListInstance.objects.filter(all_reviewed=False).exclude(
            testinstance__status__requires_review=True
        )
        n_reviewed = newly_reviewed.update(
            all_reviewed=True, reviewed=now, reviewed_by=internal_user
        )

        remaining = TestListInstance.objects.filter(all_reviewed=False).count()
        self.stdout.write(
            self.style.SUCCESS(
                "Updated %d TestInstance(s); auto-approved %d TLI(s); %d remain unreviewed."
                % (tis_updated, n_reviewed, remaining)
            )
        )
