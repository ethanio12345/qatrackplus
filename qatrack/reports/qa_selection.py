"""Selection of canonical linac QA UnitTestCollections for archiving.

Implements design D2 of the linac-qa-report-archive change: a structural +
has-data selection rule that automatically excludes empty / junk / Once-Off /
non-linac suites without requiring a hand-maintained allowlist.
"""

import calendar

from django.db.models import Count, Q
from django.utils import timezone

from qatrack.qa import models

# UnitType names that represent linacs / treatment units (design D2). Used to
# scope the selection to real treatment machines (excludes chambers,
# thermometers, test phantoms registered as units, etc.).
LINAC_UNIT_TYPE_NAMES = (
    "Cyberknife",
    "Tomotherapy",
    "Agility",
    "Axesse",
    "Precise",
    "Synergy",
    "Clinac",
    "EDGE",
    "Novalis",
    "Trilogy",
    "TrueBeam",
    "Oncor",
    "Primus",
)

# Canonical QA frequencies included by default (design D2). "Other" and
# "Once Off" are deliberately excluded so junk / commissioning suites are
# dropped.
DEFAULT_ARCHIVE_FREQUENCIES = (
    "Daily",
    "Weekly",
    "Monthly",
    "Quarterly",
    "Semi Annual",
    "Annual",
)


def previous_month_window(ref=None):
    """Return ``(first_day_00:00, last_day_23:59)`` for the calendar month before ``ref``.

    ``ref`` defaults to now (in the current timezone). Both returned datetimes
    are timezone-aware.
    """
    ref = ref or timezone.now()
    # first day of the current month at 00:00
    first_of_current = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # the day before that is the last day of the previous month
    last_of_prev = first_of_current - timezone.timedelta(days=1)
    window_start = last_of_prev.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    last_day = calendar.monthrange(last_of_prev.year, last_of_prev.month)[1]
    window_end = last_of_prev.replace(
        day=last_day, hour=23, minute=59, second=59, microsecond=0
    )
    return window_start, window_end


def current_month_window(ref=None):
    """Return ``(first_day_00:00, now)`` for the current calendar month."""
    ref = ref or timezone.now()
    window_start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return window_start, ref


def month_window(year, month):
    """Return the full ``(first_day_00:00, last_day_23:59)`` window for a month."""
    last_day = calendar.monthrange(year, month)[1]
    tz = timezone.get_current_timezone()
    window_start = timezone.datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    window_end = timezone.datetime(year, month, last_day, 23, 59, 59, tzinfo=tz)
    return window_start, window_end


def resolve_window(window_arg):
    """Resolve a ``--window`` argument into a ``(start, end)`` datetime window.

    Accepted values:
      * ``"lastmonth"`` - the previous calendar month (default archive cadence)
      * ``"month"`` - the current calendar month (up to now)
      * ``"YYYY-MM"`` - that specific calendar month
    """
    if not window_arg:
        return previous_month_window()

    arg = str(window_arg).strip().lower()
    if arg == "lastmonth":
        return previous_month_window()
    if arg == "month":
        return current_month_window()

    # try YYYY-MM
    try:
        year, month = (int(x) for x in arg.split("-"))
    except (ValueError, AttributeError):
        raise ValueError(
            "Invalid window %r. Use 'month', 'lastmonth', or 'YYYY-MM'." % window_arg
        )
    return month_window(year, month)


def select_archive_utcs(window_start, window_end, freqs=None, units=None):
    """Return a queryset of UnitTestCollections selected for archiving.

    A UTC is included if and only if (design D2):

      * ``active=True`` and its unit is active
      * its unit's type name is in :data:`LINAC_UNIT_TYPE_NAMES`
      * its ``frequency__name`` is in ``freqs`` (default
        :data:`DEFAULT_ARCHIVE_FREQUENCIES`)
      * it has at least one TestListInstance with ``work_completed`` inside the
        ``[window_start, window_end]`` window

    Parameters
    ----------
    window_start, window_end : datetime
        Inclusive window for the has-data requirement.
    freqs : iterable of str, optional
        Frequency names to allow. Defaults to the six canonical QA frequencies.
    units : iterable of Unit pks, optional
        Restrict to these units if provided.

    The returned queryset is annotated with ``tli_in_window`` (the count of
    TestListInstances in the window) for dry-run display.
    """
    freq_names = list(freqs) if freqs is not None else list(DEFAULT_ARCHIVE_FREQUENCIES)

    qs = models.UnitTestCollection.objects.filter(
        active=True,
        unit__active=True,
        unit__type__name__in=LINAC_UNIT_TYPE_NAMES,
        frequency__name__in=freq_names,
    )
    if units:
        qs = qs.filter(unit__in=units)

    qs = qs.annotate(
        tli_in_window=Count(
            "testlistinstance",
            filter=Q(
                testlistinstance__work_completed__gte=window_start,
                testlistinstance__work_completed__lte=window_end,
            ),
        )
    ).filter(tli_in_window__gte=1)

    return qs.select_related("unit", "frequency", "unit__type").order_by(
        "unit__name", "name"
    )


def active_linac_units():
    """Return a queryset of active linac Units (type name in LINAC_UNIT_TYPE_NAMES)."""
    from qatrack.units.models import Unit

    return Unit.objects.filter(
        active=True, type__name__in=LINAC_UNIT_TYPE_NAMES
    ).order_by("name")
