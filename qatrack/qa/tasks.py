"""Scheduled tasks for django-q (myQA import, autosave cleanup)."""

import logging
import os
import subprocess
import sys

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from qatrack.myqa_import import (
    compute_multi_flags,
    discover_tasknames,
    get_connection,
    import_session,
    query_sessions,
)
from qatrack.qa.models import AutoSave, TestInstanceStatus

logger = logging.getLogger("django-q2")


def clean_autosaves():

    max_date = timezone.now() - timezone.timedelta(days=settings.AUTOSAVE_DAYS_TO_KEEP)
    AutoSave.objects.filter(modified__lte=max_date).delete()


def import_myqa_all(dry_run=False, unit=None, days=30, task_name=None):
    """Import myQA sessions across all (or one) TaskNames.

    Replaces the previous task-type-keyed iteration with TaskName-driven
    iteration. For each discovered TaskName (or the single TaskName passed via
    ``task_name``), sessions are queried by exact TaskName match and imported
    via :func:`qatrack.myqa_import.import_session`, which aggregates every
    execution type present in the session into one TestListInstance.

    Parameters
    ----------
    dry_run : bool
        If True, preview only (no DB writes).
    unit : int or None
        If set, only import sessions for this specific unit number. Sessions
        for other units are skipped (still counted in ``total``).
    days : int
        Look back this many days from now for sessions.
    task_name : str or None
        If set, only import for this specific TaskName; otherwise discover
        all TaskNames from myQA.

    Returns
    -------
    dict
        Counts: imported, skipped_dup, skipped_empty, skipped_err, total.
    """
    result = {
        "imported": 0,
        "skipped_dup": 0,
        "skipped_err": 0,
        "skipped_empty": 0,
        "total": 0,
    }

    # Open a short-lived connection just to discover TaskNames, then close it.
    # Each TaskName batch re-opens its own connection below.
    conn = get_connection()
    try:
        tasknames = [task_name] if task_name else discover_tasknames(conn)
    finally:
        conn.close()

    internal_user = User.objects.get(username="QATrack+ Internal")
    default_status = TestInstanceStatus.objects.get(is_default=True)
    status_map = {
        "unreviewed": default_status,
        "approved": TestInstanceStatus.objects.get(slug="Approved"),
        "skipped": TestInstanceStatus.objects.get(slug="skipped"),
    }

    for tn in tasknames:
        # Re-open per TaskName so a long iteration doesn't sit on a stale
        # connection. The connection is closed explicitly at the end.
        conn = get_connection()
        try:
            sessions = query_sessions(conn, tn, days)
            if unit is not None:
                sessions = [s for s in sessions if s["unit_number"] == unit]
            result["total"] += len(sessions)
            print(f"  {tn}: found {len(sessions)} sessions")
            multi_flags = compute_multi_flags(conn, tn)

            for session in sessions:
                if dry_run:
                    ref_date = session["reference_date"]
                    ref_date_str = (
                        ref_date.date() if hasattr(ref_date, "date") else ref_date
                    )
                    print(
                        f"    WOULD IMPORT unit {session['unit_number']} on {ref_date_str}"
                    )
                    result["imported"] += 1
                    continue

                outcome = import_session(
                    conn,
                    tn,
                    session,
                    internal_user,
                    default_status,
                    status_map,
                    multi_flags=multi_flags,
                )
                status = outcome["status"]
                if status == "imported":
                    result["imported"] += 1
                    print(
                        f"    IMPORTED unit {session['unit_number']}: {outcome['count']} tests"
                    )
                elif status == "skipped_dup":
                    result["skipped_dup"] += 1
                elif status == "skipped_empty":
                    result["skipped_empty"] += 1
                else:
                    result["skipped_err"] += 1
                    print(
                        f"    ERROR unit {session['unit_number']}: {outcome.get('reason')}"
                    )
        finally:
            conn.close()

    summary = (
        f"Done: {result['imported']} imported, "
        f"{result['skipped_dup']} duplicates, "
        f"{result['skipped_empty']} empty, "
        f"{result['skipped_err']} errors "
        f"(out of {result['total']} found)"
    )
    print(summary)
    return result


def import_matrix_monthly(dry_run=False, unit=None, days=30):
    """Import monthly matrix dosimetry data from myQA into QATrack+.

    .. deprecated::
       The matrix-dosimetry-import TestList has been removed by the
       myqa-dynamic-taskname-import redesign. Monthly dosimetry is now
       imported per TaskName via :func:`import_myqa_all`. This shim is kept
       only so old scheduled tasks / scripts don't crash — it does a best-
       effort import of Monthly Dosimetry TaskNames.
    """
    print(
        "DEPRECATED: import_matrix_monthly is deprecated. Monthly dosimetry "
        "is now imported per TaskName via import_myqa_all. Pass --task-name "
        "with the relevant TaskName (e.g. '5.Tmt.Linac.M.Dosimetry - Monthly QA')."
    )
    return import_myqa_all(dry_run=dry_run, unit=unit, days=days)


def _run_setup_detached(log_name="setup_myqa_tasks.log"):
    """Spawn ``manage.py setup_myqa_tests`` as a detached background process.

    ``setup_myqa_tests`` iterates all TaskNames in myQA and runs several
    queries per TaskName — it takes several minutes, far exceeding
    ``Q_CLUSTER['timeout']`` (60 s). The django-q entry point therefore
    spawns the management command detached and returns immediately; the
    command itself does the discovery + UTC/UTI creation and writes output
    to ``<repo>/pdf/<log_name>``.

    Mirrors :func:`qatrack.reports.tasks._run_detached` — duplicated rather
    than shared to avoid a cross-app import dependency for a 20-line helper.
    """
    from qatrack.reports import qa_archive

    manage = os.path.join(settings.PROJECT_ROOT, "..", "manage.py")
    log_path = os.path.join(qa_archive.default_out_dir(), log_name)
    cmd = [sys.executable, manage, "setup_myqa_tests"]
    # start_new_session=True detaches the child from the qcluster worker so
    # it survives worker recycling; the qcluster task returns at once.
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
    logger.info("Spawned detached: setup_myqa_tests (log: %s)", log_path)
    return {"spawned": True, "command": "setup_myqa_tests", "log": log_path}


def run_setup_myqa_tests(META=None):
    """django-q entry point for weekly ``setup_myqa_tests``.

    Spawns ``manage.py setup_myqa_tests`` as a detached process and returns
    immediately. Use this so newly-commissioned units (e.g. RFT26) and new
    myQA TaskNames get their UTCs/UTIs created without requiring a manual
    setup run after every change in myQA. ``setup_myqa_tests`` is idempotent
    so weekly runs are safe (existing TestLists/UTCs/UTIs are no-ops via
    ``get_or_create``).

    The ``META`` arg is accepted for symmetry with
    :func:`qatrack.myqa_import.import_myqa_results` and is currently unused.
    """
    return _run_setup_detached()
