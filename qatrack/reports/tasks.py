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


def _run_detached(command, args, log_name):
    """Spawn ``manage.py <command>`` as a detached background process.

    Returns immediately (within the django-q task timeout). The command runs
    independently of the qcluster worker so long renders (~45 min) are not
    killed by ``Q_CLUSTER['timeout']``. Output is appended to
    ``<pdf folder>/<log_name>``.
    """
    import os
    import subprocess
    import sys

    from django.conf import settings

    from qatrack.reports import qa_archive

    manage = os.path.join(settings.PROJECT_ROOT, "manage.py")
    log_path = os.path.join(qa_archive.default_out_dir(), log_name)
    cmd = [sys.executable, manage, command] + args
    # start_new_session=True detaches the child from the qcluster worker so it
    # survives worker recycling; the qcluster task itself returns at once.
    log_f = open(log_path, "ab")
    try:
        subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_f.close()
    logger.info("Spawned detached: %s %s (log: %s)", command, args, log_path)
    return {"spawned": True, "command": command, "args": args, "log": log_path}


def _delivery_args(window, email_group, out_dir):
    args = ["--window", str(window)]
    if email_group:
        args += ["--email", str(email_group)]
    if out_dir:
        args += ["--out-dir", str(out_dir)]
    return args


def run_linac_qa_archive(META=None, window="lastmonth", email_group=None, out_dir=None):
    """django-q entry point for the linac QA archive.

    Spawns ``manage.py archive_linac_qa`` as a detached process (the render
    takes ~40 min, far longer than the qcluster task timeout). Accepts either a
    single ``META`` dict or explicit keyword args (for django-q ``kwargs``
    scheduling). Returns immediately with the spawn status.
    """
    if isinstance(META, dict):
        window = META.get("window", window)
        email_group = META.get("email_group", email_group)
        out_dir = META.get("out_dir", out_dir)

    from qatrack.reports.qa_selection import resolve_window

    resolve_window(window)  # validate eagerly so a bad window surfaces in the task log
    args = _delivery_args(window, email_group, out_dir)
    return _run_detached("archive_linac_qa", args, "linac_qa_archive.log")


def run_daily_qa_bundle(META=None, window="lastmonth", email_group=None, out_dir=None):
    """django-q entry point for the daily constancy bundle.

    Spawns ``manage.py daily_qa_bundle`` as a detached process (the render takes
    ~45 min). Same META/kwargs contract as :func:`run_linac_qa_archive`.
    """
    if isinstance(META, dict):
        window = META.get("window", window)
        email_group = META.get("email_group", email_group)
        out_dir = META.get("out_dir", out_dir)

    from qatrack.reports.qa_selection import resolve_window

    resolve_window(window)
    args = _delivery_args(window, email_group, out_dir)
    return _run_detached("daily_qa_bundle", args, "daily_qa_bundle.log")
