import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

import pymssql

from qatrack.qa.models import (
    Test, TestInstance, TestInstanceStatus, TestList,
    TestListInstance, Tolerance, UnitTestCollection, UnitTestInfo,
)

MYQA_DB_SETTINGS = {
    'server': settings.MYQA_DB_SERVER,
    'database': settings.MYQA_DB_NAME,
    'username': settings.MYQA_DB_USERNAME,
    'password': settings.MYQA_DB_PASSWORD,
}

LINAC_MAP = {
    1: "CST15 - H192361",
    2: "OBK15 - H192362",
    3: "LA317 - H192972",
    4: "LA414 - H191733",
    5: "LA512 - H191182",
    7: "LA524 - H196713",
    8: "LA224 - H196406",
    50: "DXR - GM0191",
}


def slugify_name(list_slug: str, name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9.]+', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_')
    return f'{list_slug}_{slug}'


def myqa_to_qatrack_tolerance(
    warn_on: Optional[float],
    fail_on: Optional[float],
    is_relative: bool = False,
    limit_tendency: int = 0,
) -> Optional[Tolerance]:
    if warn_on is None and fail_on is None:
        return None

    if is_relative:
        tol_type = 'percent'
    else:
        tol_type = 'absolute'

    if limit_tendency == 0:
        tol_lower = -(warn_on or 0)
        tol_upper = +(warn_on or 0)
    elif limit_tendency == 1:
        tol_lower = -(fail_on or 0)
        tol_upper = None
    elif limit_tendency == 2:
        tol_lower = None
        tol_upper = fail_on
    else:
        return None

    tol, _ = Tolerance.objects.get_or_create(
        type=tol_type,
        tol_low=tol_lower,
        tol_high=tol_upper,
        act_low=-(fail_on or 0) if limit_tendency == 0 else tol_lower,
        act_high=+(fail_on or 0) if limit_tendency == 0 else tol_upper,
    )
    return tol


class MyqaImportBase:

    task_name_patterns: List[str] = []
    list_slug: str = ''
    test_slug_prefix: str = ''
    frequency: str = ''
    execution_type: str = ''

    def __init__(self):
        self.conn = self._get_connection()
        self.internal_user = User.objects.get(username='QATrack+ Internal')
        self.default_status = TestInstanceStatus.objects.get(is_default=True)
        if not self.test_slug_prefix:
            self.test_slug_prefix = f'{self.list_slug}_'

    def _get_connection(self):
        return pymssql.connect(
            server=MYQA_DB_SETTINGS['server'],
            database=MYQA_DB_SETTINGS['database'],
            user=MYQA_DB_SETTINGS['username'],
            password=MYQA_DB_SETTINGS['password'],
        )

    def close(self):
        if self.conn:
            self.conn.close()

    def query_new_sessions(self, days: int = 30, unit_numbers: Optional[List[int]] = None):
        if unit_numbers is None:
            unit_numbers = list(LINAC_MAP.keys())

        cutoff = timezone.now() - timezone.timedelta(days=days)
        cutoff_naive = cutoff.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        now_naive = timezone.now().replace(tzinfo=None)

        sessions = []
        cursor = self.conn.cursor(as_dict=True)

        for unit_num in unit_numbers:
            linac_name = LINAC_MAP.get(unit_num)
            if linac_name is None:
                continue

            for pattern in self.task_name_patterns:
                cursor.execute("""
                    SELECT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate,
                           te.TaskName, te.RadiationDeviceName
                    FROM MQA_TestExecutions te
                    WHERE te.RadiationDeviceName = %s
                      AND te.TaskName LIKE %s
                      AND te.ReferenceDate IS NOT NULL
                      AND te.ReferenceDate >= %s
                      AND te.ReferenceDate <= %s
                    ORDER BY te.ReferenceDate, te.FinishingDate
                """, (linac_name, pattern, cutoff_naive, now_naive))

                for row in cursor.fetchall():
                    sessions.append({
                        'task_execution_id': str(row['TaskExecutionId']),
                        'reference_date': row['ReferenceDate'],
                        'finishing_date': row['FinishingDate'],
                        'task_name': row['TaskName'],
                        'unit_number': unit_num,
                        'linac_name': linac_name,
                    })

        return sessions

    def duplicate_check(self, execution_id: str, unit_number: int) -> bool:
        taskid_slug = f'{self.test_slug_prefix}taskid'
        return TestInstance.objects.filter(
            unit_test_info__test__slug=taskid_slug,
            unit_test_info__unit__number=unit_number,
            string_value=execution_id,
        ).exists()

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def import_session(self, session: dict) -> dict:
        unit_number = session['unit_number']
        execution_id = session['task_execution_id']
        ref_date = session['reference_date']
        fin_date = session['finishing_date'] or ref_date

        if self.duplicate_check(execution_id, unit_number):
            return {'status': 'skipped_dup', 'reason': f'duplicate taskid {execution_id[:8]}...'}

        results = self.extract_results(execution_id)
        if results.get('error'):
            return {'status': 'error', 'reason': results['error']}

        test_list = TestList.objects.get(slug=self.list_slug)
        ct = ContentType.objects.get_for_model(test_list)
        utc = UnitTestCollection.objects.filter(
            unit__number=unit_number,
            content_type=ct,
            object_id=test_list.pk,
        ).first()
        if utc is None:
            return {'status': 'error', 'reason': f'No UTC for unit {unit_number} / list {self.list_slug}'}

        tests_by_slug = {t.slug: t for t in Test.objects.filter(slug__startswith=self.test_slug_prefix)}
        all_utis = {}
        for uti in UnitTestInfo.objects.filter(test__slug__startswith=self.test_slug_prefix).select_related('unit'):
            all_utis[(uti.unit.number, uti.test.slug)] = uti

        try:
            with transaction.atomic():
                tli = TestListInstance(
                    unit_test_collection=utc,
                    test_list=test_list,
                    work_started=ref_date,
                    work_completed=fin_date or timezone.now(),
                    in_progress=False,
                    include_for_scheduling=False,
                    day=0,
                    created_by=self.internal_user,
                    modified_by=self.internal_user,
                    modified=timezone.now(),
                )
                tli.save()

                tis = []
                for slug, val in results.items():
                    if slug == 'error':
                        continue
                    test = tests_by_slug.get(slug)
                    if test is None:
                        continue
                    uti = all_utis.get((unit_number, slug))
                    if uti is None:
                        continue

                    tis.append(TestInstance(
                        test_list_instance=tli,
                        unit_test_info=uti,
                        value=float(val) if isinstance(val, (int, float)) else None,
                        string_value=str(val) if isinstance(val, str) else None,
                        work_started=ref_date,
                        work_completed=fin_date or timezone.now(),
                        created_by=self.internal_user,
                        modified_by=self.internal_user,
                        status=self.default_status,
                        pass_fail='no_tol',
                        order=0,
                    ))

                if tis:
                    TestInstance.objects.bulk_create(tis)

            return {'status': 'imported', 'count': len(tis)}

        except Exception as e:
            return {'status': 'error', 'reason': str(e)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MyqaNumericImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.N%', '5.Tmt.DXR.N%']
    list_slug = 'myqa_numeric'
    frequency = 'daily'
    execution_type = 'Numeric'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT tc.Name, tcne.Actual, tcne.WarningTolerance, tcne.ErrorTolerance,
                   tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency
            FROM MQA_Numeric_TestConditionExecutions tcne
            JOIN MQA_TestConditions tc ON tcne.TestCondition_Id = tc.Id
            JOIN MQA_TestImplementationExecutions tie ON tcne.TestImplementationExecution_Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row['Name'])
            results[slug] = row['Actual']
            results[f'{slug}_warn'] = row['WarningTolerance']
            results[f'{slug}_fail'] = row['ErrorTolerance']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaPassFailImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.P%', '5.Tmt.DXR.P%']
    list_slug = 'myqa_passfail'
    frequency = 'daily'
    execution_type = 'PassFail'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT tc.Name, pfte.PassStatus
            FROM MQA_PassFail_TestExecutions pfte
            JOIN MQA_TestConditions tc ON pfte.TestCondition_Id = tc.Id
            JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row['Name'])
            results[slug] = row['PassStatus']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaProfileImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Dosimetry%', '5.Tmt.DXR.M%Dosimetry%']
    list_slug = 'matrix-dosimetry-import'
    test_slug_prefix = 'mtx_'
    frequency = 'monthly'
    execution_type = 'Profile'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT dpr.Actual, dpr.DisplayName, dpr.ProfileDirection,
                   dpr.Expected, dvc.EnergyValue, et.Description, dvc.IsFlatteningFilterFree
            FROM MQA_Dosimetry_Profile_Results dpr
            JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
                ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
            JOIN MQA_Dosimetry_Profile_TestExecutions dpte
                ON dpqie.Id = dpte.ProfileQueueItem_Id
            JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            LEFT JOIN DVC_RadiationDeviceEnergy dvc
                ON dpte.BeamQuality_RadiationDeviceEnergyId = dvc.Id
            LEFT JOIN DVC_EnergyType et ON dvc.EnergyTypeId = et.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            energy = str(round(row.get('EnergyValue', 0)))
            desc = (row.get('Description') or 'photons').lower()
            fff = row.get('IsFlatteningFilterFree')
            if desc == 'electrons':
                energy_tag = f'{energy}e'
            else:
                energy_tag = f'{energy}{"fff" if fff else "x"}'
            direction = 'il' if row.get('ProfileDirection') == 1 else 'cl'
            display_name = row.get('DisplayName', '')
            name_map = {
                'Flatness': 'flat', 'Symmetry': 'sym', 'Center': 'centre',
                'Field Width': 'width', 'Penumbra Left': 'lpen', 'Penumbra Right': 'rpen',
                'Inflection Point Left': 'inflection_left', 'Inflection Point Right': 'inflection_right',
                'Flatness 80%': 'flat_80', 'Flatness 90%': 'flat_90', 'Deviation': 'deviation',
            }
            mtype = name_map.get(display_name, display_name)
            slug = f'mtx_{mtype}_{direction}_{energy_tag}'
            results[slug] = round(row['Actual'], 4) if row['Actual'] is not None else None
        results['mtx_taskid'] = execution_id
        return results


class MyqaEnergyImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Energy%', '5.Tmt.DXR.M%Energy%']
    list_slug = 'matrix-dosimetry-import'
    test_slug_prefix = 'mtx_'
    frequency = 'monthly'
    execution_type = 'Energy'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT ece.Actual, ece.Expected, ete.WarningTolerance, ete.ErrorTolerance,
                   cqie.BeamQuality_EnergyValue, cqie.BeamQuality_EnergyDimension,
                   cqie.BeamQuality_IsFlatteningFilterFree, ece.ChamberNumber
            FROM MQA_Dosimetry_Energy_ChamberExecutions ece
            JOIN MQA_Dosimetry_Energy_QueueItemExecutions eqie
                ON ece.EnergyConstancyQueueItemExecution_Id = eqie.Id
            JOIN MQA_Dosimetry_Energy_TestExecutions ete ON eqie.EnergyConstancyExecution_Id = ete.Id
            JOIN MQA_TestImplementationExecutions tie ON ete.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON eqie.Id = cqie.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            energy = str(round(row.get('BeamQuality_EnergyValue', 0)))
            dim = row.get('BeamQuality_EnergyDimension', '6')
            mode = 'MeV' if dim == '6' else 'MV'
            fff = 'fff' if row.get('BeamQuality_IsFlatteningFilterFree') else ''
            chamber = row.get('ChamberNumber', 1)
            slug = f'mtx_energy_{energy}{"" if not fff else fff}_{mode.lower()}_ch{chamber}'
            results[slug] = round(row['Actual'], 4) if row['Actual'] is not None else None
        results['mtx_taskid'] = execution_id
        return results


class MyqaWedgeImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Wedge%', '5.Tmt.DXR.M%Wedge%']
    list_slug = 'matrix-dosimetry-import'
    test_slug_prefix = 'mtx_'
    frequency = 'monthly'
    execution_type = 'Wedge'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT wqie.ActualValue, wqie.ExpectedValue, wte.BeamQuality_EnergyValue,
                   wqie.Tolerance_Warn, wqie.Tolerance_Fail
            FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
            JOIN MQA_Dosimetry_Wedge_TestExecutions wte
                ON wqie.WedgeConstancyExecution_Id = wte.Id
            JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            energy = str(int(row.get('BeamQuality_EnergyValue', 0)))
            slug = f'mtx_wedge_cont_{energy}x'
            results[slug] = round(row['ActualValue'], 4) if row['ActualValue'] is not None else None
        results['mtx_taskid'] = execution_id
        return results


class MyqaOutputImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Output%', '5.Tmt.DXR.M%Output%']
    list_slug = 'myqa_monthly_output'
    frequency = 'monthly'
    execution_type = 'Output'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT oqie.ActualValue, oqie.ExpectedValue, oqie.Tolerance_Warn, oqie.Tolerance_Fail,
                   ote.BeamQuality_EnergyValue
            FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
            JOIN MQA_Dosimetry_Output_TestExecutions ote
                ON oqie.OutputConstancyExecution_Id = ote.Id
            JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            energy = str(int(row.get('BeamQuality_EnergyValue', 0)))
            slug = f'mtx_output_{energy}x'
            results[slug] = round(row['ActualValue'], 4) if row['ActualValue'] is not None else None
        results['mtx_taskid'] = execution_id
        return results


class MyqaMlcImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%MLC%', '5.Tmt.DXR.M%MLC%']
    list_slug = 'myqa_mlc'
    frequency = 'monthly'
    execution_type = 'MLC'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT mlcr.Actual, mlcr.DisplayName, mlcr.MlcPosition
            FROM MQA_MDL_MlcQA_Results mlcr
            JOIN MQA_MDL_MlcQA_QueueItemExecutions mlcqie
                ON mlcr.MlcQAQueueItemExecution_Id = mlcqie.Id
            JOIN MQA_TestImplementationExecutions tie ON mlcqie.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            display = row.get('DisplayName', '')
            position = row.get('MlcPosition', '')
            tag = f'{display}_{position}'.lower().replace(' ', '_')
            slug = slugify_name(self.list_slug, tag)
            results[slug] = row['Actual']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaCbctImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%CBCT%', '5.Tmt.DXR.M%CBCT%']
    list_slug = 'myqa_cbct'
    frequency = 'quarterly'
    execution_type = 'CBCT'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT cbctr.Actual, cbctr.DisplayName
            FROM MQA_MDL_Cbct_Results cbctr
            JOIN MQA_MDL_Cbct_QueueItemExecutions cbctqie
                ON cbctr.CbctQueueItemExecution_Id = cbctqie.Id
            JOIN MQA_TestImplementationExecutions tie ON cbctqie.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row.get('DisplayName', ''))
            results[slug] = row['Actual']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaPlanarImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Planar%', '5.Tmt.DXR.M%Planar%']
    list_slug = 'myqa_planar'
    frequency = 'monthly'
    execution_type = 'Planar'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT pr.Actual, pr.DisplayName
            FROM MQA_MDL_Planar_Results pr
            JOIN MQA_MDL_Planar_QueueItemExecutions pqie
                ON pr.PlanarQueueItemExecution_Id = pqie.Id
            JOIN MQA_TestImplementationExecutions tie ON pqie.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row.get('DisplayName', ''))
            results[slug] = row['Actual']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaVmatImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%VMAT%', '5.Tmt.DXR.M%VMAT%']
    list_slug = 'myqa_vmat'
    frequency = 'monthly'
    execution_type = 'VMAT'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT vdr.Actual, vdr.DisplayName
            FROM MQA_MDL_VmatDmlc_Results vdr
            JOIN MQA_MDL_VmatDmlc_QueueItemExecutions vdqie
                ON vdr.VmatDmlcQueueItemExecution_Id = vdqie.Id
            JOIN MQA_TestImplementationExecutions tie ON vdqie.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row.get('DisplayName', ''))
            results[slug] = row['Actual']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


class MyqaWinstonLutzImport(MyqaImportBase):
    task_name_patterns = ['5.Tmt.Linac.M%Winston%', '5.Tmt.DXR.M%Winston%']
    list_slug = 'myqa_winston_lutz'
    frequency = 'monthly'
    execution_type = 'WinstonLutz'

    def extract_results(self, execution_id: str) -> Dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute("""
            SELECT wlr.Actual, wlr.DisplayName
            FROM MQA_IsoCheck_WinstonLutz_TestExecutions wlr
            JOIN MQA_TestImplementationExecutions tie ON wlr.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """, (execution_id,))
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row.get('DisplayName', ''))
            results[slug] = row['Actual']
        results[f'{self.list_slug}_taskid'] = execution_id
        return results


TASK_TYPE_REGISTRY = {
    'myqa_numeric': MyqaNumericImport,
    'myqa_passfail': MyqaPassFailImport,
    'myqa_profile': MyqaProfileImport,
    'myqa_energy': MyqaEnergyImport,
    'myqa_wedge': MyqaWedgeImport,
    'myqa_output': MyqaOutputImport,
    'myqa_mlc': MyqaMlcImport,
    'myqa_cbct': MyqaCbctImport,
    'myqa_planar': MyqaPlanarImport,
    'myqa_vmat': MyqaVmatImport,
    'myqa_winston_lutz': MyqaWinstonLutzImport,
}


def get_importer(task_type: str) -> Optional[MyqaImportBase]:
    cls = TASK_TYPE_REGISTRY.get(task_type)
    if cls is None:
        return None
    return cls()


def import_myqa_results(META: dict) -> str:
    task_type = META.get('task_type', 'myqa_numeric')
    days = META.get('days', 30)
    unit_number = META.get('unit_number')

    importer = get_importer(task_type)
    if importer is None:
        return json.dumps({'error': f'Unknown task type: {task_type}'})

    try:
        unit_numbers = [unit_number] if unit_number else None
        sessions = importer.query_new_sessions(days=days, unit_numbers=unit_numbers)

        results = {'imported': 0, 'skipped_dup': 0, 'skipped_err': 0, 'total': len(sessions), 'details': []}

        for session in sessions:
            result = importer.import_session(session)
            results['details'].append(result)
            if result['status'] == 'imported':
                results['imported'] += 1
            elif result['status'] == 'skipped_dup':
                results['skipped_dup'] += 1
            else:
                results['skipped_err'] += 1

        return json.dumps(results)
    finally:
        importer.close()
