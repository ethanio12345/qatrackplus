from django.test import TestCase
from django.utils import timezone

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.reports import qa_selection
from qatrack.units.models import UnitType

LINAC_TYPE = "TrueBeam"


def _freq(name):
    freq, _ = models.Frequency.objects.get_or_create(
        name=name,
        defaults={
            "slug": name.lower().replace(" ", "_"),
            "nominal_interval": 1,
            "window_end": 1,
            "recurrences": "",
        },
    )
    return freq


def _linac_unit(name="linac"):
    tipe, _ = UnitType.objects.get_or_create(name=LINAC_TYPE)
    return utils.create_unit(name=name, tipe=tipe)


def _non_linac_unit(name="phantom"):
    tipe, _ = UnitType.objects.get_or_create(name="SomeNonLinacType")
    return utils.create_unit(name=name, tipe=tipe)


def _utc(unit, frequency, name=None, test_collection=None, active=True):
    return utils.create_unit_test_collection(
        unit=unit,
        frequency=frequency,
        test_collection=test_collection or utils.create_test_list(name=name),
        active=active,
    )


class TestPreviousMonthWindow(TestCase):
    def test_previous_month_basic(self):
        ref = timezone.datetime(
            2026, 7, 15, 10, 30, tzinfo=timezone.get_current_timezone()
        )
        start, end = qa_selection.previous_month_window(ref)
        assert start.year == 2026 and start.month == 6 and start.day == 1
        assert start.hour == 0 and start.minute == 0
        assert end.year == 2026 and end.month == 6 and end.day == 30
        assert end.hour == 23 and end.minute == 59

    def test_previous_month_handles_february_leap(self):
        ref = timezone.datetime(
            2024, 3, 1, 0, 0, tzinfo=timezone.get_current_timezone()
        )
        start, end = qa_selection.previous_month_window(ref)
        assert (start.year, start.month, start.day) == (2024, 2, 1)
        assert (end.year, end.month, end.day) == (2024, 2, 29)  # leap year


class TestResolveWindow(TestCase):
    def test_lastmonth(self):
        start, end = qa_selection.resolve_window("lastmonth")
        now = timezone.now()
        # start is first of previous month
        assert start.day == 1
        assert start <= now

    def test_yyyy_mm(self):
        start, end = qa_selection.resolve_window("2026-06")
        assert (start.year, start.month) == (2026, 6)
        assert (end.year, end.month, end.day) == (2026, 6, 30)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            qa_selection.resolve_window("nonsense")


class TestSelectArchiveUtcs(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.window = (
            self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            self.now,
        )
        self.daily = _freq("Daily")
        self.monthly = _freq("Monthly")
        self.other = _freq("Other")
        self.once = _freq("Once Off")

    def _tli(self, utc, when):
        return utils.create_test_list_instance(
            unit_test_collection=utc, work_completed=when
        )

    def test_empty_utc_excluded(self):
        unit = _linac_unit("u1")
        utc = _utc(unit, self.daily, name="Empty Daily")
        # no TLI created -> excluded
        sel = qa_selection.select_archive_utcs(*self.window)
        assert utc.pk not in list(sel.values_list("pk", flat=True))

    def test_once_off_and_other_excluded(self):
        unit = _linac_unit("u2")
        for freq in (self.other, self.once):
            utc = _utc(unit, freq, name="%s suite" % freq.name)
            self._tli(utc, self.now)
        sel = qa_selection.select_archive_utcs(*self.window)
        names = list(sel.values_list("name", flat=True))
        assert not any("Once Off" in n for n in names)
        assert not any(n.endswith("Other suite") for n in names)

    def test_stale_utc_excluded(self):
        unit = _linac_unit("u3")
        utc = _utc(unit, self.monthly, name="Stale Monthly")
        self._tli(utc, self.window[0] - timezone.timedelta(days=400))
        sel = qa_selection.select_archive_utcs(*self.window)
        assert utc.pk not in list(sel.values_list("pk", flat=True))

    def test_non_linac_excluded(self):
        unit = _non_linac_unit("chamber")
        utc = _utc(unit, self.daily, name="Non-linac daily")
        self._tli(utc, self.now)
        sel = qa_selection.select_archive_utcs(*self.window)
        assert utc.pk not in list(sel.values_list("pk", flat=True))

    def test_inactive_utc_excluded(self):
        unit = _linac_unit("u4")
        utc = _utc(unit, self.daily, name="Inactive", active=False)
        self._tli(utc, self.now)
        sel = qa_selection.select_archive_utcs(*self.window)
        assert utc.pk not in list(sel.values_list("pk", flat=True))

    def test_canonical_included(self):
        unit = _linac_unit("u5")
        utc = _utc(unit, self.daily, name="Canonical Daily")
        self._tli(utc, self.now)
        sel = qa_selection.select_archive_utcs(*self.window)
        pks = list(sel.values_list("pk", flat=True))
        assert utc.pk in pks
        # annotation present
        assert sel.get(pk=utc.pk).tli_in_window == 1

    def test_freq_override(self):
        unit = _linac_unit("u6")
        daily_utc = _utc(unit, self.daily, name="Daily")
        monthly_utc = _utc(unit, self.monthly, name="Monthly")
        self._tli(daily_utc, self.now)
        self._tli(monthly_utc, self.now)
        sel = qa_selection.select_archive_utcs(*self.window, freqs=["Daily"])
        names = list(sel.values_list("name", flat=True))
        assert "Daily" in names and "Monthly" not in names

    def test_window_data_filter(self):
        """A canonical UTC whose only TLI is outside the window is excluded."""
        unit = _linac_unit("u7")
        utc = _utc(unit, self.daily, name="WindowDaily")
        self._tli(utc, self.window[0] - timezone.timedelta(days=10))
        sel = qa_selection.select_archive_utcs(*self.window)
        assert utc.pk not in list(sel.values_list("pk", flat=True))
