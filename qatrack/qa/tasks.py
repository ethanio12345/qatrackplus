from django.utils import timezone

from qatrack.qa.models import AutoSave
from qatrack.myqa_import import TASK_TYPE_REGISTRY, get_importer


def clean_autosaves():

    max_date = timezone.now() - timezone.timedelta(days=settings.AUTOSAVE_DAYS_TO_KEEP)
    AutoSave.objects.filter(modified__lte=max_date).delete()


def import_myqa_all(dry_run=False, unit=None, days=30, task=None):
    """
    Import all myQA task types for all (or specified) units.

    Parameters
    ----------
    dry_run : bool
        If True, preview only (no DB writes).
    unit : int or None
        If set, only import for this specific unit number.
    days : int
        Look back this many days from now for sessions.
    task : str or None
        If set, only import for this specific task type key.

    Returns
    -------
    dict
        Counts of imported, skipped_dup, skipped_err, total.
    """
    result = {'imported': 0, 'skipped_dup': 0, 'skipped_err': 0, 'total': 0}

    task_types = [task] if task else list(TASK_TYPE_REGISTRY.keys())

    for task_key in task_types:
        importer = get_importer(task_key)
        if importer is None:
            msg = f"  SKIP unknown task type: {task_key}"
            print(msg)
            continue

        unit_numbers = [unit] if unit else None

        try:
            sessions = importer.query_new_sessions(days=days, unit_numbers=unit_numbers)
            result['total'] += len(sessions)
            msg = f"  {task_key}: found {len(sessions)} sessions"
            print(msg)

            for session in sessions:
                if dry_run:
                    msg = (
                        f"    WOULD IMPORT unit {session['unit_number']} "
                        f"on {session['reference_date'].date() if hasattr(session['reference_date'], 'date') else session['reference_date']}"
                    )
                    print(msg)
                    result['imported'] += 1
                    continue

                import_result = importer.import_session(session)
                if import_result['status'] == 'imported':
                    result['imported'] += 1
                    print(f"    IMPORTED unit {session['unit_number']}: {import_result['count']} tests")
                elif import_result['status'] == 'skipped_dup':
                    result['skipped_dup'] += 1
                    print(f"    SKIP unit {session['unit_number']}: {import_result['reason']}")
                else:
                    result['skipped_err'] += 1
                    print(f"    ERROR unit {session['unit_number']}: {import_result['reason']}")

        finally:
            importer.close()

    summary = (
        f"Done: {result['imported']} imported, "
        f"{result['skipped_dup']} duplicates, "
        f"{result['skipped_err']} errors "
        f"(out of {result['total']} found)"
    )
    print(summary)
    return result


def import_matrix_monthly(dry_run=False, unit=None, days=30):
    """
    Import monthly matrix dosimetry data from myQA into QATrack+.

    .. deprecated::
       Use ``import_myqa_all(task='myqa_profile')`` instead. This function
       is kept for backward compatibility and delegates to the new import
       engine.

    Queries myQA for monthly dosimetry sessions within the lookback window,
    checks de-duplication by mtx_taskid string_value, and creates
    TestListInstance + TestInstance records for new sessions.

    Parameters
    ----------
    dry_run : bool
        If True, only preview what would be imported (no DB writes).
    unit : int or None
        If set, only import for this specific unit number.
    days : int
        Look back this many days from now for sessions.

    Returns
    -------
    dict
        Counts of imported, skipped_dup, skipped_err, total.
    """
    print("DEPRECATED: import_matrix_monthly is deprecated. Use import_myqa_all(task='myqa_profile') instead.")
    return import_myqa_all(dry_run=dry_run, unit=unit, days=days, task='myqa_profile')
