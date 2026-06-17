import json
import re
from typing import Any

import pymssql
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from qatrack.qa.models import (
    Test,
    TestInstance,
    TestInstanceStatus,
    TestList,
    TestListInstance,
    Tolerance,
    UnitTestCollection,
    UnitTestInfo,
)

MYQA_DB_SETTINGS = {
    "server": settings.MYQA_DB_SERVER,
    "database": settings.MYQA_DB_NAME,
    "username": settings.MYQA_DB_USERNAME,
    "password": settings.MYQA_DB_PASSWORD,
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

# Per-list unit scoping (design.md M8 fix). Drives UTC + UTI creation in
# setup_myqa_tests.py, replacing the blanket `for unit_num in LINAC_MAP` loop.
# DXR (unit 50) only appears on the DXR daily list — MLC/CBCT/Planar/VMAT/WL/
# PassFail are linac-only QA types (an orthovoltage unit doesn't perform them).
# The dual task_name_patterns (Linac + DXR) on those importers exist for
# forward-compat but DXR executions are not expected in practice.
UNITS_PER_LIST = {
    "myqa_daily_constancy": [1, 2, 3, 4, 5, 7, 8],
    "myqa_daily_physics": [1, 2, 3, 4, 5, 7, 8],
    "myqa_dxr_daily": [50],
    "myqa_mlc": [1, 2, 3, 4, 5, 7, 8],
    "myqa_cbct": [1, 2, 3, 4, 5, 7, 8],
    "myqa_planar": [1, 2, 3, 4, 5, 7, 8],
    "myqa_vmat": [1, 2, 3, 4, 5, 7, 8],
    "myqa_winston_lutz": [1, 2, 3, 4, 5, 7, 8],
    "myqa_passfail": [1, 2, 3, 4, 5, 7, 8],
}


def _cols(prefix: str) -> dict[str, str]:
    """Build the standard Pattern B 4-tuple column mapping for a metric prefix.

    Verifierd myQA schema: ``{Prefix}_Result_Value_Value`` is the value,
    ``{Prefix}_AcceptanceCriterion_Tolerances_Warn_Value`` /
    ``{Prefix}_AcceptanceCriterion_Tolerances_Fail_Value`` are tolerances
    (setup-only). Verdict column (``{Prefix}_Result_Verdict``) omitted per D4
    (deferred — engine hardcodes pass_fail='no_tol'; verdicts not stored).
    """
    return {
        "value_col": f"{prefix}_Result_Value_Value",
        "warn_col": f"{prefix}_AcceptanceCriterion_Tolerances_Warn_Value",
        "fail_col": f"{prefix}_AcceptanceCriterion_Tolerances_Fail_Value",
    }


def slugify_name(list_slug: str, name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9.]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip("_")
    return f"{list_slug}_{slug}"


def clean_roi_name(name: str) -> str:
    """Strip leading/trailing brackets from a VMAT ROI name.

    VMAT ROI rows have ``Name`` like ``[2.0 cm/s]`` — the brackets are myQA
    display decoration. After cleaning, the name is fed to :func:`slugify_name`
    which preserves periods (e.g. ``2.0`` stays ``2.0``). Per O3 / Blocker 1
    decision (A): periods are kept in slugs (matches the actual slugify_name
    behaviour and this change's specs); if QATrack+ URL routing rejects periods
    in a future production test, pre-strip them here.
    """
    return (name or "").strip("[]")


def myqa_to_qatrack_tolerance(
    warn_on: float | None,
    fail_on: float | None,
    is_relative: bool = False,
    limit_tendency: int = 0,
) -> Tolerance | None:
    if warn_on is None and fail_on is None:
        return None

    if is_relative:
        tol_type = "percent"
    else:
        tol_type = "absolute"

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
    task_name_patterns: list[str] = []
    list_slug: str = ""
    test_slug_prefix: str = ""
    frequency: str = ""
    execution_type: str = ""

    def __init__(self):
        self.conn = self._get_connection()
        self.internal_user = User.objects.get(username="QATrack+ Internal")
        self.default_status = TestInstanceStatus.objects.get(is_default=True)
        if not self.test_slug_prefix:
            self.test_slug_prefix = f"{self.list_slug}_"

    def _get_connection(self):
        return pymssql.connect(
            server=MYQA_DB_SETTINGS["server"],
            database=MYQA_DB_SETTINGS["database"],
            user=MYQA_DB_SETTINGS["username"],
            password=MYQA_DB_SETTINGS["password"],
        )

    def close(self):
        if self.conn:
            self.conn.close()

    def query_new_sessions(self, days: int = 30, unit_numbers: list[int] | None = None):
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
                cursor.execute(
                    """
                    SELECT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate,
                           te.TaskName, te.RadiationDeviceName
                    FROM MQA_TestExecutions te
                    WHERE te.RadiationDeviceName = %s
                      AND te.TaskName LIKE %s
                      AND te.ReferenceDate IS NOT NULL
                      AND te.ReferenceDate >= %s
                      AND te.ReferenceDate <= %s
                    ORDER BY te.ReferenceDate, te.FinishingDate
                """,
                    (linac_name, pattern, cutoff_naive, now_naive),
                )

                for row in cursor.fetchall():
                    sessions.append(
                        {
                            "task_execution_id": str(row["TaskExecutionId"]),
                            "reference_date": row["ReferenceDate"],
                            "finishing_date": row["FinishingDate"],
                            "task_name": row["TaskName"],
                            "unit_number": unit_num,
                            "linac_name": linac_name,
                        }
                    )

        return sessions

    def duplicate_check(self, execution_id: str, unit_number: int) -> bool:
        taskid_slug = f"{self.test_slug_prefix}taskid"
        return TestInstance.objects.filter(
            unit_test_info__test__slug=taskid_slug,
            unit_test_info__unit__number=unit_number,
            string_value=execution_id,
        ).exists()

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        """Return test specs for the setup command to create.

        Each spec is a dict with keys: name, slug, type ('numerical' | 'string'),
        warn, fail, is_relative, limit_tendency. The default returns an empty
        list (importer is skipped during setup); override per subclass to enable
        setup. Discovery may run SQL via ``self.conn`` (Numeric, VMAT) or return
        a static list driven by the importer's METRICS dict (MLC/CBCT/Planar) or
        hardcoded values (WL, PassFail).
        """
        return []

    def import_session(self, session: dict) -> dict:
        unit_number = session["unit_number"]
        execution_id = session["task_execution_id"]
        ref_date = session["reference_date"]
        fin_date = session["finishing_date"] or ref_date

        if self.duplicate_check(execution_id, unit_number):
            return {"status": "skipped_dup", "reason": f"duplicate taskid {execution_id[:8]}..."}

        results = self.extract_results(execution_id)
        if results.get("error"):
            return {"status": "error", "reason": results["error"]}

        test_list = TestList.objects.get(slug=self.list_slug)
        ct = ContentType.objects.get_for_model(test_list)
        utc = UnitTestCollection.objects.filter(
            unit__number=unit_number,
            content_type=ct,
            object_id=test_list.pk,
        ).first()
        if utc is None:
            return {"status": "error", "reason": f"No UTC for unit {unit_number} / list {self.list_slug}"}

        tests_by_slug = {t.slug: t for t in Test.objects.filter(slug__startswith=self.test_slug_prefix)}
        all_utis = {}
        for uti in UnitTestInfo.objects.filter(test__slug__startswith=self.test_slug_prefix).select_related("unit"):
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
                    if slug == "error":
                        continue
                    test = tests_by_slug.get(slug)
                    if test is None:
                        continue
                    uti = all_utis.get((unit_number, slug))
                    if uti is None:
                        continue

                    tis.append(
                        TestInstance(
                            test_list_instance=tli,
                            unit_test_info=uti,
                            value=float(val) if isinstance(val, (int, float)) else None,
                            string_value=str(val) if isinstance(val, str) else None,
                            work_started=ref_date,
                            work_completed=fin_date or timezone.now(),
                            created_by=self.internal_user,
                            modified_by=self.internal_user,
                            status=self.default_status,
                            pass_fail="no_tol",
                            order=0,
                        )
                    )

                if tis:
                    TestInstance.objects.bulk_create(tis)

            return {"status": "imported", "count": len(tis)}

        except Exception as e:
            return {"status": "error", "reason": str(e)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MyqaNumericImportBase(MyqaImportBase):
    """Shared base for the three Numeric daily-QA importers (D1 three-way split).

    Each subclass sets ``list_slug``, ``task_name_patterns`` (full task-name
    strings, applied via LIKE), and ``frequency``. The shared
    :meth:`extract_results` reads ``Name``/``Actual`` directly from
    ``MQA_Numeric_TestConditionExecutions`` against the verified schema:
    ``MQA_TestConditions`` does not exist and tolerance columns are named
    ``WarnOn``/``FailOn`` (not ``WarningTolerance``/``ErrorTolerance``).
    Tolerance columns are setup-only (S3) and not selected on the import path.
    """

    frequency = "daily"
    execution_type = "Numeric"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern A (dynamic row-per-condition) per design.md.
        # JOIN chain: tcne.NumericTestExecution_Id -> tie.Id -> te.Id
        # Filter on te.TaskExecutionId (NOT te.Id — execution_id is the FK to
        # MQA_TaskExecutions; filtering on te.Id returns zero rows).
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT tcne.Name, tcne.Actual
            FROM MQA_Numeric_TestConditionExecutions tcne
            JOIN MQA_TestImplementationExecutions tie
                ON tcne.NumericTestExecution_Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """,
            (execution_id,),
        )
        for row in cursor.fetchall():
            slug = slugify_name(self.list_slug, row["Name"])
            results[slug] = row["Actual"]
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Per specs/numeric/spec.md R4 (replaces the triple-broken
        # setup_myqa_tests.py:77-87 query). Tolerance via get_or_create_tolerance
        # using WarnOn/FailOn/BoundingType/IsRelative/LimitTendency.
        # BoundingType is read but unused (forward-compat per O6).
        specs: list[dict[str, Any]] = []
        cursor = self.conn.cursor(as_dict=True)
        for pattern in self.task_name_patterns:
            cursor.execute(
                """
                SELECT DISTINCT tcne.Name, tcne.WarnOn, tcne.FailOn,
                                tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency
                FROM MQA_Numeric_TestConditionExecutions tcne
                JOIN MQA_TestImplementationExecutions tie
                    ON tcne.NumericTestExecution_Id = tie.Id
                JOIN MQA_TestExecutions te ON tie.Id = te.Id
                WHERE te.TaskName LIKE %s
            """,
                (pattern,),
            )
            for row in cursor.fetchall():
                name = row["Name"] or ""
                specs.append(
                    {
                        "name": name,
                        "slug": slugify_name(self.list_slug, name),
                        "type": "numerical",
                        "warn": row["WarnOn"],
                        "fail": row["FailOn"],
                        "is_relative": bool(row["IsRelative"]),
                        "limit_tendency": int(row["LimitTendency"] or 0),
                    }
                )
        return specs


class MyqaNumericConstancyImport(MyqaNumericImportBase):
    # D1: 5.Tmt.Linac.D - myQA Daily Constancy Check -> myqa_daily_constancy.
    # Full task-name string (not a `.D%` prefix) — `.D%` would also match .D2.
    list_slug = "myqa_daily_constancy"
    task_name_patterns = ["5.Tmt.Linac.D - myQA Daily Constancy Check"]


class MyqaNumericPhysicsImport(MyqaNumericImportBase):
    # D1: 5.Tmt.Linac.D2 - Daily QA (Physics) -> myqa_daily_physics.
    list_slug = "myqa_daily_physics"
    task_name_patterns = ["5.Tmt.Linac.D2 - Daily QA (Physics)"]


class MyqaNumericDxrImport(MyqaNumericImportBase):
    # D1: 5.Tmt.DXR.D - myQA Daily Constancy Check -> myqa_dxr_daily (unit 50).
    list_slug = "myqa_dxr_daily"
    task_name_patterns = ["5.Tmt.DXR.D - myQA Daily Constancy Check"]


class MyqaPassFailImport(MyqaImportBase):
    # NOTE: task_name_patterns inherited from the previous (broken) importer.
    # The 'P%' prefix should be verified against actual myQA PassFail TaskName
    # values during the operational backfill (Task 7.2) — if it's wrong, the
    # import will find zero sessions. Out of scope for the code rewrite.
    task_name_patterns = ["5.Tmt.Linac.P%", "5.Tmt.DXR.P%"]
    list_slug = "myqa_passfail"
    frequency = "daily"
    execution_type = "PassFail"

    # Single text field per D3 / specs/passfail/spec.md. Engine stores as
    # string_value via the isinstance(val, str) branch at myqa_import.py:219-220.
    TEST_NAME = "Acceptance Criteria"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern D (degenerate). Removes the broken PassStatus + MQA_TestConditions
        # reads — neither exists in the verified schema (Key Finding #3).
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT pfte.AcceptanceCriteria
            FROM MQA_PassFail_TestExecutions pfte
            JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            results[slugify_name(self.list_slug, self.TEST_NAME)] = row.get("AcceptanceCriteria")
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Hardcoded 1-test list, type='string', no tolerance, no discovery.
        # Test.type MUST be 'string' so the engine doesn't attempt a float cast
        # on the nvarchar AcceptanceCriteria value.
        return [
            {
                "name": self.TEST_NAME,
                "slug": slugify_name(self.list_slug, self.TEST_NAME),
                "type": "string",
                "warn": None,
                "fail": None,
                "is_relative": False,
                "limit_tendency": 0,
            }
        ]


class MyqaProfileImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Dosimetry%", "5.Tmt.DXR.M%Dosimetry%"]
    list_slug = "matrix-dosimetry-import"
    test_slug_prefix = "mtx_"
    frequency = "monthly"
    execution_type = "Profile"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
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
        """,
            (execution_id,),
        )
        for row in cursor.fetchall():
            energy = str(round(row.get("EnergyValue", 0)))
            desc = (row.get("Description") or "photons").lower()
            fff = row.get("IsFlatteningFilterFree")
            if desc == "electrons":
                energy_tag = f"{energy}e"
            else:
                energy_tag = f"{energy}{'fff' if fff else 'x'}"
            direction = "il" if row.get("ProfileDirection") == 1 else "cl"
            display_name = row.get("DisplayName", "")
            name_map = {
                "Flatness": "flat",
                "Symmetry": "sym",
                "Center": "centre",
                "Field Width": "width",
                "Penumbra Left": "lpen",
                "Penumbra Right": "rpen",
                "Inflection Point Left": "inflection_left",
                "Inflection Point Right": "inflection_right",
                "Flatness 80%": "flat_80",
                "Flatness 90%": "flat_90",
                "Deviation": "deviation",
            }
            mtype = name_map.get(display_name, display_name)
            slug = f"mtx_{mtype}_{direction}_{energy_tag}"
            results[slug] = round(row["Actual"], 4) if row["Actual"] is not None else None
        results["mtx_taskid"] = execution_id
        return results


class MyqaEnergyImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Energy%", "5.Tmt.DXR.M%Energy%"]
    list_slug = "matrix-dosimetry-import"
    test_slug_prefix = "mtx_"
    frequency = "monthly"
    execution_type = "Energy"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
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
        """,
            (execution_id,),
        )
        for row in cursor.fetchall():
            energy = str(round(row.get("BeamQuality_EnergyValue", 0)))
            dim = row.get("BeamQuality_EnergyDimension", "6")
            mode = "MeV" if dim == "6" else "MV"
            fff = "fff" if row.get("BeamQuality_IsFlatteningFilterFree") else ""
            chamber = row.get("ChamberNumber", 1)
            slug = f"mtx_energy_{energy}{'' if not fff else fff}_{mode.lower()}_ch{chamber}"
            results[slug] = round(row["Actual"], 4) if row["Actual"] is not None else None
        results["mtx_taskid"] = execution_id
        return results


class MyqaWedgeImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Wedge%", "5.Tmt.DXR.M%Wedge%"]
    list_slug = "matrix-dosimetry-import"
    test_slug_prefix = "mtx_"
    frequency = "monthly"
    execution_type = "Wedge"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT wqie.ActualValue, wqie.ExpectedValue, wte.BeamQuality_EnergyValue,
                   wqie.Tolerance_Warn, wqie.Tolerance_Fail
            FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
            JOIN MQA_Dosimetry_Wedge_TestExecutions wte
                ON wqie.WedgeConstancyExecution_Id = wte.Id
            JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """,
            (execution_id,),
        )
        for row in cursor.fetchall():
            energy = str(int(row.get("BeamQuality_EnergyValue", 0)))
            slug = f"mtx_wedge_cont_{energy}x"
            results[slug] = round(row["ActualValue"], 4) if row["ActualValue"] is not None else None
        results["mtx_taskid"] = execution_id
        return results


class MyqaOutputImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Output%", "5.Tmt.DXR.M%Output%"]
    list_slug = "myqa_monthly_output"
    frequency = "monthly"
    execution_type = "Output"

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        results = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT oqie.ActualValue, oqie.ExpectedValue, oqie.Tolerance_Warn, oqie.Tolerance_Fail,
                   ote.BeamQuality_EnergyValue
            FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
            JOIN MQA_Dosimetry_Output_TestExecutions ote
                ON oqie.OutputConstancyExecution_Id = ote.Id
            JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
        """,
            (execution_id,),
        )
        for row in cursor.fetchall():
            energy = str(int(row.get("BeamQuality_EnergyValue", 0)))
            slug = f"mtx_output_{energy}x"
            results[slug] = round(row["ActualValue"], 4) if row["ActualValue"] is not None else None
        results["mtx_taskid"] = execution_id
        return results


class MyqaMlcImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%MLC%", "5.Tmt.DXR.M%MLC%"]
    list_slug = "myqa_mlc"
    frequency = "monthly"
    execution_type = "MLC"

    # Pattern B (denormalized wide-row) per design.md / specs/mlc/spec.md.
    # METRICS keys are slug suffixes (spec R1 table); column names follow the
    # verified `{Prefix}_Result_Value_Value` / `{Prefix}_AcceptanceCriterion_
    # Tolerances_{Warn,Fail}_Value` pattern. LineDistance* and LineSlope*
    # tolerance-only columns are excluded (O1 — no paired result column).
    METRICS = {
        "failing_peaks": _cols("FailingPeaks"),
        "max_deviation": _cols("MaximumDeviation"),
        "interstrip_ratio": _cols("InterstripRatio"),
        "standard_deviation": _cols("StandardDeviation"),
        "isocenter_to_strip_distance": _cols("IsocenterToStripDistance"),
    }

    # Non-conforming columns (spec R1):
    #   TotalPeaks — value-only (no tolerance, no verdict)
    #   LeavesThatFailed — nvarchar → engine stores as string_value
    #                       (isinstance(val, str) branch at myqa_import.py:219-220)
    #   TestResult — verdict-only → NOT fetched (D4 deferred; "MAY be logged"
    #                per spec scenario — omitted here for simplicity)
    VALUE_ONLY_COLS = {"total_peaks": "TotalPeaks"}
    STRING_COLS = {"leaves_that_failed": "LeavesThatFailed"}

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern B with extra MLC hop: r.MlcQATestExecutionBase_Id -> mte.Id
        # -> tie.Id -> te.Id, filter te.TaskExecutionId. Replaces the broken
        # MlcQAQueueItemExecution_Id path (not in verified schema).
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)

        value_cols = [m["value_col"] for m in self.METRICS.values()]
        all_cols = value_cols + list(self.VALUE_ONLY_COLS.values()) + list(self.STRING_COLS.values())
        select_clause = ", ".join(f"r.{c}" for c in all_cols)

        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_MlcQA_Results r
            JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
            JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            for slug_suffix, cols in self.METRICS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(cols["value_col"])
            for slug_suffix, col in self.VALUE_ONLY_COLS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(col)
            for slug_suffix, col in self.STRING_COLS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(col)
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Pattern B setup (spec R3): iterate the same METRICS dict the importer
        # uses, plus VALUE_ONLY_COLS and STRING_COLS. Engine silently drops
        # slugs lacking a Test (myqa_import.py:209-211), so ALL 7 emitted
        # slugs need a Test created here. Tolerances via single MAX() query
        # (Pattern B importers don't have per-row Name columns to discover).
        tolerances = self._fetch_pattern_b_tolerances()

        specs: list[dict[str, Any]] = []
        # 5 prefix tests with tolerance
        for slug_suffix, cols in self.METRICS.items():
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": tolerances.get(cols["warn_col"]),
                    "fail": tolerances.get(cols["fail_col"]),
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        # value-only entries
        for slug_suffix in self.VALUE_ONLY_COLS:
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": None,
                    "fail": None,
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        # string entries — Test.type MUST be 'string' so the engine's
        # isinstance(val, str) branch routes to string_value (not float cast).
        for slug_suffix in self.STRING_COLS:
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "string",
                    "warn": None,
                    "fail": None,
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        return specs

    def _fetch_pattern_b_tolerances(self) -> dict[str, float | None]:
        """Fetch representative warn/fail tolerance values for METRICS in a
        single query. MAX() ignores NULLs (returns NULL only if all values
        are NULL). Tolerance presumed consistent across executions in myQA.
        """
        all_cols: list[str] = []
        for cols in self.METRICS.values():
            if cols.get("warn_col"):
                all_cols.append(cols["warn_col"])
            if cols.get("fail_col"):
                all_cols.append(cols["fail_col"])
        if not all_cols:
            return {}
        select_clause = ", ".join(f"MAX(r.{c}) AS {c}" for c in all_cols)
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_MlcQA_Results r
            """,
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


class MyqaCbctImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%CBCT%", "5.Tmt.DXR.M%CBCT%"]
    list_slug = "myqa_cbct"
    frequency = "quarterly"
    execution_type = "CBCT"

    # Pattern B (denormalized wide-row) per design.md / specs/cbct/spec.md.
    # 9 prefixes with the standard 4-tuple (verdict omitted — D4 deferred).
    METRICS = {
        "scaling_discrepancy": _cols("ScalingDiscrepancy"),
        "geometric_distortion": _cols("GeometricDistortion"),
        "spatial_resolution": _cols("SpatialResolution"),
        "overall_uniformity": _cols("OverallUniformity"),
        "minimum_uniformity": _cols("MinimumUniformity"),
        "contrast": _cols("Contrast"),
        "cnr": _cols("CNR"),
        "max_hu_deviation": _cols("MaxHuDeviation"),
        "measured_slice_width": _cols("MeasuredSliceWidth"),
    }

    # Non-conforming columns (spec R2):
    #   SliceWidthDifference_Value — value-only → slug suffix slice_width_difference
    #   SliceWidthDifference_Dimension, *Roi, EnergyType, EnergyValue, TestResult
    #     → metadata → not emitted
    VALUE_ONLY_COLS = {"slice_width_difference": "SliceWidthDifference_Value"}

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern B same-UUID link: r.Id = cte.Id (Cbct_Results.Id shares UUID
        # with Cbct_TestExecutions.Id), filter te.TaskExecutionId. Replaces
        # the broken CbctQueueItemExecution_Id path (not in verified schema).
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)

        value_cols = [m["value_col"] for m in self.METRICS.values()]
        all_cols = value_cols + list(self.VALUE_ONLY_COLS.values())
        select_clause = ", ".join(f"r.{c}" for c in all_cols)

        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_Cbct_Results r
            JOIN MQA_MDL_Cbct_TestExecutions cte ON r.Id = cte.Id
            JOIN MQA_TestImplementationExecutions tie ON cte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            for slug_suffix, cols in self.METRICS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(cols["value_col"])
            for slug_suffix, col in self.VALUE_ONLY_COLS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(col)
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Pattern B setup (spec R4): 9 prefix tests with tolerance + 1 value-
        # only test. Engine silently drops slugs lacking a Test, so ALL 10
        # emitted slugs need a Test created here.
        tolerances = self._fetch_pattern_b_tolerances()

        specs: list[dict[str, Any]] = []
        for slug_suffix, cols in self.METRICS.items():
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": tolerances.get(cols["warn_col"]),
                    "fail": tolerances.get(cols["fail_col"]),
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        for slug_suffix in self.VALUE_ONLY_COLS:
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": None,
                    "fail": None,
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        return specs

    def _fetch_pattern_b_tolerances(self) -> dict[str, float | None]:
        all_cols: list[str] = []
        for cols in self.METRICS.values():
            if cols.get("warn_col"):
                all_cols.append(cols["warn_col"])
            if cols.get("fail_col"):
                all_cols.append(cols["fail_col"])
        if not all_cols:
            return {}
        select_clause = ", ".join(f"MAX(r.{c}) AS {c}" for c in all_cols)
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_Cbct_Results r
            """,
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


class MyqaPlanarImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Planar%", "5.Tmt.DXR.M%Planar%"]
    list_slug = "myqa_planar"
    frequency = "monthly"
    execution_type = "Planar"

    # Pattern B (denormalized wide-row) per design.md / specs/planar/spec.md.
    # 7 prefixes with the standard 4-tuple. Non-conforming columns
    # (MinUniformityRoi, EnergyType, EnergyValue, TestResult) are metadata →
    # not emitted (no value-only entries for Planar).
    METRICS = {
        "scaling_discrepancy": _cols("ScalingDiscrepancy"),
        "spatial_resolution": _cols("SpatialResolution"),
        "minimum_uniformity": _cols("MinimumUniformity"),
        "contrast": _cols("Contrast"),
        "cnr": _cols("CNR"),
        "x_offset": _cols("XOffset"),
        "y_offset": _cols("YOffset"),
    }
    VALUE_ONLY_COLS: dict[str, str] = {}

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern B same-UUID link: r.Id = pte.Id, filter te.TaskExecutionId.
        # Replaces the broken PlanarQueueItemExecution_Id path.
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)

        value_cols = [m["value_col"] for m in self.METRICS.values()]
        all_cols = value_cols + list(self.VALUE_ONLY_COLS.values())
        select_clause = ", ".join(f"r.{c}" for c in all_cols) if all_cols else "NULL AS _no_cols"

        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_Planar_Results r
            JOIN MQA_MDL_Planar_TestExecutions pte ON r.Id = pte.Id
            JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            for slug_suffix, cols in self.METRICS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(cols["value_col"])
            for slug_suffix, col in self.VALUE_ONLY_COLS.items():
                results[slugify_name(self.list_slug, slug_suffix)] = row.get(col)
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Pattern B setup (spec R4): iterate METRICS, create one Test + one
        # Tolerance per prefix. No value-only entries for Planar.
        tolerances = self._fetch_pattern_b_tolerances()

        specs: list[dict[str, Any]] = []
        for slug_suffix, cols in self.METRICS.items():
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": tolerances.get(cols["warn_col"]),
                    "fail": tolerances.get(cols["fail_col"]),
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        for slug_suffix in self.VALUE_ONLY_COLS:
            specs.append(
                {
                    "name": slug_suffix.replace("_", " ").title(),
                    "slug": slugify_name(self.list_slug, slug_suffix),
                    "type": "numerical",
                    "warn": None,
                    "fail": None,
                    "is_relative": False,
                    "limit_tendency": 0,
                }
            )
        return specs

    def _fetch_pattern_b_tolerances(self) -> dict[str, float | None]:
        all_cols: list[str] = []
        for cols in self.METRICS.values():
            if cols.get("warn_col"):
                all_cols.append(cols["warn_col"])
            if cols.get("fail_col"):
                all_cols.append(cols["fail_col"])
        if not all_cols:
            return {}
        select_clause = ", ".join(f"MAX(r.{c}) AS {c}" for c in all_cols)
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            f"""
            SELECT {select_clause}
            FROM MQA_MDL_Planar_Results r
            """,
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


class MyqaVmatImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%VMAT%", "5.Tmt.DXR.M%VMAT%"]
    list_slug = "myqa_vmat"
    frequency = "monthly"
    execution_type = "VMAT"

    # Pattern C (hybrid: parent wide-row + child-table fan-out) per design.md /
    # specs/vmat/spec.md. The only type with a 1-to-many child relationship.
    PARENT_TEST_NAME = "Normalization Value"
    # Tolerance column names on the parent table (shared across all ROI rows
    # of the same metric type — read during setup only).
    PARENT_TOL_COLS = {
        "norm_warn": "NormalizationValueAcceptanceCriterion_Tolerances_Warn_Value",
        "norm_fail": "NormalizationValueAcceptanceCriterion_Tolerances_Fail_Value",
        "mean_warn": "RoiMeanAcceptanceCriterion_Tolerances_Warn_Value",
        "mean_fail": "RoiMeanAcceptanceCriterion_Tolerances_Fail_Value",
        "std_warn": "RoiStandardDeviationAcceptanceCriterion_Tolerances_Warn_Value",
        "std_fail": "RoiStandardDeviationAcceptanceCriterion_Tolerances_Fail_Value",
    }

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Parent (one row): NormalizationValue. Child (N rows): per-ROI Mean +
        # StdDev. Both filter te.TaskExecutionId. Replaces the broken
        # VmatDmlcQueueItemExecution_Id path.
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)

        # Parent query
        cursor.execute(
            """
            SELECT r.NormalizationValueResult_Value_Value
            FROM MQA_MDL_VmatDmlc_Results r
            JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
            JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        parent_row = cursor.fetchone()
        if parent_row is not None:
            results[slugify_name(self.list_slug, self.PARENT_TEST_NAME)] = parent_row.get(
                "NormalizationValueResult_Value_Value"
            )

        # Child query — iterate ROI rows, emit two entries per row (Mean + StdDev)
        cursor.execute(
            """
            SELECT rr.Name, rr.Mean_Value_Value, rr.StandardDeviation_Value_Value, rr.Rank
            FROM MQA_MDL_VmatDmlc_RoiResults rr
            JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
            JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
            JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            ORDER BY rr.Rank
            """,
            (execution_id,),
        )
        for child_row in cursor.fetchall():
            cleaned = clean_roi_name(child_row["Name"])
            results[slugify_name(self.list_slug, f"{cleaned} mean")] = child_row.get("Mean_Value_Value")
            results[slugify_name(self.list_slug, f"{cleaned} std dev")] = child_row.get("StandardDeviation_Value_Value")

        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Per spec R5: static parent Test + discovery query over the child
        # table for ROI Tests. Each distinct ROI Name → 2 Tests (Mean + StdDev)
        # with shared tolerances from the parent (RoiMean*, RoiStd*).
        cursor = self.conn.cursor(as_dict=True)

        # Single query: fetch all 6 tolerance columns (MAX aggregation handles
        # any NULL values per column independently).
        tol_select = ", ".join(f"MAX(r.{col}) AS {alias}" for alias, col in self.PARENT_TOL_COLS.items())
        cursor.execute(
            f"""
            SELECT {tol_select}
            FROM MQA_MDL_VmatDmlc_Results r
            """,
        )
        tol_row = cursor.fetchone()
        tols = dict(tol_row) if tol_row else {}

        specs: list[dict[str, Any]] = []

        # 1. Static parent Test (Normalization Value)
        specs.append(
            {
                "name": self.PARENT_TEST_NAME,
                "slug": slugify_name(self.list_slug, self.PARENT_TEST_NAME),
                "type": "numerical",
                "warn": tols.get("norm_warn"),
                "fail": tols.get("norm_fail"),
                "is_relative": False,
                "limit_tendency": 0,
            }
        )

        # 2. Discover distinct ROI Names via the child table (JOIN through
        # parent + te, filter by te.TaskName LIKE per pattern). DISTINCT inside
        # the query dedupes within a pattern; we dedupe across patterns by slug
        # below (Linac + DXR patterns could in principle yield the same ROI).
        for pattern in self.task_name_patterns:
            cursor.execute(
                """
                SELECT DISTINCT rr.Name
                FROM MQA_MDL_VmatDmlc_RoiResults rr
                JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
                JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
                JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
                JOIN MQA_TestExecutions te ON tie.Id = te.Id
                WHERE te.TaskName LIKE %s
                ORDER BY rr.Name
                """,
                (pattern,),
            )
            for row in cursor.fetchall():
                cleaned = clean_roi_name(row["Name"])
                specs.append(
                    {
                        "name": f"{cleaned} mean",
                        "slug": slugify_name(self.list_slug, f"{cleaned} mean"),
                        "type": "numerical",
                        "warn": tols.get("mean_warn"),
                        "fail": tols.get("mean_fail"),
                        "is_relative": False,
                        "limit_tendency": 0,
                    }
                )
                specs.append(
                    {
                        "name": f"{cleaned} std dev",
                        "slug": slugify_name(self.list_slug, f"{cleaned} std dev"),
                        "type": "numerical",
                        "warn": tols.get("std_warn"),
                        "fail": tols.get("std_fail"),
                        "is_relative": False,
                        "limit_tendency": 0,
                    }
                )

        # Dedup by slug (defensive — same ROI name under both Linac + DXR
        # patterns would otherwise produce duplicate specs).
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for spec in specs:
            if spec["slug"] not in seen:
                seen.add(spec["slug"])
                deduped.append(spec)
        return deduped


class MyqaWinstonLutzImport(MyqaImportBase):
    task_name_patterns = ["5.Tmt.Linac.M%Winston%", "5.Tmt.DXR.M%Winston%"]
    list_slug = "myqa_winston_lutz"
    frequency = "monthly"
    execution_type = "WinstonLutz"

    # Two exhaustive direct-column metrics (Pattern D per design.md). Slug
    # names come from slugify_name — the column names MaximumDeviation2D /
    # Deviation3D are CamelCase; we humanise them so the slug and Test.name
    # are readable. (WL spec.md R1 table abbreviates "Maximum" to "Max" in
    # the slug column, but design.md line 131 prescribes slugify_name on the
    # humanised string — we follow the design so import + setup agree.)
    METRIC_NAMES = ("Maximum Deviation 2D", "Deviation 3D")

    def extract_results(self, execution_id: str) -> dict[str, Any]:
        # Pattern D — direct columns, JOIN wl.Id -> tie.Id -> te.Id,
        # filter te.TaskExecutionId. Tolerance_Warn / Tolerance_Fail are
        # setup-only (S3) and not selected on the import path.
        results: dict[str, Any] = {}
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT wl.MaximumDeviation2D, wl.Deviation3D
            FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
            JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskExecutionId = %s
            """,
            (execution_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            results[slugify_name(self.list_slug, self.METRIC_NAMES[0])] = row["MaximumDeviation2D"]
            results[slugify_name(self.list_slug, self.METRIC_NAMES[1])] = row["Deviation3D"]
        results[f"{self.list_slug}_taskid"] = execution_id
        return results

    def discover_setup_tests(self) -> list[dict[str, Any]]:
        # Per design.md / WL spec.md R3: hardcoded 2-test list, 1 shared
        # two-sided absolute tolerance (WL has no LimitTendency column → 0).
        # Fetch representative Tolerance_Warn / Tolerance_Fail from the most
        # recent WL execution that has either value. If none found, both
        # Tests are created with no Tolerance (spec "NULL tolerance" scenario).
        warn: float | None = None
        fail: float | None = None
        cursor = self.conn.cursor(as_dict=True)
        cursor.execute(
            """
            SELECT TOP 1 Tolerance_Warn, Tolerance_Fail
            FROM MQA_IsoCheck_WinstonLutz_TestExecutions
            WHERE Tolerance_Warn IS NOT NULL OR Tolerance_Fail IS NOT NULL
            ORDER BY Id DESC
            """,
        )
        row = cursor.fetchone()
        if row is not None:
            warn = row.get("Tolerance_Warn")
            fail = row.get("Tolerance_Fail")

        shared = {
            "type": "numerical",
            "warn": warn,
            "fail": fail,
            "is_relative": False,
            "limit_tendency": 0,
        }
        return [
            {
                **shared,
                "name": self.METRIC_NAMES[0],
                "slug": slugify_name(self.list_slug, self.METRIC_NAMES[0]),
            },
            {
                **shared,
                "name": self.METRIC_NAMES[1],
                "slug": slugify_name(self.list_slug, self.METRIC_NAMES[1]),
            },
        ]


TASK_TYPE_REGISTRY = {
    "numeric_constancy": MyqaNumericConstancyImport,
    "numeric_physics": MyqaNumericPhysicsImport,
    "numeric_dxr": MyqaNumericDxrImport,
    "myqa_passfail": MyqaPassFailImport,
    "myqa_profile": MyqaProfileImport,
    "myqa_energy": MyqaEnergyImport,
    "myqa_wedge": MyqaWedgeImport,
    "myqa_output": MyqaOutputImport,
    "myqa_mlc": MyqaMlcImport,
    "myqa_cbct": MyqaCbctImport,
    "myqa_planar": MyqaPlanarImport,
    "myqa_vmat": MyqaVmatImport,
    "myqa_winston_lutz": MyqaWinstonLutzImport,
}


def get_importer(task_type: str) -> MyqaImportBase | None:
    cls = TASK_TYPE_REGISTRY.get(task_type)
    if cls is None:
        return None
    return cls()


def import_myqa_results(META: dict) -> str:
    # Default is numeric_constancy (first Numeric importer per D1). The other
    # two Numeric lists (numeric_physics, numeric_dxr) are invoked via their own
    # django-q Schedule entries; there is no aggregate key (engine fan-out is a
    # Non-goal per proposal.md).
    task_type = META.get("task_type", "numeric_constancy")
    days = META.get("days", 30)
    unit_number = META.get("unit_number")

    importer = get_importer(task_type)
    if importer is None:
        return json.dumps({"error": f"Unknown task type: {task_type}"})

    try:
        unit_numbers = [unit_number] if unit_number else None
        sessions = importer.query_new_sessions(days=days, unit_numbers=unit_numbers)

        results = {"imported": 0, "skipped_dup": 0, "skipped_err": 0, "total": len(sessions), "details": []}

        for session in sessions:
            result = importer.import_session(session)
            results["details"].append(result)
            if result["status"] == "imported":
                results["imported"] += 1
            elif result["status"] == "skipped_dup":
                results["skipped_dup"] += 1
            else:
                results["skipped_err"] += 1

        return json.dumps(results)
    finally:
        importer.close()
