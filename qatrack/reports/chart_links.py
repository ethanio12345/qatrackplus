"""Helpers to build clickable chart-link URLs for QA report PDFs.

Per design D3 of the linac-qa-report-archive change, PDFs render tabular data
plus chart *links* (not embedded images). Links point at the live interactive
run chart (``/qa/charts/``) and the server-rendered control chart PNG
(``/qa/charts/control_chart.png``).
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.sites.models import Site
from django.urls import reverse

from qatrack.qa import models

# Format expected by the charts ``date_range`` query param
# (parsed by dateutil in qatrack.qa.views.charts).
_DATE_RANGE_FMT = "%d %b %Y"


def _site_base():
    """Return the absolute site base URL, e.g. ``https://qatrack.example.com``."""
    domain = Site.objects.get_current().domain
    return "%s://%s" % (settings.HTTP_OR_HTTPS, domain.rstrip("/"))


def _format_range(window_start, window_end):
    """Return the ``date_range`` query value used by the charts views."""
    return "%s - %s" % (
        window_start.strftime(_DATE_RANGE_FMT),
        window_end.strftime(_DATE_RANGE_FMT),
    )


def _default_status_pks():
    """Status pks that the control chart should include so it renders data.

    The control chart view returns early unless ``statuses[]`` is provided, so
    we default to all *valid* statuses (design D3: links must resolve to real
    data, not a blank image).
    """
    return list(
        models.TestInstanceStatus.objects.filter(valid=True).values_list(
            "pk", flat=True
        )
    )


def chart_urls(test, unit, window_start, window_end, test_list=None, statuses=None):
    """Return ``(run_chart_url, control_chart_url)`` for a test/unit/window.

    URLs are absolute (include the current Site domain) so they resolve from
    within an emailed PDF.

    Parameters
    ----------
    test, unit : Test, Unit
        The test and unit to scope the chart to.
    window_start, window_end : datetime
        Chart date range.
    test_list : TestList, optional
        If provided, included as ``test_lists[]`` (the run chart UI and the
        control chart data query both key off test lists).
    statuses : iterable of int, optional
        TestInstanceStatus pks to include. Defaults to all valid statuses.
    """
    base = _site_base()
    date_range = _format_range(window_start, window_end)

    common = [
        ("units[]", unit.pk),
        ("tests[]", test.pk),
        ("date_range", date_range),
    ]
    if test_list is not None:
        common.append(("test_lists[]", test_list.pk))

    run_url = "%s%s?%s" % (base, reverse("charts"), urlencode(common, doseq=True))

    control_params = list(common)
    if statuses is None:
        statuses = _default_status_pks()
    for pk in statuses:
        control_params.append(("statuses[]", pk))
    control_url = "%s%s?%s" % (
        base,
        reverse("control_chart"),
        urlencode(control_params, doseq=True),
    )

    return run_url, control_url
