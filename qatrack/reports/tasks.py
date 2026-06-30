import logging

from django.conf import settings
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import schedule

from qatrack.qatrack_core.email import send_email_to_users
from qatrack.qatrack_core.tasks import (
    qatrack_task_wrapper,
    run_periodic_scheduler,
)
from qatrack.reports.models import ReportSchedule
from qatrack.reports.reports import CONTENT_TYPES

logger = logging.getLogger('django-q2')


@qatrack_task_wrapper
def run_reports():
    """Should run every 15 minutes at HH:07:30, HH:22:30, HH:37:30, HH:52:30"""

    run_periodic_scheduler(
        ReportSchedule, "run_reports", schedule_report, time_field="time", recurrence_field="schedule"
    )


@qatrack_task_wrapper
def schedule_report(s, send_time):

    logger.info("Scheduling report %s for %s" % (s.report_id, send_time))
    name = "Send report %d %s" % (s.report_id, send_time.isoformat())
    schedule(
        "qatrack.reports.tasks.send_report",
        s.id,
        name,
        name=name,
        schedule_type=Schedule.ONCE,
        repeats=1,
        next_run=send_time,
        task_name=name,
    )


@qatrack_task_wrapper
def send_report(schedule_id, task_name=""):

    logger.info("Attempting Send of ReportSchedule %s" % schedule_id)

    s = ReportSchedule.objects.filter(id=schedule_id).first()
    if s:
        recipients = s.recipients()
        if not recipients:
            logger.info("Send of ReportSchedule %s requested, but no recipients" % schedule_id)
            return
    else:
        logger.info("Send of ReportSchedule %s requested, but no such ReportSchedule exists" % schedule_id)
        return

    fname, attach = s.report.render(user=s.created_by)

    try:
        send_email_to_users(
            recipients,
            "reports/email.html",
            context={
                'report': s.report,
                "report_schedule": s
            },
            subject_template="reports/email_subject.txt",
            text_template="reports/email.txt",
            attachments=[(fname, attach, CONTENT_TYPES[s.report.report_format])],
        )
        logger.info("Sent ReportSchedule %s (report %s) at %s" % (schedule_id, s.report_id, timezone.now()))
        try:
            Schedule.objects.get(name=task_name).delete()
        except:  # noqa: E722  # pragma: nocover
            logger.exception("Unable to delete Schedule.name = %s after successful send" % task_name)
    except:  # noqa: E722  # pragma: nocover
        logger.exception(
            "Error sending email for ReportSchedule %s (report %s) at %s." % (schedule_id, s.report_id, timezone.now())
        )
        fail_silently = getattr(settings, "EMAIL_FAIL_SILENTLY", True)
        if not fail_silently:
            raise
    finally:
        s.last_sent = timezone.now()
        s.save()


def run_linac_qa_archive(META=None, window="lastmonth", email_group=None, out_dir=None):
    """django-q entry point: render + zip the linac QA archive, then deliver.

    Delivery: if ``out_dir`` is given (or no ``email_group`` is set) the zip is
    written to that folder (defaulting to the ``pdf`` folder); email is only
    sent when ``email_group`` is set. Accepts either a single ``META`` dict
    (``{"window": ..., "email_group": ..., "out_dir": ...}``, mirroring the myQA
    Schedule #7 pattern) or explicit keyword args (for django-q ``kwargs``
    scheduling).
    """
    from qatrack.reports import qa_archive
    from qatrack.reports.qa_selection import resolve_window

    if isinstance(META, dict):
        window = META.get("window", window)
        email_group = META.get("email_group", email_group)
        out_dir = META.get("out_dir", out_dir)

    window_start, window_end = resolve_window(window)
    if not email_group and not out_dir:
        out_dir = qa_archive.default_out_dir()
    zip_path, summary = qa_archive.generate_archive(window_start, window_end, out_dir)
    logger.info("Linac QA archive for %s produced: %s", summary["label"], zip_path)

    if email_group:
        recipients = qa_archive.recipients_for_group(email_group)
        if recipients:
            qa_archive.email_archive(zip_path, recipients, summary)
        else:
            logger.warning("run_linac_qa_archive: group %r has no recipients", email_group)
    return summary


def run_daily_qa_bundle(META=None, window="lastmonth", email_group=None, out_dir=None):
    """django-q entry point: render + zip the daily constancy bundle, then deliver.

    Same delivery semantics as :func:`run_linac_qa_archive`: writes to
    ``out_dir`` (default ``pdf`` folder) unless ``email_group`` triggers email.
    """
    from qatrack.reports import qa_archive
    from qatrack.reports.qa_selection import resolve_window
    from qatrack.reports.qc import daily_bundle

    if isinstance(META, dict):
        window = META.get("window", window)
        email_group = META.get("email_group", email_group)
        out_dir = META.get("out_dir", out_dir)

    window_start, window_end = resolve_window(window)
    if not email_group and not out_dir:
        out_dir = qa_archive.default_out_dir()
    zip_path, summary = daily_bundle.generate_daily_bundles(window_start, window_end, out_dir)
    logger.info("Daily QA bundle for %s produced: %s", summary["label"], zip_path)

    if email_group:
        recipients = qa_archive.recipients_for_group(email_group)
        if recipients:
            daily_bundle.email_daily_bundles(zip_path, recipients, summary)
        else:
            logger.warning("run_daily_qa_bundle: group %r has no recipients", email_group)
    return summary
