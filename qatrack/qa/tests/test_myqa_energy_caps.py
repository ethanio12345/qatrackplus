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

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
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
