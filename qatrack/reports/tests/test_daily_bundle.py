import zipfile
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from django.utils.text import slugify

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.reports.qa_selection import LINAC_UNIT_TYPE_NAMES
from qatrack.reports.qc import daily_bundle
from qatrack.units.models import UnitType


def _freq(name):
    freq, _ = models.Frequency.objects.get_or_create(
        name=name,
        defaults={
            "slug": name.lower(),
            "nominal_interval": 1,
            "window_end": 1,
            "recurrences": "",
        },
    )
    return freq


def _linac(name="linac"):
    tipe, _ = UnitType.objects.get_or_create(name=LINAC_UNIT_TYPE_NAMES[0])
    return utils.create_unit(name=name, tipe=tipe)


def _utc(unit, name, frequency=None):
    return utils.create_unit_test_collection(
        unit=unit,
        frequency=frequency or _freq("Daily"),
        test_collection=utils.create_test_list(name=name),
    )


class TestResolveCurrentDailyConstancyUtc(TestCase):
    def setUp(self):
        self.unit = _linac("LA224")
        self.now = timezone.now()

    def test_most_recent_wins(self):
        old = _utc(self.unit, "Daily Constancy Check")
        utils.create_test_list_instance(
            unit_test_collection=old,
            work_completed=self.now - timezone.timedelta(days=400),
        )
        current = _utc(self.unit, "Daily Constancy Check[3]")
        utils.create_test_list_instance(
            unit_test_collection=current, work_completed=self.now
        )
        resolved = daily_bundle.resolve_current_daily_constancy_utc(self.unit)
        assert resolved.pk == current.pk

    def test_no_constancy_utc(self):
        assert daily_bundle.resolve_current_daily_constancy_utc(self.unit) is None

    def test_override_takes_precedence(self):
        old = _utc(self.unit, "Daily Constancy Check")
        utils.create_test_list_instance(
            unit_test_collection=old, work_completed=self.now
        )
        override_utc = _utc(self.unit, "Daily Constancy Check[2]")
        utils.create_test_list_instance(
            unit_test_collection=override_utc,
            work_completed=self.now - timezone.timedelta(days=900),
        )
        # the override points at override_utc even though 'old' is more recent
        with mock.patch.object(
            daily_bundle,
            "_load_constancy_override",
            return_value={self.unit.name: override_utc.pk},
        ):
            resolved = daily_bundle.resolve_current_daily_constancy_utc(self.unit)
        assert resolved.pk == override_utc.pk


class TestResolveRtDailyUtc(TestCase):
    def test_resolves_rt_utc(self):
        unit = _linac("LA317")
        rt = _utc(unit, "Daily QA (RTs)")
        assert daily_bundle.resolve_rt_daily_utc(unit).pk == rt.pk

    def test_none_when_absent(self):
        unit = _linac("LA999")
        assert daily_bundle.resolve_rt_daily_utc(unit) is None


class TestRenderDailyBundle(TestCase):
    def setUp(self):
        self.unit = _linac("LA317")
        self.now = timezone.now()
        self.window = (
            self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            self.now,
        )
        self.constancy = _utc(self.unit, "Daily Constancy Check[1]")
        utils.create_test_list_instance(
            unit_test_collection=self.constancy, work_completed=self.now
        )
        self.rt = _utc(self.unit, "Daily QA (RTs)")
        utils.create_test_list_instance(
            unit_test_collection=self.rt, work_completed=self.now
        )

    def test_bundle_renders_constancy_only(self):
        pdf_bytes = daily_bundle.render_daily_bundle_pdf(self.unit, self.window)
        assert pdf_bytes[:4] == b"%PDF"

    def test_bundle_raises_when_no_constancy(self):
        empty_unit = _linac("LA_empty")
        with self.assertRaises(ValueError):
            daily_bundle.render_daily_bundle_pdf(empty_unit, self.window)


class TestGenerateDailyBundles(TestCase):
    def setUp(self):
        self.unit = _linac("LA1")
        self.now = timezone.now()
        self.window = (
            self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            self.now,
        )
        self.constancy = _utc(self.unit, "Daily Constancy Check")
        utils.create_test_list_instance(
            unit_test_collection=self.constancy, work_completed=self.now
        )
        self.rt = _utc(self.unit, "Daily QA (RTs)")
        utils.create_test_list_instance(
            unit_test_collection=self.rt, work_completed=self.now
        )

    def test_generate_daily_bundles_zip_layout(self):
        zip_path, summary = daily_bundle.generate_daily_bundles(*self.window)
        assert summary["count"] == 1
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert len(names) == 1
            expected = "%s_daily_qa_%s.pdf" % (
                slugify(self.unit.name),
                self.window[0].strftime("%Y-%m"),
            )
            assert names[0] == expected
            assert zf.read(names[0])[:4] == b"%PDF"
        assert summary["zip_name"] == "daily_qa_report_%s.zip" % self.window[
            0
        ].strftime("%Y-%m")

    def test_unit_without_constancy_is_skipped(self):
        # an extra active linac with no Daily Constancy UTC is skipped, not errored
        _linac("LA_empty2")
        zip_path, summary = daily_bundle.generate_daily_bundles(*self.window)
        units_skipped = [s["unit"] for s in summary["skipped"]]
        assert "LA_empty2" in units_skipped
        assert summary["count"] == 1  # only the configured unit
