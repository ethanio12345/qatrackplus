from django.test import TestCase

from qatrack.qa import models
from qatrack.qa.tests import utils


class TestAutoApprove(TestCase):
    """TestListInstance.auto_approve should mark a TLI reviewed iff every
    TestInstance is within tolerance (auto-approves via the ruleset)."""

    def _setup(self, values):
        """Create a TLI whose tests have the given values; ref=1, abs tol [-1,1]
        so value in [0,2]->OK, else action. Returns (tli, default_status)."""
        default = utils.create_status(name="default", slug="default", requires_review=True, is_default=True)
        approved = utils.create_status(name="approved", slug="approved", requires_review=False)

        rule = models.AutoReviewRule.objects.create(pass_fail=models.OK, status=approved)
        ruleset = models.AutoReviewRuleSet.objects.create(name="default", is_default=True)
        ruleset.rules.add(rule)

        ref = utils.create_reference(value=1)
        tol = utils.create_tolerance()  # ABSOLUTE, tol [-1,1], act [-2,2]

        test_list = utils.create_test_list()
        tests = []
        for _ in values:
            test = utils.create_test()
            test.autoreviewruleset_id = ruleset.id
            test.save()
            utils.create_test_list_membership(test_list, test)
            tests.append(test)

        # UTC creation auto-creates UnitTestInfos for the test_list's tests.
        utc = utils.create_unit_test_collection(test_collection=test_list)
        tli = utils.create_test_list_instance(unit_test_collection=utc)

        for v, test in zip(values, tests):
            uti = models.UnitTestInfo.objects.get(test=test, unit=utc.unit)
            ti = utils.create_test_instance(tli, unit_test_info=uti, value=v, status=default)
            ti.reference = ref
            ti.tolerance = tol
            ti.calculate_pass_fail()
            ti.save()
        return tli, default, approved

    def test_all_within_tolerance_is_auto_approved(self):
        tli, default, approved = self._setup([1.0, 1.0])  # both == ref -> OK
        assert tli.all_reviewed is False
        result = tli.auto_approve()
        assert result is True
        tli.refresh_from_db()
        assert tli.all_reviewed is True
        assert tli.reviewed is not None
        assert all(ti.status_id == approved.pk for ti in tli.testinstance_set.all())

    def test_one_failing_test_stays_unreviewed(self):
        tli, default, approved = self._setup([1.0, 10.0])  # 10 is action (out of tol)
        result = tli.auto_approve()
        assert result is False
        tli.refresh_from_db()
        assert tli.all_reviewed is False
        assert tli.reviewed is None
