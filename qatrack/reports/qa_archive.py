"""Linac QA archive: render one PDF per canonical UTC, zip, and deliver.

Implements the linac-qa-archive capability (design D1/D5/D6/D7):

  * one PDF per selected UnitTestCollection, rendered via the existing
    :class:`TestListInstanceDetailsReport` engine with chart links enabled
  * packaged into ``linac_qa_archive_{YYYY-MM}.zip`` with per-unit subdirs
  * delivered by email (with a size guard) or to the filesystem
"""

import logging
import os
import tempfile
import zipfile

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.utils.text import slugify

from qatrack.qatrack_core.email import send_email_to_users
from qatrack.reports.qa_selection import select_archive_utcs
from qatrack.reports.qc.testlistinstance import TestListInstanceDetailsReport

logger = logging.getLogger("qatrack")

# Default max zip size (MB) permitted as an email attachment (spec size guard).
DEFAULT_MAX_ATTACH_MB = 24


def default_out_dir():
    """Return the default filesystem folder for scheduled PDF production.

    Defaults to ``<repo_root>/pdf`` (i.e. ``settings.PROJECT_ROOT/..``/pdf). May
    be overridden via the ``QA_REPORTS_OUT_DIR`` setting. The directory is
    created if missing.
    """
    path = getattr(settings, "QA_REPORTS_OUT_DIR", None) or os.path.join(
        settings.PROJECT_ROOT, "..", "pdf"
    )
    os.makedirs(path, exist_ok=True)
    return path


def _work_completed_range(window_start, window_end):
    """Format a window as the date-range string the report filter expects."""
    return "%s - %s" % (
        window_start.strftime("%d %b %Y"),
        window_end.strftime("%d %b %Y"),
    )


def _system_user():
    """Return a user to attribute programmatic report renders to."""
    return User.objects.filter(is_superuser=True).first() or User.objects.first()


def _report_base_opts(window_start, window_end, include_chart_links):
    return {
        "include_chart_links": include_chart_links,
        "chart_window": {"start": window_start, "end": window_end},
        "paper_size": "letter",
    }


def render_utc_pdf(utc, window, include_chart_links=True):
    """Render one PDF (bytes) for a single UTC scoped to ``window``.

    Wraps :class:`TestListInstanceDetailsReport` scoped to one UTC + window
    (design D5). ``include_chart_links`` toggles the chart-link column.
    """
    window_start, window_end = window
    report_opts = {
        "unit_test_collection": [utc.pk],
        "work_completed": _work_completed_range(window_start, window_end),
    }
    base_opts = _report_base_opts(window_start, window_end, include_chart_links)
    rep = TestListInstanceDetailsReport(
        base_opts=base_opts, report_opts=report_opts, user=_system_user()
    )
    rep.report_format = "pdf"
    return rep.to_pdf()


def _utc_in_window(utc, window_start, window_end):
    return utc.testlistinstance_set.filter(
        work_completed__gte=window_start, work_completed__lte=window_end
    ).exists()


def _resolve_zip_path(out_dir, zip_name):
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, zip_name)
    tmp = tempfile.mkdtemp(prefix="qa_archive_")
    return os.path.join(tmp, zip_name)


def generate_archive(window_start, window_end, out_zip_path=None):
    """Render one PDF per selected UTC and package them into a zip.

    Returns a ``(zip_path, summary)`` tuple. ``summary`` is a dict with:

      * ``label``: ``YYYY-MM`` window label
      * ``zip_path`` / ``zip_name``: location of the produced archive
      * ``count``: number of PDFs rendered
      * ``rendered``: list of dicts (``unit``, ``utc``, ``arcname``, ``tli_count``)
      * ``skipped``: list of dicts (``unit``, ``utc``, ``reason``)
    """
    label = window_start.strftime("%Y-%m")
    utcs = select_archive_utcs(window_start, window_end)

    rendered = []
    skipped = []
    pdfs = {}

    for utc in utcs:
        unit_name = utc.unit.name
        if not _utc_in_window(utc, window_start, window_end):
            skipped.append(
                {
                    "unit": unit_name,
                    "utc": utc.name,
                    "reason": "no TLIs in window at render time",
                }
            )
            continue
        try:
            pdf_bytes = render_utc_pdf(utc, (window_start, window_end))
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to render UTC %s (%s)", utc.pk, utc.name)
            skipped.append({"unit": unit_name, "utc": utc.name, "reason": str(e)})
            continue

        arcname = "%s/%s_%s.pdf" % (slugify(unit_name), slugify(utc.name), label)
        pdfs[arcname] = pdf_bytes
        rendered.append(
            {
                "unit": unit_name,
                "utc": utc.name,
                "arcname": arcname,
                "tli_count": utc.tli_in_window,
            }
        )

    zip_name = "linac_qa_archive_%s.zip" % label
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
        "Linac QA archive %s: %d PDFs rendered, %d skipped",
        label,
        len(pdfs),
        len(skipped),
    )
    return zip_path, summary


def recipients_for_group(group_name):
    """Return a list of RFC-style recipient strings for the named Group.

    Includes users in the group with an email address. Returns an empty list if
    the group does not exist.
    """
    try:
        group = Group.objects.get(name=group_name)
    except Group.DoesNotExist:
        return []
    recipients = []
    for u in group.user_set.exclude(email="").values_list(
        "first_name", "last_name", "email"
    ):
        first, last, email = u
        if first and last:
            recipients.append('"%s %s" <%s>' % (first, last, email))
        else:
            recipients.append(email)
    return recipients


def email_archive(zip_path, recipients, summary, max_attach_mb=DEFAULT_MAX_ATTACH_MB):
    """Email the archive zip to ``recipients`` with a size guard.

    If the zip is at or under ``max_attach_mb`` it is attached; otherwise the
    email body carries the on-site path/URL and a size warning (spec size
    guard). Returns ``True`` if an attachment was included.
    """
    if not recipients:
        logger.warning("email_archive called with no recipients; skipping send.")
        return False

    zip_size = os.path.getsize(zip_path)
    max_bytes = max_attach_mb * 1024 * 1024
    attach = zip_size <= max_bytes

    context = {
        "summary": summary,
        "zip_path": zip_path,
        "zip_name": summary.get("zip_name", os.path.basename(zip_path)),
        "label": summary.get("label"),
        "count": summary.get("count", 0),
        "skipped": summary.get("skipped", []),
        "attached": attach,
        "too_large": not attach,
        "max_attach_mb": max_attach_mb,
    }

    attachments = []
    if attach:
        with open(zip_path, "rb") as f:
            attachments.append((context["zip_name"], f.read(), "application/zip"))

    send_email_to_users(
        recipients,
        "reports/qa_archive_email.html",
        context=context,
        subject_template="reports/qa_archive_email_subject.txt",
        text_template="reports/qa_archive_email.txt",
        attachments=attachments,
    )
    return attach
