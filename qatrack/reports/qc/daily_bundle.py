"""Per-linac Daily QA bundle report (design D4).

For each linac, bundle two UnitTestCollections' TestListInstances for the window
into one PDF:

  * the unit's *current* Daily Constancy Check UTC (resolved by most-recent
    ``work_completed``, overridable via ``daily_constancy_override.yaml``)
  * the unit's "Daily QA (RTs)" UTC (which contains the MPC test)

Both reuse :class:`TestListInstanceDetailsReport` with chart links enabled.
"""

import logging
import zipfile
from pathlib import Path

import yaml
from django.conf import settings
from django.db.models import Max
from django.utils.text import slugify

from qatrack.qa import models
from qatrack.reports.qa_archive import (
    _report_base_opts,
    _resolve_zip_path,
    _system_user,
    _work_completed_range,
    email_archive,
)
from qatrack.reports.qa_selection import active_linac_units
from qatrack.reports.qc.testlistinstance import TestListInstanceDetailsReport

logger = logging.getLogger("qatrack")

OVERRIDE_FILENAME = "daily_constancy_override.yaml"


def _override_path():
    # PROJECT_ROOT is the qatrack/ package directory (settings.py lives there)
    return Path(settings.PROJECT_ROOT) / "reports" / OVERRIDE_FILENAME


def _load_constancy_override():
    """Return the ``{unit_name: utc_pk}`` override map, or ``{}`` if absent."""
    path = _override_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        logger.exception("Could not parse %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items()}


def resolve_current_daily_constancy_utc(unit):
    """Return the current Daily Constancy UTC for ``unit`` (design D4).

    Resolution rule:
      1. If ``daily_constancy_override.yaml`` maps the unit's name to a UTC pk,
         that UTC is used (precedence).
      2. Otherwise, the active UTC whose name starts with "Daily Constancy" on
         this unit with the most recent ``work_completed`` is returned.

    Returns ``None`` if no such UTC exists.
    """
    override = _load_constancy_override()
    pk = override.get(unit.name)
    if pk is not None:
        utc = models.UnitTestCollection.objects.filter(pk=pk).first()
        if utc:
            return utc
        logger.warning(
            "daily_constancy_override.yaml maps %r to missing UTC pk %s", unit.name, pk
        )

    return (
        models.UnitTestCollection.objects.filter(
            unit=unit, active=True, name__istartswith="Daily Constancy"
        )
        .annotate(last_wc=Max("testlistinstance__work_completed"))
        .filter(last_wc__isnull=False)
        .order_by("-last_wc")
        .first()
    )


def resolve_rt_daily_utc(unit):
    """Return the unit's "Daily QA (RTs)" UTC (contains MPC), or ``None``.

    Reserved for a future revision of the daily bundle that re-adds the RT/MPC
    section. Not used by :func:`render_daily_bundle_pdf` at present (per the
    "physics constancy only" scoping decision — see the
    ``daily-qa-bundle-report`` spec).
    """
    return models.UnitTestCollection.objects.filter(
        unit=unit, active=True, name__icontains="Daily QA (RTs)"
    ).first()


def resolve_daily_pair(unit):
    """Return ``(constancy_utc, rt_utc)`` for ``unit``; either may be ``None``.

    The RT UTC is resolved for completeness/future use; the current render path
    only consumes the constancy UTC.
    """
    return resolve_current_daily_constancy_utc(unit), resolve_rt_daily_utc(unit)


def render_daily_bundle_pdf(unit, window, include_chart_links=True):
    """Render one PDF (bytes) of the unit's Daily Constancy physics tests.

    Scoped to the unit's *current* Daily Constancy UTC (output, field
    width/penumbra, flatness, symmetry, energy factor, center) for the window,
    with chart links enabled. The RT/MPC daily list is intentionally excluded
    at this stage (only physics constancy tests are wanted); see the
    ``daily-qa-bundle-report`` spec.
    """
    constancy = resolve_current_daily_constancy_utc(unit)
    if constancy is None:
        raise ValueError("No Daily Constancy UTC found for unit %s" % unit.name)

    window_start, window_end = window
    report_opts = {
        "unit_test_collection": [constancy.pk],
        "work_completed": _work_completed_range(window_start, window_end),
    }
    base_opts = _report_base_opts(window_start, window_end, include_chart_links)
    rep = TestListInstanceDetailsReport(
        base_opts=base_opts, report_opts=report_opts, user=_system_user()
    )
    rep.report_format = "pdf"
    return rep.to_pdf()


def generate_daily_bundles(window_start, window_end, out_zip_path=None):
    """Render one daily-constancy PDF per active linac and zip them together.

    Only linacs that resolve to a current Daily Constancy UTC are rendered;
    others are skipped. Returns a ``(zip_path, summary)`` tuple. ``summary`` has
    ``label``, ``zip_path``, ``zip_name``, ``count``, ``rendered`` and
    ``skipped``.
    """
    label = window_start.strftime("%Y-%m")
    units = active_linac_units()

    rendered = []
    skipped = []
    pdfs = {}

    for unit in units:
        constancy = resolve_current_daily_constancy_utc(unit)
        if constancy is None:
            skipped.append({"unit": unit.name, "reason": "no Daily Constancy UTC"})
            continue
        try:
            pdf_bytes = render_daily_bundle_pdf(unit, (window_start, window_end))
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to render daily bundle for unit %s", unit.name)
            skipped.append({"unit": unit.name, "reason": str(e)})
            continue

        arcname = "%s_daily_qa_%s.pdf" % (slugify(unit.name), label)
        pdfs[arcname] = pdf_bytes
        rendered.append(
            {"unit": unit.name, "arcname": arcname, "constancy": constancy.name}
        )

    zip_name = "daily_qa_report_%s.zip" % label
    zip_path = _resolve_zip_path(out_zip_path, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in pdfs.items():
            zf.writestr(arcname, data)

    summary = {
        "label": label,
        "zip_path": zip_path,
        "zip_name": zip_name,
        "count": len(pdfs),
        "rendered": rendered,
        "skipped": skipped,
    }
    logger.info(
        "Daily QA bundles %s: %d PDFs rendered, %d skipped",
        label,
        len(pdfs),
        len(skipped),
    )
    return zip_path, summary


# Convenience alias so the daily-bundle flow shares the archive delivery path.
def email_daily_bundles(zip_path, recipients, summary, max_attach_mb=24):
    """Email the daily-QA bundle zip (size guard applies)."""
    return email_archive(zip_path, recipients, summary, max_attach_mb=max_attach_mb)
