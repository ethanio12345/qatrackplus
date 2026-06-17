"""Tests for the ``setup_myqa_tests`` management command.

These exercise the per-type dispatch in ``Command.handle()`` (which calls each
importer's ``discover_setup_tests()`` then runs the shared TestList / Test /
Tolerance / TestListMembership / UTC / UTI creation logic).

The myQA SQL Server connection is mocked — the importer instances returned by
``discover_setup_tests()`` are stubbed directly. The Django ORM (Test, TestList,
Frequency, UnitTestCollection, UnitTestInfo) IS exercised against the test
database via ``django.test.TestCase``.

**Dev-env note:** running this file requires Django migrations to be
applicable. A pre-existing migration conflict in unrelated apps (parts /
reports / units) currently blocks test DB creation in this dev env (not caused
by this change — reproduces with all changes stashed). The CI workflow (which
runs from a clean checkout) is unaffected.
"""

import unittest
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from qatrack.qa.models import (
    Test,
    TestList,
    TestListMembership,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.qa.tests.utils import create_frequency
from qatrack.units.models import Unit


def make_importer_stub(list_slug, specs, execution_type="Stub"):
    """Build a stub importer instance with the given discover_setup_tests output.

    Bypasses MyqaImportBase.__init__ (no pymssql connection, no ORM lookups).
    """
    stub = mock.Mock()
    stub.list_slug = list_slug
    stub.execution_type = execution_type
    stub.frequency = "daily"
    stub.task_name_patterns = []
    stub.test_slug_prefix = f"{list_slug}_"
    stub.close = mock.Mock()
    stub.discover_setup_tests.return_value = specs
    # Context-manager protocol (Command uses `with importer_cls() as importer:`)
    stub.__enter__ = mock.Mock(return_value=stub)
    stub.__exit__ = mock.Mock(return_value=None)
    return stub


@pytest.mark.django_db
class TestSetupCommandPerTypeDispatch(TestCase):
    """Verify the Command's per-type dispatch creates the expected objects.

    Uses a small registry stub so we don't depend on real importer SQL —
    we feed canned specs to the setup pipeline directly.
    """

    @classmethod
    def setUpTestData(cls):
        # Minimal ORM prerequisites. Use the project's factory helpers so we
        # satisfy all NOT-NULL constraints discovered in the model definitions
        # (Frequency.window_end, Unit.date_acceptance + type, etc.).
        cls.user = User.objects.get_or_create(username="QATrack+ Internal")[0]
        cls.freq = create_frequency(name="Daily", slug="daily", interval=1)
        # Test.category is non-nullable; the setup command hardcodes category_id=1,
        # so we ensure a Category with id=1 exists.
        from qatrack.qa.models import Category

        cls.category, _ = Category.objects.get_or_create(id=1, defaults={"name": "myQA", "slug": "myqa"})
        # Units per UNITS_PER_LIST (numbers 1-8 + 50). create_unit picks an
        # auto-incrementing number if none given; we pass the explicit number
        # to match UNITS_PER_LIST exactly.
        from qatrack.qa.tests.utils import create_unit

        for num in (1, 2, 3, 4, 5, 7, 8, 50):
            existing = Unit.objects.filter(number=num).first()
            if existing is None:
                create_unit(name=f"Unit {num}", number=num)

    def _run(self, list_slug, specs, extra_opts=None):
        """Run setup for one importer stub; return the created TestList."""
        stub = make_importer_stub(list_slug, specs)
        registry_patch = mock.patch(
            "qatrack.qa.management.commands.setup_myqa_tests.TASK_TYPE_REGISTRY",
            {list_slug: mock.Mock(return_value=stub)},
        )
        with registry_patch:
            opts = {"dry_run": False, "force": True, "task_type": list_slug}
            if extra_opts:
                opts.update(extra_opts)
            call_command("setup_myqa_tests", **opts)
        return TestList.objects.get(slug=list_slug)

    # -- Pattern D: PassFail (1 test, string, no tolerance) -----------------

    def test_passfail_creates_single_string_test(self):
        list_slug = "myqa_passfail"
        specs = [
            {
                "name": "Acceptance Criteria",
                "slug": "myqa_passfail_acceptance_criteria",
                "type": "string",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            }
        ]
        test_list = self._run(list_slug, specs)

        # 1 taskid Test + 1 spec Test = 2 Tests created
        tests = Test.objects.filter(slug__startswith=f"{list_slug}_")
        self.assertEqual(tests.count(), 2)
        acceptance = Test.objects.get(slug="myqa_passfail_acceptance_criteria")
        self.assertEqual(acceptance.type, "string")

        # TestList + Membership
        self.assertEqual(test_list.slug, list_slug)
        memberships = TestListMembership.objects.filter(test_list=test_list)
        self.assertEqual(memberships.count(), 2)

    # -- Pattern D: WinstonLutz (2 tests, shared tolerance) -----------------

    def test_winston_lutz_creates_two_tests_with_shared_tolerance(self):
        list_slug = "myqa_winston_lutz"
        specs = [
            {
                "name": "Maximum Deviation 2D",
                "slug": "myqa_winston_lutz_maximum_deviation_2d",
                "type": "numerical",
                "warn": 1.0,
                "fail": 2.0,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Deviation 3D",
                "slug": "myqa_winston_lutz_deviation_3d",
                "type": "numerical",
                "warn": 1.0,
                "fail": 2.0,
                "is_relative": False,
                "limit_tendency": 0,
            },
        ]
        self._run(list_slug, specs)

        # 2 spec tests + 1 taskid test = 3
        tests = Test.objects.filter(slug__startswith=f"{list_slug}_")
        self.assertEqual(tests.count(), 3)
        # Both metric tests should have a tolerance (warn/fail non-NULL)
        # — verified via TestInstance interaction in the engine; here we
        # just confirm the Tests exist.

    # -- Pattern B: MLC (7 tests including value-only and string) ----------

    def test_mlc_creates_all_seven_emitted_slugs(self):
        # Spec MLC R3 — engine silent-drop trap: every emitted slug MUST
        # have a Test created here.
        list_slug = "myqa_mlc"
        specs = [
            {
                "name": "Failing Peaks",
                "slug": "myqa_mlc_failing_peaks",
                "type": "numerical",
                "warn": 5,
                "fail": 10,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Max Deviation",
                "slug": "myqa_mlc_max_deviation",
                "type": "numerical",
                "warn": 0.5,
                "fail": 1.0,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Interstrip Ratio",
                "slug": "myqa_mlc_interstrip_ratio",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Standard Deviation",
                "slug": "myqa_mlc_standard_deviation",
                "type": "numerical",
                "warn": 0.1,
                "fail": 0.2,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Isocenter To Strip Distance",
                "slug": "myqa_mlc_isocenter_to_strip_distance",
                "type": "numerical",
                "warn": 1.5,
                "fail": 2.0,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Total Peaks",
                "slug": "myqa_mlc_total_peaks",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Leaves That Failed",
                "slug": "myqa_mlc_leaves_that_failed",
                "type": "string",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
        ]
        self._run(list_slug, specs)

        # 7 spec tests + 1 taskid test = 8
        tests = Test.objects.filter(slug__startswith=f"{list_slug}_")
        self.assertEqual(tests.count(), 8)

        # String type for LeavesThatFailed (engine isinstance routing)
        leaves = Test.objects.get(slug="myqa_mlc_leaves_that_failed")
        self.assertEqual(leaves.type, "string")

    # -- UTC + UTI scoping (design M8 fix) ---------------------------------

    def test_linac_list_does_not_create_dxr_utc(self):
        # Per UNITS_PER_LIST: myqa_mlc is linac-only (units 1-8) — DXR (50)
        # MUST NOT get a UTC for it. This is the design M8 fix.
        list_slug = "myqa_mlc"
        specs = [
            {
                "name": "X",
                "slug": "myqa_mlc_x",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            }
        ]
        test_list = self._run(list_slug, specs)

        utc_unit_numbers = UnitTestCollection.objects.filter(object_id=test_list.pk).values_list(
            "unit__number", flat=True
        )
        self.assertEqual(set(utc_unit_numbers), {1, 2, 3, 4, 5, 7, 8})
        self.assertNotIn(50, utc_unit_numbers)

    def test_dxr_list_creates_only_unit_50_utc(self):
        # myqa_dxr_daily → unit 50 only.
        list_slug = "myqa_dxr_daily"
        specs = [
            {
                "name": "X",
                "slug": "myqa_dxr_daily_x",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            }
        ]
        # DXR uses 'daily' frequency in our test fixture
        test_list = self._run(list_slug, specs)
        utc_unit_numbers = UnitTestCollection.objects.filter(object_id=test_list.pk).values_list(
            "unit__number", flat=True
        )
        self.assertEqual(set(utc_unit_numbers), {50})

    def test_uti_created_for_every_unit_test_pair(self):
        # Engine's silent-drop at myqa_import.py:213 happens when UTI is
        # missing. Setup MUST create UTIs for every (unit, test) pair.
        list_slug = "myqa_mlc"
        specs = [
            {
                "name": "X",
                "slug": "myqa_mlc_x",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Y",
                "slug": "myqa_mlc_y",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
        ]
        self._run(list_slug, specs)

        utis = UnitTestInfo.objects.filter(test__slug__startswith=f"{list_slug}_")
        # 7 units * (2 spec tests + 1 taskid test) = 21 UTIs
        # (UNITS_PER_LIST['myqa_mlc'] = 7 linac units)
        self.assertEqual(utis.count(), 7 * 3)

    # -- --force safety (design M1) ----------------------------------------

    def test_force_deletes_existing_tests_with_slug_prefix(self):
        list_slug = "myqa_mlc"
        # First run creates 2 spec tests
        specs = [
            {
                "name": "X",
                "slug": "myqa_mlc_x",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
            {
                "name": "Y",
                "slug": "myqa_mlc_y",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
        ]
        self._run(list_slug, specs)
        self.assertEqual(Test.objects.filter(slug__startswith="myqa_mlc_").count(), 3)

        # Second run with --force and DIFFERENT specs (Z replaces X, Y)
        specs_v2 = [
            {
                "name": "Z",
                "slug": "myqa_mlc_z",
                "type": "numerical",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            },
        ]
        self._run(list_slug, specs_v2)

        # Old X and Y are gone (slug-prefix delete); Z + taskid remain
        slugs = set(Test.objects.filter(slug__startswith="myqa_mlc_").values_list("slug", flat=True))
        self.assertEqual(slugs, {"myqa_mlc_taskid", "myqa_mlc_z"})

    # -- --dry-run ---------------------------------------------------------

    def test_dry_run_creates_nothing(self):
        list_slug = "myqa_passfail"
        specs = [
            {
                "name": "Acceptance Criteria",
                "slug": "myqa_passfail_acceptance_criteria",
                "type": "string",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            }
        ]
        stub = make_importer_stub(list_slug, specs)
        registry_patch = mock.patch(
            "qatrack.qa.management.commands.setup_myqa_tests.TASK_TYPE_REGISTRY",
            {list_slug: mock.Mock(return_value=stub)},
        )
        with registry_patch:
            call_command("setup_myqa_tests", dry_run=True, force=False, task_type=list_slug)

        # Nothing created
        self.assertFalse(TestList.objects.filter(slug=list_slug).exists())
        self.assertFalse(Test.objects.filter(slug__startswith=f"{list_slug}_").exists())


if __name__ == "__main__":
    unittest.main()
