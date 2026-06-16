import json

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

import pymssql

from qatrack.qa.models import (
    AutoSave, Test, TestInstance, TestInstanceStatus,
    TestList, TestListInstance, UnitTestCollection, UnitTestInfo,
)
from qatrack.matrix_import import import_matrix_results


def clean_autosaves():

    max_date = timezone.now() - timezone.timedelta(days=settings.AUTOSAVE_DAYS_TO_KEEP)
    AutoSave.objects.filter(modified__lte=max_date).delete()


def import_matrix_monthly(dry_run=False, unit=None, days=30):
    """
    Import monthly matrix dosimetry data from myQA into QATrack+.

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
    result = {'imported': 0, 'skipped_dup': 0, 'skipped_err': 0, 'total': 0}

    # Pre-fetch lookups
    tl = TestList.objects.get(pk=133)
    ct = ContentType.objects.get_for_model(tl)
    internal_user = User.objects.get(username='QATrack+ Internal')
    default_status = TestInstanceStatus.objects.get(is_default=True)
    tests_by_slug = {t.slug: t for t in Test.objects.filter(slug__startswith='mtx_')}
    all_utis = {}
    for uti in UnitTestInfo.objects.filter(test__slug__startswith='mtx_').select_related('unit'):
        all_utis[(uti.unit.number, uti.test.slug)] = uti

    # Linac mapping: unit_number -> myQA linac name
    linac_map = {
        1: "CST15 - H192361",
        2: "OBK15 - H192362",
        3: "LA317 - H192972",
        4: "LA414 - H191733",
        5: "LA512 - H191182",
        7: "LA524 - H196713",
        8: "LA224 - H196406",
        50: "DXR - GM0191",
    }

    # Cutoff date for lookback
    cutoff = timezone.now() - timezone.timedelta(days=days)
    cutoff_naive = cutoff.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    now_naive = timezone.now().replace(tzinfo=None)

    # Build myQA connection
    try:
        conn = pymssql.connect(
            server=settings.MYQA_DB_SERVER,
            database=settings.MYQA_DB_NAME,
            user=settings.MYQA_DB_USERNAME,
            password=settings.MYQA_DB_PASSWORD,
        )
    except Exception as e:
        result['skipped_err'] = 1
        log_msg = f"myQA connection failed: {e}"
        print(log_msg)
        result['error'] = log_msg
        return result

    cursor = conn.cursor(as_dict=True)

    # Determine which units to process
    units_to_process = [u for u in linac_map if unit is None or u == unit]

    for unit_num in units_to_process:
        linac_name = linac_map[unit_num]
        utc = UnitTestCollection.objects.filter(
            unit__number=unit_num,
            content_type=ct,
            object_id=tl.pk,
        ).first()
        if utc is None:
            continue

        # Task name pattern
        if unit_num == 50:
            taskname_pattern = "5.Tmt.DXR.M%"
        else:
            taskname_pattern = "5.Tmt.Linac.M%Dosimetry%"

        # Query myQA for sessions in the lookback window
        cursor.execute("""
            SELECT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate, te.TaskName
            FROM MQA_TestExecutions te
            WHERE te.RadiationDeviceName = %s
              AND te.TaskName LIKE %s
              AND te.ReferenceDate IS NOT NULL
              AND te.ReferenceDate >= %s
              AND te.ReferenceDate <= %s
            ORDER BY te.ReferenceDate, te.FinishingDate
        """, (linac_name, taskname_pattern, cutoff_naive, now_naive))

        # Deduplicate by ReferenceDate (one session per day)
        sessions = {}
        for row in cursor.fetchall():
            d = row['ReferenceDate']
            if d not in sessions:
                sessions[d] = row

        result['total'] += len(sessions)

        for ref_date, row in sorted(sessions.items()):
            taskid = str(row['TaskExecutionId'])
            fin_date = row['FinishingDate'] or ref_date

            # De-duplication check
            dup = TestInstance.objects.filter(
                unit_test_info__test__slug='mtx_taskid',
                unit_test_info__unit__number=unit_num,
                string_value=taskid,
            ).exists()

            if dup:
                result['skipped_dup'] += 1
                msg = f"  SKIP #{unit_num} {linac_name} on {ref_date.date()}: duplicate taskid {taskid[:8]}..."
                print(msg)
                continue

            # Import from myQA
            META = {'unit_number': unit_num, 'work_started': ref_date}
            try:
                raw = import_matrix_results(META)
                data = json.loads(raw)
            except Exception as e:
                result['skipped_err'] += 1
                msg = f"  ERROR #{unit_num} {linac_name} on {ref_date.date()}: {e}"
                print(msg)
                continue

            if data.get('error') and not data.get('mtx_taskid'):
                result['skipped_err'] += 1
                msg = f"  ERROR #{unit_num} {linac_name} on {ref_date.date()}: {data['error']}"
                print(msg)
                continue

            # Gather non-null readings
            readings = {k: v for k, v in data.items() if v is not None and k != 'error'}

            if dry_run:
                msg = f"  WOULD IMPORT #{unit_num} {linac_name} on {ref_date.date()}: {len(readings)} readings"
                print(msg)
                result['imported'] += 1
                continue

            # Create TLI + TIs in a transaction
            try:
                with transaction.atomic():
                    tli = TestListInstance(
                        unit_test_collection=utc,
                        test_list=tl,
                        work_started=ref_date,
                        work_completed=fin_date or timezone.now(),
                        in_progress=False,
                        include_for_scheduling=False,
                        day=0,
                        created_by=internal_user,
                        modified_by=internal_user,
                        modified=timezone.now(),
                    )
                    tli.save()

                    tis = []
                    for slug, val in readings.items():
                        test = tests_by_slug.get(slug)
                        if test is None:
                            continue
                        uti = all_utis.get((unit_num, slug))
                        if uti is None:
                            continue

                        tis.append(TestInstance(
                            test_list_instance=tli,
                            unit_test_info=uti,
                            value=float(val) if isinstance(val, (int, float)) else None,
                            string_value=val if isinstance(val, str) else None,
                            work_started=ref_date,
                            work_completed=fin_date or timezone.now(),
                            created_by=internal_user,
                            modified_by=internal_user,
                            status=default_status,
                            pass_fail='no_tol',
                            order=0,
                        ))

                    if tis:
                        TestInstance.objects.bulk_create(tis)

                result['imported'] += 1
                msg = f"  IMPORTED #{unit_num} {linac_name} on {ref_date.date()}: {len(tis)} tests (taskid={taskid[:8]}...)"
                print(msg)

            except Exception as e:
                result['skipped_err'] += 1
                msg = f"  ERROR #{unit_num} {linac_name} on {ref_date.date()}: DB persist failed: {e}"
                print(msg)

    conn.close()
    summary = (
        f"Done: {result['imported']} imported, "
        f"{result['skipped_dup']} duplicates, "
        f"{result['skipped_err']} errors "
        f"(out of {result['total']} found)"
    )
    print(summary)
    return result
