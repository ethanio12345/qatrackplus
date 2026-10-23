"""Tests for per-unit beam-energy caps (unit_energy_caps).

Covers:
- ``classify_test_energy()`` name classification (electrons, photons,
  energy-agnostic, false positives)
- ``_normalise_energy_caps()`` / ``get_unit_energy_caps()`` config plumbing
- ``energy_applicable()`` / ``_apply_energy_caps()`` filtering
- ``skip_inapplicable_myqa_tests`` command: dry-run, --apply (skips junk TIs,
  re-approves sessions whose only blocker was the junk), --deactivate-utis
"""

from unittest import mock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from qatrack.myqa_import import (
    _apply_energy_caps,
    _normalise_energy_caps,
    classify_test_energy,
    energy_applicable,
    get_unit_energy_caps,
)
from qatrack.qa.models import (
    AutoReviewRule,
    AutoReviewRuleSet,
    Category,
    Test,
    TestInstance,
    TestInstanceStatus,
    TestList,
    TestListInstance,
    TestListMembership,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.qa.utils import get_internal_user
from qatrack.units.models import Unit, UnitType

# Caps mimicking LA317 (Ethos): photons only, no electrons.
PHOTONS_ONLY_CAPS = {"photons": {"6X", "6FFF", "10X", "10FFF"}, "electrons": set()}


class TestClassifyTestEnergy(TestCase):
    def test_electron_with_energy(self):
        assert classify_test_energy("Electrons 1.02 9MeV Output") == ("electron", 9)
        assert classify_test_energy("Electrons 1.10 18MeV Uniformity") == (
            "electron",
            18,
        )
        assert classify_test_energy("08.01 Electron PDI 01. 6MeV D90%") == (
            "electron",
            6,
        )

    def test_electron_with_spaced_energy(self):
        assert classify_test_energy("Uniformity 12 MeV") == ("electron", 12)

    def test_electron_word_without_energy(self):
        assert classify_test_energy("Electron Applicator: A10") == ("electron", None)

    def test_photon_tokens(self):
        assert classify_test_energy("Photons 1.01 6MV Output") == ("photon", "6X")
        assert classify_test_energy("Photons 1.07 6FFF Uniformity") == (
            "photon",
            "6FFF",
        )
        assert classify_test_energy("10FFF Flatness") == ("photon", "10FFF")
        assert classify_test_energy("10MV CentreShift") == ("photon", "10X")
        assert classify_test_energy("18MV Dose Output") == ("photon", "18X")
        assert classify_test_energy("Photon 18X Output") == ("photon", "18X")

    def test_energy_agnostic_names(self):
        assert (
            classify_test_energy("Geometry/Collimation 2.04 Gantry Absolute (deg)")
            is None
        )
        assert (
            classify_test_energy("Enhanced MLC 2.14 MLC Max offset (Bank A) (mm)")
            is None
        )
        assert (
            classify_test_energy("5.Tmt.Linac.D2 - Daily QA (Physics) Task ID") is None
        )

    def test_false_positives_are_not_energy(self):
        # "MV Imager" has no leading energy digit.
        assert (
            classify_test_energy("Geometry/Collimation 2.03 MV Imager offset (mm)")
            is None
        )
        # An enriched step prefix like "1.18" must not read as "18 MeV/MV".
        assert classify_test_energy("Photons 1.18 MV offset (mm)") is None
        # Field sizes like 10x10 / 6x6 are not energies (no word boundary).
        assert classify_test_energy("PDD 10x10 6x6 field") is None
        # Jaw X1 has the digit after the X.
        assert classify_test_energy("Geometry/Collimation 2.06 Jaw X1 (mm)") is None


class TestNormaliseEnergyCaps(TestCase):
    def test_none_is_unrestricted(self):
        assert _normalise_energy_caps(None) is None

    def test_aliases_and_int_coercion(self):
        caps = _normalise_energy_caps(
            {"photons": ["6MV", "6FFF", "10X", "10fff"], "electrons": ["9", 12]}
        )
        assert caps == {
            "photons": {"6X", "6FFF", "10X", "10FFF"},
            "electrons": {9, 12},
        }

    def test_get_unit_energy_caps_unlisted_unit(self):
        with mock.patch("qatrack.myqa_import._load_centre_config", return_value={}):
            assert get_unit_energy_caps(999) is None

    def test_get_unit_energy_caps_explicit_null(self):
        with mock.patch(
            "qatrack.myqa_import._load_centre_config",
            return_value={"unit_energy_caps": {3: None}},
        ):
            assert get_unit_energy_caps(3) is None

    def test_get_unit_energy_caps_string_keys(self):
        with mock.patch(
            "qatrack.myqa_import._load_centre_config",
            return_value={
                "unit_energy_caps": {"3": {"photons": ["6X"], "electrons": []}}
            },
        ):
            assert get_unit_energy_caps(3) == {"photons": {"6X"}, "electrons": set()}


class TestEnergyApplicable(TestCase):
    def test_unrestricted_caps_allow_everything(self):
        assert energy_applicable("Electrons 1.02 9MeV Output", None)
        assert energy_applicable("18MV Dose Output", None)

    def test_photons_only_unit(self):
        assert energy_applicable("Photons 1.01 6MV Output", PHOTONS_ONLY_CAPS)
        assert energy_applicable("Geometry 2.04 Gantry Absolute", PHOTONS_ONLY_CAPS)
        assert not energy_applicable("Electrons 1.02 9MeV Output", PHOTONS_ONLY_CAPS)
        assert not energy_applicable("18MV Dose Output", PHOTONS_ONLY_CAPS)
        # Energy-agnostic electron work needs at least one electron energy.
        assert not energy_applicable("Electron Applicator: A10", PHOTONS_ONLY_CAPS)

    def test_unit_energy_applicable_uses_config(self):
        caps_by_unit = {3: PHOTONS_ONLY_CAPS}
        with mock.patch(
            "qatrack.myqa_import._load_centre_config",
            return_value={"unit_energy_caps": caps_by_unit},
        ):
            from qatrack.myqa_import import unit_energy_applicable

            assert not unit_energy_applicable("Electrons 1.02 9MeV Output", 3)
            assert unit_energy_applicable("Electrons 1.02 9MeV Output", 4)  # unlisted


class TestApplyEnergyCaps(TestCase):
    def test_filters_and_counts(self):
        results = {
            "Photons 1.01 6MV Output": {"value": 1.0},
            "Electrons 1.02 9MeV Output": {"value": 0.03},
            "18MV Dose Output": {"value": 1.0},
            "Geometry 2.04 Gantry Absolute": {"value": 0.2},
        }
        filtered, dropped = _apply_energy_caps(results, PHOTONS_ONLY_CAPS)
        assert set(filtered) == {
            "Photons 1.01 6MV Output",
            "Geometry 2.04 Gantry Absolute",
        }
        assert dropped == 2

    def test_no_caps_is_noop(self):
        results = {"Electrons 1.02 9MeV Output": {"value": 0.03}}
        filtered, dropped = _apply_energy_caps(results, None)
        assert filtered is results
        assert dropped == 0


class TestSkipInapplicableCommand(TestCase):
    """End-to-end: junk electron readings on a photons-only unit get skipped
    and their sessions approved; genuine failures keep blocking."""

    @classmethod
    def setUpTestData(cls):
        cls.internal_user = get_internal_user()
        unit_type = UnitType.objects.create(name="Treatment LINAC")
        cls.unit = Unit.objects.create(
            name="LA317: 2972",
            number=3,
            type=unit_type,
            date_acceptance=timezone.now().date(),
        )
        category = Category.objects.create(name="myQA")
        cls.test_list = TestList.objects.create(
            name="5.Tmt.Linac.D2 - Daily QA (Physics)",
            slug="5tmtlinacd2dailyqaphysics",
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.utc = UnitTestCollection.objects.create(
            unit=cls.unit,
            content_type=ContentType.objects.get_for_model(TestList),
            object_id=cls.test_list.pk,
            name=cls.test_list.name,
        )

        cls.electron_test = Test.objects.create(
            name="Electrons 1.02 9MeV Output",
            slug="electrons1029mevoutput",
            type="simple",
            category=category,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.photon_test = Test.objects.create(
            name="Photons 1.01 6MV Output",
            slug="photons1016mvoutput",
            type="simple",
            category=category,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.gantry_test = Test.objects.create(
            name="Geometry/Collimation 2.04 Gantry Absolute (deg)",
            slug="geometrycollimation204gantryabsolute",
            type="simple",
            category=category,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        for i, test in enumerate((cls.electron_test, cls.photon_test, cls.gantry_test)):
            TestListMembership.objects.create(
                test_list=cls.test_list, test=test, order=i
            )
        # NOTE: UnitTestInfos are created automatically by the post_save
        # signals on UnitTestCollection / TestListMembership (qatrack/qa/
        # signals.py) — don't create them manually here.
        assert UnitTestInfo.objects.filter(unit=cls.unit).count() == 3

        # Auto-review machinery: Default ruleset mapping everything but
        # action to Approved.
        cls.status_ok = TestInstanceStatus.objects.create(
            name="Approved", slug="approved", requires_review=False
        )
        cls.status_action = TestInstanceStatus.objects.create(
            name="Unreviewed", slug="unreviewed", requires_review=True
        )
        cls.ruleset = AutoReviewRuleSet.objects.create(name="Default", is_default=True)
        for pass_fail, status in (
            ("ok", cls.status_ok),
            ("tolerance", cls.status_ok),
            ("no_tol", cls.status_ok),
            ("not_done", cls.status_ok),
            ("action", cls.status_action),
        ):
            rule = AutoReviewRule.objects.create(pass_fail=pass_fail, status=status)
            cls.ruleset.rules.add(rule)
        for test in (cls.electron_test, cls.photon_test, cls.gantry_test):
            test.autoreviewruleset = cls.ruleset
            test.save()

        # Session A: junk electron reading + two good tests -> should become
        # fully reviewed once the electron TI is skipped.
        cls.tli_a = cls._make_tli()
        cls._make_ti(cls.tli_a, cls.electron_test, value=0.03, pass_fail="action")
        cls._make_ti(cls.tli_a, cls.photon_test, value=1.0, pass_fail="ok")
        cls._make_ti(cls.tli_a, cls.gantry_test, value=0.2, pass_fail="ok")

        # Session B: junk electron reading + a genuinely failed, commented
        # gantry test -> must stay unreviewed.
        cls.tli_b = cls._make_tli()
        cls._make_ti(cls.tli_b, cls.electron_test, value=0.03, pass_fail="action")
        ti = cls._make_ti(cls.tli_b, cls.gantry_test, value=5.0, pass_fail="action")
        ti.comment = "genuine failure"
        ti.save()

    @classmethod
    def _make_tli(cls):
        return TestListInstance.objects.create(
            unit_test_collection=cls.utc,
            test_list=cls.test_list,
            work_started=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
            day=0,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )

    @staticmethod
    def _make_ti(tli, test, value, pass_fail):
        uti = UnitTestInfo.objects.get(unit=tli.unit_test_collection.unit, test=test)
        return TestInstance.objects.create(
            test_list_instance=tli,
            unit_test_info=uti,
            value=value,
            pass_fail=pass_fail,
            status=TestInstanceStatus.objects.get(
                requires_review=(pass_fail == "action")
            ),
            created_by=tli.created_by,
            modified_by=tli.created_by,
            work_started=tli.work_started,
        )

    def _run(self, *args):
        from io import StringIO

        out = StringIO()
        with mock.patch(
            "qatrack.qa.management.commands.skip_inapplicable_myqa_tests"
            ".get_unit_energy_caps",
            return_value=PHOTONS_ONLY_CAPS,
        ):
            call_command("skip_inapplicable_myqa_tests", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self._run()
        assert "would become fully reviewed" in output
        assert TestInstance.objects.filter(skipped=True).count() == 0
        assert not TestListInstance.objects.get(pk=self.tli_a.pk).all_reviewed

    def test_apply_skips_junk_and_approves_clean_sessions(self):
        output = self._run("--apply")
        assert "auto-approved" in output

        junk = TestInstance.objects.filter(unit_test_info__test=self.electron_test)
        assert junk.count() == 2
        assert all(ti.skipped for ti in junk)
        assert all(ti.pass_fail == "not_done" for ti in junk)
        assert all("Not applicable" in (ti.comment or "") for ti in junk)

        # Session A (only junk blocker) approved; B keeps its genuine failure.
        assert TestListInstance.objects.get(pk=self.tli_a.pk).all_reviewed
        assert not TestListInstance.objects.get(pk=self.tli_b.pk).all_reviewed

        # UTIs untouched without --deactivate-utis.
        assert UnitTestInfo.objects.filter(unit=self.unit, active=False).count() == 0

    def test_apply_is_idempotent(self):
        self._run("--apply")
        output = self._run("--apply")
        assert "already done" in output
        assert TestInstance.objects.filter(skipped=True).count() == 2

    def test_apply_deactivate_utis(self):
        self._run("--apply", "--deactivate-utis")
        uti = UnitTestInfo.objects.get(unit=self.unit, test=self.electron_test)
        assert not uti.active
        # Energy-agnostic tests keep their active UTIs.
        assert UnitTestInfo.objects.get(unit=self.unit, test=self.photon_test).active

    def test_unlisted_unit_is_untouched(self):
        output = self._run("--units", "999")
        assert "nothing to do" in output
        assert TestInstance.objects.filter(skipped=True).count() == 0


class TestConstantReadingsMode(TestCase):
    """--constant-readings: flag placeholder series (every reading identical)
    on linac units, but never count-type metrics whose constants are real."""

    @classmethod
    def setUpTestData(cls):
        cls.internal_user = get_internal_user()
        unit_type = UnitType.objects.create(name="TrueBeam")
        cls.unit = Unit.objects.create(
            name="LA224",
            number=8,
            type=unit_type,
            date_acceptance=timezone.now().date(),
        )
        category = Category.objects.create(name="myQA")
        cls.test_list = TestList.objects.create(
            name="5.Tmt.Linac.D2 - Daily QA (Physics)",
            slug="5tmtlinacd2dailyqaphysics",
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.utc = UnitTestCollection.objects.create(
            unit=cls.unit,
            content_type=ContentType.objects.get_for_model(TestList),
            object_id=cls.test_list.pk,
            name=cls.test_list.name,
        )

        cls.specs = {
            "couch": "Geometry/Couch 2.24 Couch Vertical (mm)",
            "peaks": "Static Picket Fence @ G=0 Failing Peaks",
            "varying": "Photons 1.01 6MV Output",
            "short": "Short Constant Series (mm)",
        }
        cls.ruleset = cls._ruleset()
        cls.tests = {}
        for key, name in cls.specs.items():
            test = Test.objects.create(
                name=name,
                slug=f"const-{key}",
                type="simple",
                category=category,
                created_by=cls.internal_user,
                modified_by=cls.internal_user,
                autoreviewruleset=cls.ruleset,
            )
            cls.tests[key] = test
            TestListMembership.objects.create(
                test_list=cls.test_list, test=test, order=len(cls.tests)
            )

        cls.tli = TestListInstance.objects.create(
            unit_test_collection=cls.utc,
            test_list=cls.test_list,
            work_started=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
            day=0,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        # 12 placeholder couch readings + 12 genuine-ok peak counts +
        # 12 varying output readings + only 5 of a constant series.
        cls._add_readings("couch", [1.0] * 12)
        cls._add_readings("peaks", [0.0] * 12)
        cls._add_readings("varying", [1.0 + i / 100 for i in range(12)])
        cls._add_readings("short", [0.03] * 5)

    @classmethod
    def _ruleset(cls):
        ruleset = AutoReviewRuleSet.objects.create(name="Default CR", is_default=True)
        status_ok = TestInstanceStatus.objects.get_or_create(
            name="Approved", slug="approved", defaults={"requires_review": False}
        )[0]
        status_action = TestInstanceStatus.objects.get_or_create(
            name="Unreviewed", slug="unreviewed", defaults={"requires_review": True}
        )[0]
        for pass_fail, status in (
            ("ok", status_ok),
            ("tolerance", status_ok),
            ("no_tol", status_ok),
            ("not_done", status_ok),
            ("action", status_action),
        ):
            rule = AutoReviewRule.objects.create(pass_fail=pass_fail, status=status)
            ruleset.rules.add(rule)
        return ruleset

    @classmethod
    def _add_readings(cls, key, values):
        test = cls.tests[key]
        uti = UnitTestInfo.objects.get(unit=cls.unit, test=test)
        status_ok = TestInstanceStatus.objects.get(slug="approved")
        for value in values:
            TestInstance.objects.create(
                test_list_instance=cls.tli,
                unit_test_info=uti,
                value=value,
                pass_fail="ok",
                status=status_ok,
                created_by=cls.internal_user,
                modified_by=cls.internal_user,
                work_started=cls.tli.work_started,
            )

    def _run(self, *args):
        from io import StringIO

        out = StringIO()
        call_command("skip_inapplicable_myqa_tests", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_flags_only_true_placeholders(self):
        output = self._run("--constant-readings")
        detail_lines = [line for line in output.splitlines() if "TI(s) in" in line]
        assert any("Couch Vertical" in line for line in detail_lines)
        assert all("constant placeholder" in line for line in detail_lines)
        # Count-type metrics are never flagged, nor varying or short series.
        assert not any("Failing Peaks" in line for line in detail_lines)
        assert not any("6MV Output" in line for line in detail_lines)
        assert not any("Short Constant Series" in line for line in detail_lines)
        assert TestInstance.objects.filter(skipped=True).count() == 0

    def test_apply_skips_placeholders_only(self):
        output = self._run("--constant-readings", "--apply")
        assert "auto-approved" in output

        couch = TestInstance.objects.filter(unit_test_info__test=self.tests["couch"])
        assert couch.count() == 12
        assert all(ti.skipped for ti in couch)
        assert all("placeholder" in (ti.comment or "") for ti in couch)

        # Count-type, varying, and too-short series are untouched.
        for key in ("peaks", "varying", "short"):
            assert (
                TestInstance.objects.filter(
                    unit_test_info__test=self.tests[key], skipped=True
                ).count()
                == 0
            ), key
        assert TestListInstance.objects.get(pk=self.tli.pk).all_reviewed

    def test_apply_is_idempotent(self):
        self._run("--constant-readings", "--apply")
        # Already-skipped readings are excluded from series detection, so a
        # re-run simply finds nothing left to do.
        output = self._run("--constant-readings", "--apply")
        assert "No flaggable TestInstances found" in output
        assert (
            TestInstance.objects.filter(
                unit_test_info__test=self.tests["couch"], skipped=True
            ).count()
            == 12
        )

    def test_min_readings_override(self):
        # Series of 5 readings are below the default threshold of 10 but get
        # flagged when --min-readings is lowered. Each test starts from the
        # pristine fixtures (per-test rollback), so the 12 couch readings are
        # flagged again too: 12 + 5 = 17.
        output = self._run("--constant-readings", "--min-readings", "3", "--apply")
        assert "17 TI(s) flagged" in output
        assert (
            TestInstance.objects.filter(
                unit_test_info__test=self.tests["short"], skipped=True
            ).count()
            == 5
        )

    def test_non_linac_units_ignored(self):
        # A non-linac unit type is outside --constant-readings scope.
        other_type = UnitType.objects.create(name="Well Chamber")
        other = Unit.objects.create(
            name="Some Chamber",
            number=999,
            type=other_type,
            date_acceptance=timezone.now().date(),
        )
        category = Category.objects.get(name="myQA")
        test = Test.objects.create(
            name="Chamber Reading (pA)",
            slug="chamber-reading",
            type="simple",
            category=category,
            created_by=self.internal_user,
            modified_by=self.internal_user,
        )
        uti = UnitTestInfo.objects.create(unit=other, test=test)
        status_ok = TestInstanceStatus.objects.get(slug="approved")
        for _ in range(12):
            TestInstance.objects.create(
                test_list_instance=self.tli,
                unit_test_info=uti,
                value=32.119,
                pass_fail="ok",
                status=status_ok,
                created_by=self.internal_user,
                modified_by=self.internal_user,
                work_started=self.tli.work_started,
            )
        output = self._run("--constant-readings", "--apply")
        assert "Chamber Reading" not in output
        assert (
            TestInstance.objects.filter(
                unit_test_info__unit=other, skipped=True
            ).count()
            == 0
        )


class TestForceCloseAndListUtcs(TestCase):
    """--force-close-unreviewed and --deactivate-list-utcs options."""

    @classmethod
    def setUpTestData(cls):
        cls.internal_user = get_internal_user()
        unit_type = UnitType.objects.create(name="Treatment LINAC")
        cls.unit = Unit.objects.create(
            name="LA414: 1733",
            number=4,
            type=unit_type,
            date_acceptance=timezone.now().date(),
        )
        category = Category.objects.create(name="myQA")

        cls.d2_list = TestList.objects.create(
            name="5.Tmt.Linac.D2 - Daily QA (Physics)",
            slug="5tmtlinacd2dailyqaphysics",
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.other_list = TestList.objects.create(
            name="5.Tmt.Linac.Monthly - IGRT",
            slug="5tmtlinacmonthlyigrt",
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        cls.d2_utc = UnitTestCollection.objects.create(
            unit=cls.unit,
            content_type=ContentType.objects.get_for_model(TestList),
            object_id=cls.d2_list.pk,
            name=cls.d2_list.name,
        )
        cls.other_utc = UnitTestCollection.objects.create(
            unit=cls.unit,
            content_type=ContentType.objects.get_for_model(TestList),
            object_id=cls.other_list.pk,
            name=cls.other_list.name,
        )
        test = Test.objects.create(
            name="Geometry 2.04 Gantry Absolute (deg)",
            slug="gantry-absolute",
            type="simple",
            category=category,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        TestListMembership.objects.create(test_list=cls.d2_list, test=test, order=0)
        uti = UnitTestInfo.objects.get(unit=cls.unit, test=test)
        status_action = TestInstanceStatus.objects.get_or_create(
            name="Unreviewed", slug="unreviewed", defaults={"requires_review": True}
        )[0]
        cls.tli = TestListInstance.objects.create(
            unit_test_collection=cls.d2_utc,
            test_list=cls.d2_list,
            work_started=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
            day=0,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
        )
        TestInstance.objects.create(
            test_list_instance=cls.tli,
            unit_test_info=uti,
            value=99.0,
            pass_fail="action",
            status=status_action,
            created_by=cls.internal_user,
            modified_by=cls.internal_user,
            work_started=cls.tli.work_started,
        )

    def _run(self, *args):
        from io import StringIO

        out = StringIO()
        call_command("skip_inapplicable_myqa_tests", *args, stdout=out)
        return out.getvalue()

    def test_force_close_requires_units(self):
        with pytest.raises(CommandError):
            self._run("--force-close-unreviewed", "--apply")

    def test_force_close_dry_run_changes_nothing(self):
        self._run("--force-close-unreviewed", "--units", "4")
        tli = TestListInstance.objects.get(pk=self.tli.pk)
        assert not tli.all_reviewed

    def test_force_close_marks_reviewed(self):
        self._run("--force-close-unreviewed", "--units", "4", "--apply")
        tli = TestListInstance.objects.get(pk=self.tli.pk)
        assert tli.all_reviewed
        assert tli.reviewed_by_id == self.internal_user.pk
        # Readings preserved untouched.
        assert (
            TestInstance.objects.filter(
                test_list_instance=self.tli, skipped=True
            ).count()
            == 0
        )

    def test_deactivate_list_utcs_by_name(self):
        assert self.d2_utc.active and self.other_utc.active
        self._run("--deactivate-list-utcs", self.d2_list.name, "--apply")
        self.d2_utc.refresh_from_db()
        self.other_utc.refresh_from_db()
        assert not self.d2_utc.active
        assert self.other_utc.active

    def test_deactivate_list_utcs_dry_run(self):
        self._run("--deactivate-list-utcs", "5tmtlinacd2dailyqaphysics")
        self.d2_utc.refresh_from_db()
        assert self.d2_utc.active

    def test_deactivate_list_utcs_unknown_list(self):
        with pytest.raises(CommandError):
            self._run("--deactivate-list-utcs", "No Such List", "--apply")
