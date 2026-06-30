from django import template

from qatrack.reports.chart_links import chart_urls

register = template.Library()


@register.simple_tag(takes_context=True)
def chart_link_urls(context, ti):
    """Return ``(run_chart_url, control_chart_url)`` for a TestInstance row.

    Reads ``chart_window`` (a dict with ``start``/``end`` and optional
    ``statuses``) from the template context. Returns ``(None, None)`` when no
    window is configured (e.g. existing saved reports without chart links).
    """
    window = context.get("chart_window")
    if not window:
        return (None, None)

    uti = ti.unit_test_info
    test_list = getattr(getattr(ti, "test_list_instance", None), "test_list", None)
    run, control = chart_urls(
        uti.test,
        uti.unit,
        window["start"],
        window["end"],
        test_list=test_list,
        statuses=window.get("statuses"),
    )
    return (run, control)
