"""Unit tests for the myQA importers (`qatrack.myqa_import`).

Covers ``extract_results`` (Pattern A/B/C/D) and ``discover_setup_tests`` for
all 7 in-scope importers per `openspec/changes/fix-myqa-importers/`. Each
importer has happy-path + NULL-value + empty-result-set scenarios (per Task
8.1). The myQA SQL Server connection is mocked — no real DB access happens.

These tests bypass ``MyqaImportBase.__init__`` (which requires Django ORM +
pymssql) via ``object.__new__`` so they exercise only the SQL-shape and
dict-building logic of the importer. End-to-end ``import_session`` (which
needs Django ORM + the QATrack+ DB) is covered separately.
"""

import unittest
from unittest import mock

from qatrack.myqa_import import (
    MyqaCbctImport,
    MyqaMlcImport,
    MyqaNumericConstancyImport,
    MyqaNumericDxrImport,
    MyqaNumericPhysicsImport,
    MyqaPassFailImport,
    MyqaPlanarImport,
    MyqaVmatImport,
    MyqaWinstonLutzImport,
    clean_roi_name,
    slugify_name,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal pymssql cursor stand-in. Records calls and returns canned rows.

    ``as_dict=True`` cursor behaviour: ``fetchone`` / ``fetchall`` return dicts
    keyed by column name (the importer code reads via ``row['Col']`` / ``row.get('Col')``).
    """

    def __init__(self, rows=None, fetchone_rows=None):
        # For fetchall-style queries (Numeric iterates many rows)
        self._rows = list(rows) if rows else []
        # For fetchone-style queries (most others)
        self._fetchone_rows = list(fetchone_rows) if fetchone_rows else []
        self._fetchone_idx = 0
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        # Heuristic: fetchone-style queries pop from _fetchone_rows; otherwise
        # the next fetchall returns _rows. Real pymssql doesn't work this way
        # but our importer code is consistent within a method.
        return self

    def fetchone(self):
        if self._fetchone_idx < len(self._fetchone_rows):
            row = self._fetchone_rows[self._fetchone_idx]
            self._fetchone_idx += 1
            return row
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows = self._rows
        self._rows = []
        return rows


def make_importer(cls, **overrides):
    """Instantiate ``cls`` bypassing ``MyqaImportBase.__init__``.

    Sets the instance attributes that methods actually need (``conn``,
    ``list_slug``, ``test_slug_prefix``) without triggering pymssql.connect or
    Django ORM queries. ``overrides`` lets a test swap in a different conn.
    """
    imp = object.__new__(cls)
    imp.conn = overrides.pop("conn", None)
    imp.list_slug = overrides.pop("list_slug", cls.list_slug)
    imp.test_slug_prefix = overrides.pop("test_slug_prefix", f"{cls.list_slug}_")
    for k, v in overrides.items():
        setattr(imp, k, v)
    return imp


# ---------------------------------------------------------------------------
# slugify / clean helpers
# ---------------------------------------------------------------------------


class TestSlugHelpers(unittest.TestCase):
    def test_slugify_name_preserves_periods(self):
        # Blocker 1 decision (A) — periods preserved. Critical for VMAT ROI
        # slugs like myqa_vmat_2.0_cm_s_mean.
        self.assertEqual(
            slugify_name("myqa_vmat", "2.0 cm/s mean"),
            "myqa_vmat_2.0_cm_s_mean",
        )

    def test_slugify_name_numeric_physics(self):
        # specs/numeric/spec.md happy-path scenario
        self.assertEqual(
            slugify_name("myqa_daily_physics", "1.05 18MV Output"),
            "myqa_daily_physics_1.05_18mv_output",
        )

    def test_clean_roi_name_strips_brackets(self):
        self.assertEqual(clean_roi_name("[2.0 cm/s]"), "2.0 cm/s")
        self.assertEqual(clean_roi_name("no brackets"), "no brackets")
        self.assertEqual(clean_roi_name(""), "")
        # Graceful None handling — implementation does `(name or "")` so None
        # becomes "" (not raised, not passed through as None).
        self.assertEqual(clean_roi_name(None), "")


# ---------------------------------------------------------------------------
# Pattern A — Numeric (3 importers share MyqaNumericImportBase)
# ---------------------------------------------------------------------------


class TestNumericImportExtract(unittest.TestCase):
    """specs/numeric/spec.md scenarios R1-R2."""

    def setUp(self):
        # Single shared row fixture: Name + Actual. No tolerance cols on the
        # import path (S3 — setup-only).
        self.happy_rows = [
            {"Name": "1.05 18MV Output", "Actual": 0.03},
            {"Name": "Output Constancy", "Actual": 1.5},
        ]
        self.null_rows = [{"Name": "1.05 18MV Output", "Actual": None}]
        self.empty_rows = []

    def _make(self, rows, list_slug="myqa_daily_physics"):
        cursor = FakeCursor(rows=rows)
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaNumericPhysicsImport, conn=conn, list_slug=list_slug)

    def test_constancy_uses_correct_pattern(self):
        imp = make_importer(MyqaNumericConstancyImport)
        self.assertEqual(imp.task_name_patterns, ["5.Tmt.Linac.D - myQA Daily Constancy Check"])
        self.assertEqual(imp.list_slug, "myqa_daily_constancy")

    def test_physics_uses_correct_pattern(self):
        imp = make_importer(MyqaNumericPhysicsImport)
        self.assertEqual(imp.task_name_patterns, ["5.Tmt.Linac.D2 - Daily QA (Physics)"])
        self.assertEqual(imp.list_slug, "myqa_daily_physics")

    def test_dxr_uses_correct_pattern(self):
        imp = make_importer(MyqaNumericDxrImport)
        self.assertEqual(imp.task_name_patterns, ["5.Tmt.DXR.D - myQA Daily Constancy Check"])
        self.assertEqual(imp.list_slug, "myqa_dxr_daily")

    def test_extract_results_happy_path(self):
        imp = self._make(self.happy_rows)
        results = imp.extract_results("exec-123")
        self.assertEqual(results["myqa_daily_physics_1.05_18mv_output"], 0.03)
        self.assertEqual(results["myqa_daily_physics_output_constancy"], 1.5)
        # Dedup key always present
        self.assertEqual(results["myqa_daily_physics_taskid"], "exec-123")

    def test_extract_results_null_actual(self):
        # spec "NULL Actual value" — value stored as None, no exception
        imp = self._make(self.null_rows)
        results = imp.extract_results("exec-null")
        self.assertIsNone(results["myqa_daily_physics_1.05_18mv_output"])

    def test_extract_results_empty_result_set(self):
        # spec "Empty result set" — only the dedup key in the dict
        imp = self._make(self.empty_rows)
        results = imp.extract_results("exec-empty")
        self.assertEqual(results, {"myqa_daily_physics_taskid": "exec-empty"})

    def test_extract_results_sql_filters_taskexecutionid(self):
        # spec R1: filter te.TaskExecutionId (not te.Id). Verifies the
        # parameterised placeholder is the execution_id we passed in.
        imp = self._make(self.happy_rows)
        imp.extract_results("exec-XYZ")
        sql, params = imp.conn.cursor.return_value.executed[0]
        self.assertIn("te.TaskExecutionId = %s", sql)
        self.assertEqual(params, ("exec-XYZ",))

    def test_extract_results_no_testconditions_join(self):
        # spec R1: query MQA_Numeric_TestConditionExecutions directly — the
        # non-existent MQA_TestConditions table MUST NOT appear.
        imp = self._make(self.happy_rows)
        imp.extract_results("exec-1")
        sql, _ = imp.conn.cursor.return_value.executed[0]
        self.assertNotIn("MQA_TestConditions", sql)

    def test_extract_results_no_tolerance_columns_in_import_path(self):
        # spec R1/S3: tolerances (WarnOn/FailOn/etc.) are setup-only.
        imp = self._make(self.happy_rows)
        imp.extract_results("exec-1")
        sql, _ = imp.conn.cursor.return_value.executed[0]
        self.assertNotIn("WarnOn", sql)
        self.assertNotIn("FailOn", sql)


class TestNumericImportDiscover(unittest.TestCase):
    """specs/numeric/spec.md R4 — setup discovery query."""

    def test_discover_returns_specs_with_correct_columns(self):
        discovery_rows = [
            {
                "Name": "1.01 6MV Output",
                "WarnOn": 0.015,
                "FailOn": 0.02,
                "BoundingType": 0,
                "IsRelative": False,
                "LimitTendency": 0,
            },
        ]
        cursor = FakeCursor(rows=discovery_rows)
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaNumericPhysicsImport, conn=conn)

        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec["name"], "1.01 6MV Output")
        self.assertEqual(spec["slug"], "myqa_daily_physics_1.01_6mv_output")
        self.assertEqual(spec["type"], "numerical")
        self.assertEqual(spec["warn"], 0.015)
        self.assertEqual(spec["fail"], 0.02)
        self.assertFalse(spec["is_relative"])
        self.assertEqual(spec["limit_tendency"], 0)

    def test_discover_sql_uses_taskname_like_per_pattern(self):
        # spec R4: WHERE te.TaskName LIKE %s (one query per task_name_pattern)
        cursor = FakeCursor(rows=[])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaNumericPhysicsImport, conn=conn)

        imp.discover_setup_tests()
        sql, params = cursor.executed[0]
        self.assertIn("te.TaskName LIKE %s", sql)
        self.assertEqual(params, ("5.Tmt.Linac.D2 - Daily QA (Physics)",))


# ---------------------------------------------------------------------------
# Pattern D — Winston Lutz
# ---------------------------------------------------------------------------


class TestWinstonLutzExtract(unittest.TestCase):
    """specs/winston-lutz/spec.md R1-R2."""

    def _make(self, fetchone_row=None):
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaWinstonLutzImport, conn=conn)

    def test_happy_path(self):
        imp = self._make({"MaximumDeviation2D": 0.52, "Deviation3D": 0.61})
        results = imp.extract_results("wl-exec-1")
        # Slugs per design.md line 131 (humanised names, NOT abbreviated)
        self.assertEqual(results["myqa_winston_lutz_maximum_deviation_2d"], 0.52)
        self.assertEqual(results["myqa_winston_lutz_deviation_3d"], 0.61)
        self.assertEqual(results["myqa_winston_lutz_taskid"], "wl-exec-1")

    def test_null_deviation(self):
        # spec "NULL deviation value" — None stored, other metric still emitted
        imp = self._make({"MaximumDeviation2D": 0.4, "Deviation3D": None})
        results = imp.extract_results("wl-exec-2")
        self.assertEqual(results["myqa_winston_lutz_maximum_deviation_2d"], 0.4)
        self.assertIsNone(results["myqa_winston_lutz_deviation_3d"])

    def test_empty_result_set(self):
        imp = self._make(fetchone_row=None)
        results = imp.extract_results("wl-exec-empty")
        self.assertEqual(results, {"myqa_winston_lutz_taskid": "wl-exec-empty"})

    def test_extract_does_not_select_tolerance(self):
        # Tolerance_Warn / Tolerance_Fail are setup-only per design (S3).
        imp = self._make({"MaximumDeviation2D": 0.5, "Deviation3D": 0.6})
        imp.extract_results("wl-1")
        sql, _ = imp.conn.cursor.return_value.executed[0]
        self.assertNotIn("Tolerance_Warn", sql)
        self.assertNotIn("Tolerance_Fail", sql)


class TestWinstonLutzDiscover(unittest.TestCase):
    """specs/winston-lutz/spec.md R3 — shared two-sided tolerance."""

    def _make(self, fetchone_row=None):
        # First fetchone: tolerance fetch. Single row.
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [None])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaWinstonLutzImport, conn=conn)

    def test_shared_tolerance_applied_to_both_metrics(self):
        imp = self._make({"Tolerance_Warn": 1.0, "Tolerance_Fail": 2.0})
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 2)
        # Both specs share the same tolerance values
        for spec in specs:
            self.assertEqual(spec["warn"], 1.0)
            self.assertEqual(spec["fail"], 2.0)
            self.assertEqual(spec["limit_tendency"], 0)
            self.assertFalse(spec["is_relative"])
        # Slugs match what extract_results emits (engine silent-drop trap)
        slugs = {s["slug"] for s in specs}
        self.assertEqual(
            slugs,
            {
                "myqa_winston_lutz_maximum_deviation_2d",
                "myqa_winston_lutz_deviation_3d",
            },
        )

    def test_null_tolerance_yields_no_tolerance_in_spec(self):
        # spec "NULL tolerance" scenario — warn/fail are None, Tests still created
        imp = self._make({"Tolerance_Warn": None, "Tolerance_Fail": None})
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 2)
        for spec in specs:
            self.assertIsNone(spec["warn"])
            self.assertIsNone(spec["fail"])


# ---------------------------------------------------------------------------
# Pattern B — MLC
# ---------------------------------------------------------------------------


class TestMlcExtract(unittest.TestCase):
    """specs/mlc/spec.md R1-R2."""

    def _make(self, fetchone_row=None):
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaMlcImport, conn=conn)

    def test_happy_path_5_prefixes_emitted(self):
        row = {
            "FailingPeaks_Result_Value_Value": 3,
            "MaximumDeviation_Result_Value_Value": 0.42,
            "InterstripRatio_Result_Value_Value": 0.15,
            "StandardDeviation_Result_Value_Value": 0.08,
            "IsocenterToStripDistance_Result_Value_Value": 1.2,
            "TotalPeaks": 60,
            "LeavesThatFailed": "A1, A2, B15",
        }
        imp = self._make(row)
        results = imp.extract_results("mlc-1")
        self.assertEqual(results["myqa_mlc_failing_peaks"], 3)
        self.assertEqual(results["myqa_mlc_max_deviation"], 0.42)
        self.assertEqual(results["myqa_mlc_interstrip_ratio"], 0.15)
        self.assertEqual(results["myqa_mlc_standard_deviation"], 0.08)
        self.assertEqual(results["myqa_mlc_isocenter_to_strip_distance"], 1.2)
        # value-only + string entries
        self.assertEqual(results["myqa_mlc_total_peaks"], 60)
        self.assertEqual(results["myqa_mlc_leaves_that_failed"], "A1, A2, B15")
        # dedup
        self.assertEqual(results["myqa_mlc_taskid"], "mlc-1")

    def test_null_metric_value(self):
        # spec "NULL metric value" — None stored, no exception
        row = {
            "FailingPeaks_Result_Value_Value": 3,
            "MaximumDeviation_Result_Value_Value": None,
            "InterstripRatio_Result_Value_Value": 0.15,
            "StandardDeviation_Result_Value_Value": 0.08,
            "IsocenterToStripDistance_Result_Value_Value": 1.2,
            "TotalPeaks": 60,
            "LeavesThatFailed": None,
        }
        imp = self._make(row)
        results = imp.extract_results("mlc-null")
        self.assertEqual(results["myqa_mlc_failing_peaks"], 3)
        self.assertIsNone(results["myqa_mlc_max_deviation"])
        self.assertIsNone(results["myqa_mlc_leaves_that_failed"])

    def test_empty_result_set(self):
        imp = self._make(fetchone_row=None)
        results = imp.extract_results("mlc-empty")
        self.assertEqual(results, {"myqa_mlc_taskid": "mlc-empty"})

    def test_leaves_that_failed_is_string(self):
        # spec "LeavesThatFailed stored as string" — value passed through as-is
        # so engine's isinstance(val, str) branch routes to string_value.
        row = {
            col: None
            for col in [
                "FailingPeaks_Result_Value_Value",
                "MaximumDeviation_Result_Value_Value",
                "InterstripRatio_Result_Value_Value",
                "StandardDeviation_Result_Value_Value",
                "IsocenterToStripDistance_Result_Value_Value",
                "TotalPeaks",
            ]
        }
        row["LeavesThatFailed"] = "A1, B15"
        imp = self._make(row)
        results = imp.extract_results("mlc-str")
        self.assertEqual(results["myqa_mlc_leaves_that_failed"], "A1, B15")


class TestMlcDiscover(unittest.TestCase):
    """specs/mlc/spec.md R3 — 7 tests (5 prefix + 2 non-conforming)."""

    def _make(self, tolerance_row=None):
        # discover_setup_tests issues one fetchone (MAX aggregation query)
        cursor = FakeCursor(fetchone_rows=[tolerance_row or {}])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaMlcImport, conn=conn)

    def test_seven_specs_created(self):
        # spec R3: 5 prefix + total_peaks (value-only) + leaves_that_failed (string)
        # Engine silent-drop trap: every emitted slug MUST get a Test.
        imp = self._make(
            {
                "FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value": 5,
                "FailingPeaks_AcceptanceCriterion_Tolerances_Fail_Value": 10,
                "MaximumDeviation_AcceptanceCriterion_Tolerances_Warn_Value": 0.5,
                "MaximumDeviation_AcceptanceCriterion_Tolerances_Fail_Value": 1.0,
                "InterstripRatio_AcceptanceCriterion_Tolerances_Warn_Value": None,
                "InterstripRatio_AcceptanceCriterion_Tolerances_Fail_Value": None,
                "StandardDeviation_AcceptanceCriterion_Tolerances_Warn_Value": 0.1,
                "StandardDeviation_AcceptanceCriterion_Tolerances_Fail_Value": 0.2,
                "IsocenterToStripDistance_AcceptanceCriterion_Tolerances_Warn_Value": 1.5,
                "IsocenterToStripDistance_AcceptanceCriterion_Tolerances_Fail_Value": 2.0,
            }
        )
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 7)
        slugs = {s["slug"] for s in specs}
        self.assertEqual(
            slugs,
            {
                "myqa_mlc_failing_peaks",
                "myqa_mlc_max_deviation",
                "myqa_mlc_interstrip_ratio",
                "myqa_mlc_standard_deviation",
                "myqa_mlc_isocenter_to_strip_distance",
                "myqa_mlc_total_peaks",
                "myqa_mlc_leaves_that_failed",
            },
        )

    def test_leaves_that_failed_spec_type_is_string(self):
        # spec R3: Test.type='string' for LeavesThatFailed (engine routing)
        imp = self._make({})
        specs = imp.discover_setup_tests()
        leaves = next(s for s in specs if s["slug"] == "myqa_mlc_leaves_that_failed")
        self.assertEqual(leaves["type"], "string")
        # total_peaks is numerical (not string)
        peaks = next(s for s in specs if s["slug"] == "myqa_mlc_total_peaks")
        self.assertEqual(peaks["type"], "numerical")


# ---------------------------------------------------------------------------
# Pattern B — CBCT
# ---------------------------------------------------------------------------


class TestCbctExtract(unittest.TestCase):
    """specs/cbct/spec.md R1-R3."""

    def _make(self, fetchone_row=None):
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaCbctImport, conn=conn)

    def test_happy_path_9_prefixes_plus_value_only(self):
        row = {
            "ScalingDiscrepancy_Result_Value_Value": 0.02,
            "GeometricDistortion_Result_Value_Value": 0.1,
            "SpatialResolution_Result_Value_Value": 1.0,
            "OverallUniformity_Result_Value_Value": 2.0,
            "MinimumUniformity_Result_Value_Value": 0.5,
            "Contrast_Result_Value_Value": 14.5,
            "CNR_Result_Value_Value": 1.5,
            "MaxHuDeviation_Result_Value_Value": 30.0,
            "MeasuredSliceWidth_Result_Value_Value": 2.5,
            "SliceWidthDifference_Value": 0.3,
        }
        imp = self._make(row)
        results = imp.extract_results("cbct-1")
        self.assertEqual(results["myqa_cbct_scaling_discrepancy"], 0.02)
        self.assertEqual(results["myqa_cbct_cnr"], 1.5)
        self.assertEqual(results["myqa_cbct_measured_slice_width"], 2.5)
        self.assertEqual(results["myqa_cbct_slice_width_difference"], 0.3)
        # all 9 prefixes + 1 value-only + dedup = 11 entries
        self.assertEqual(len(results), 11)

    def test_null_metric_value(self):
        row = {
            col: None
            for col in [
                "ScalingDiscrepancy_Result_Value_Value",
                "GeometricDistortion_Result_Value_Value",
                "SpatialResolution_Result_Value_Value",
                "OverallUniformity_Result_Value_Value",
                "MinimumUniformity_Result_Value_Value",
                "Contrast_Result_Value_Value",
                "CNR_Result_Value_Value",
                "MaxHuDeviation_Result_Value_Value",
                "MeasuredSliceWidth_Result_Value_Value",
                "SliceWidthDifference_Value",
            ]
        }
        row["CNR_Result_Value_Value"] = 1.5  # one non-null
        imp = self._make(row)
        results = imp.extract_results("cbct-null")
        self.assertEqual(results["myqa_cbct_cnr"], 1.5)
        self.assertIsNone(results["myqa_cbct_contrast"])

    def test_empty_result_set(self):
        imp = self._make(fetchone_row=None)
        results = imp.extract_results("cbct-empty")
        self.assertEqual(results, {"myqa_cbct_taskid": "cbct-empty"})


class TestCbctDiscover(unittest.TestCase):
    def test_ten_specs_created(self):
        # spec R4: 9 prefix tests (with tolerance) + 1 value-only test
        cursor = FakeCursor(fetchone_rows=[{}])  # empty tolerance row
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaCbctImport, conn=conn)
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 10)
        slugs = {s["slug"] for s in specs}
        self.assertIn("myqa_cbct_slice_width_difference", slugs)
        self.assertIn("myqa_cbct_max_hu_deviation", slugs)


# ---------------------------------------------------------------------------
# Pattern B — Planar
# ---------------------------------------------------------------------------


class TestPlanarExtract(unittest.TestCase):
    """specs/planar/spec.md R1-R3."""

    def _make(self, fetchone_row=None):
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaPlanarImport, conn=conn)

    def test_happy_path_7_prefixes(self):
        row = {
            "ScalingDiscrepancy_Result_Value_Value": 0.01,
            "SpatialResolution_Result_Value_Value": 1.0,
            "MinimumUniformity_Result_Value_Value": 0.5,
            "Contrast_Result_Value_Value": 12.0,
            "CNR_Result_Value_Value": 2.1,
            "XOffset_Result_Value_Value": 0.5,
            "YOffset_Result_Value_Value": -0.3,
        }
        imp = self._make(row)
        results = imp.extract_results("planar-1")
        self.assertEqual(results["myqa_planar_x_offset"], 0.5)
        self.assertEqual(results["myqa_planar_y_offset"], -0.3)  # negative preserved
        self.assertEqual(results["myqa_planar_cnr"], 2.1)
        # 7 prefixes + dedup = 8 entries (no value-only)
        self.assertEqual(len(results), 8)

    def test_negative_offset_value(self):
        # spec "Negative offset value" — engine stores negative float (no abs/clamp)
        row = {
            col: None
            for col in [
                "ScalingDiscrepancy_Result_Value_Value",
                "SpatialResolution_Result_Value_Value",
                "MinimumUniformity_Result_Value_Value",
                "Contrast_Result_Value_Value",
                "CNR_Result_Value_Value",
                "YOffset_Result_Value_Value",
            ]
        }
        row["XOffset_Result_Value_Value"] = -1.2
        imp = self._make(row)
        results = imp.extract_results("planar-neg")
        self.assertEqual(results["myqa_planar_x_offset"], -1.2)

    def test_empty_result_set(self):
        imp = self._make(fetchone_row=None)
        results = imp.extract_results("planar-empty")
        self.assertEqual(results, {"myqa_planar_taskid": "planar-empty"})


class TestPlanarDiscover(unittest.TestCase):
    def test_seven_specs_created(self):
        cursor = FakeCursor(fetchone_rows=[{}])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaPlanarImport, conn=conn)
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 7)


# ---------------------------------------------------------------------------
# Pattern C — VMAT (parent + child fan-out)
# ---------------------------------------------------------------------------


class TestVmatExtract(unittest.TestCase):
    """specs/vmat/spec.md R1-R4."""

    def _make(self, parent_row=None, child_rows=None):
        # Two fetchone/fetchall sequences: parent (fetchone) then child (fetchall).
        cursor = FakeCursor(
            fetchone_rows=[parent_row] if parent_row else [],
            rows=list(child_rows) if child_rows else [],
        )
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaVmatImport, conn=conn)

    def test_happy_path_parent_plus_3_rois(self):
        # spec "VMAT import (happy path)" scenario
        parent = {"NormalizationValueResult_Value_Value": 100.5}
        children = [
            {"Name": "[2.0 cm/s]", "Mean_Value_Value": 42.1, "StandardDeviation_Value_Value": 0.5, "Rank": 1},
            {"Name": "[5.0 cm/s]", "Mean_Value_Value": 38.2, "StandardDeviation_Value_Value": 0.4, "Rank": 2},
            {"Name": "[10.0 cm/s]", "Mean_Value_Value": 35.0, "StandardDeviation_Value_Value": 0.3, "Rank": 3},
        ]
        imp = self._make(parent, children)
        results = imp.extract_results("vmat-1")

        self.assertEqual(results["myqa_vmat_normalization_value"], 100.5)
        # Periods preserved per Blocker 1 decision (A)
        self.assertEqual(results["myqa_vmat_2.0_cm_s_mean"], 42.1)
        self.assertEqual(results["myqa_vmat_5.0_cm_s_mean"], 38.2)
        self.assertEqual(results["myqa_vmat_10.0_cm_s_mean"], 35.0)
        # Std dev entries too
        self.assertEqual(results["myqa_vmat_2.0_cm_s_std_dev"], 0.5)
        # dedup
        self.assertEqual(results["myqa_vmat_taskid"], "vmat-1")

    def test_null_roi_mean_value(self):
        # spec "NULL ROI Mean value" — Mean None, StdDev still emitted
        parent = {"NormalizationValueResult_Value_Value": 100.0}
        children = [
            {"Name": "[2.0 cm/s]", "Mean_Value_Value": None, "StandardDeviation_Value_Value": 0.5, "Rank": 1},
        ]
        imp = self._make(parent, children)
        results = imp.extract_results("vmat-null")
        self.assertIsNone(results["myqa_vmat_2.0_cm_s_mean"])
        self.assertEqual(results["myqa_vmat_2.0_cm_s_std_dev"], 0.5)

    def test_empty_roi_result_set(self):
        # spec "Empty ROI result set" — only parent emitted
        parent = {"NormalizationValueResult_Value_Value": 100.0}
        imp = self._make(parent, child_rows=[])
        results = imp.extract_results("vmat-no-children")
        self.assertEqual(results["myqa_vmat_normalization_value"], 100.0)
        self.assertNotIn("myqa_vmat_2.0_cm_s_mean", results)

    def test_null_parent_normalization_value(self):
        # spec "NULL parent NormalizationValue" — None stored, ROI still processed
        parent = {"NormalizationValueResult_Value_Value": None}
        children = [
            {"Name": "[2.0 cm/s]", "Mean_Value_Value": 42.1, "StandardDeviation_Value_Value": 0.5, "Rank": 1},
        ]
        imp = self._make(parent, children)
        results = imp.extract_results("vmat-null-parent")
        self.assertIsNone(results["myqa_vmat_normalization_value"])
        self.assertEqual(results["myqa_vmat_2.0_cm_s_mean"], 42.1)


class TestVmatDiscover(unittest.TestCase):
    """specs/vmat/spec.md R5 — static parent + ROI discovery."""

    def _make(self, tolerance_row=None, roi_rows=None):
        # discover issues: tolerance fetchone, then DISTINCT Name per pattern.
        # For one pattern (we test with a single-pattern subclass for simplicity)
        cursor = FakeCursor(
            fetchone_rows=[tolerance_row or {}],
            rows=list(roi_rows) if roi_rows else [],
        )
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaVmatImport, conn=conn)
        return imp, cursor

    def test_static_parent_plus_discovered_rois(self):
        # 3 distinct ROI names → 1 parent + 3*2 children = 7 specs
        tol_row = {
            "norm_warn": 5.0,
            "norm_fail": 10.0,
            "mean_warn": 1.0,
            "mean_fail": 2.0,
            "std_warn": 0.1,
            "std_fail": 0.2,
        }
        roi_rows = [
            {"Name": "[2.0 cm/s]"},
            {"Name": "[5.0 cm/s]"},
        ]
        imp, _ = self._make(tol_row, roi_rows)
        # Patch task_name_patterns to a single entry so we get one DISTINCT pass
        imp.task_name_patterns = ["5.Tmt.Linac.M%VMAT%"]
        specs = imp.discover_setup_tests()

        # 1 parent + 2 rois * 2 (mean + std) = 5 specs (per single pattern)
        self.assertEqual(len(specs), 5)
        slugs = {s["slug"] for s in specs}
        self.assertIn("myqa_vmat_normalization_value", slugs)
        self.assertIn("myqa_vmat_2.0_cm_s_mean", slugs)
        self.assertIn("myqa_vmat_2.0_cm_s_std_dev", slugs)
        self.assertIn("myqa_vmat_5.0_cm_s_mean", slugs)
        self.assertIn("myqa_vmat_5.0_cm_s_std_dev", slugs)

        # Parent uses norm_* tolerance; children share mean_* / std_*
        parent = next(s for s in specs if s["slug"] == "myqa_vmat_normalization_value")
        self.assertEqual(parent["warn"], 5.0)
        self.assertEqual(parent["fail"], 10.0)
        mean_spec = next(s for s in specs if s["slug"] == "myqa_vmat_2.0_cm_s_mean")
        self.assertEqual(mean_spec["warn"], 1.0)
        self.assertEqual(mean_spec["fail"], 2.0)
        std_spec = next(s for s in specs if s["slug"] == "myqa_vmat_2.0_cm_s_std_dev")
        self.assertEqual(std_spec["warn"], 0.1)
        self.assertEqual(std_spec["fail"], 0.2)


# ---------------------------------------------------------------------------
# Pattern D — PassFail
# ---------------------------------------------------------------------------


class TestPassFailExtract(unittest.TestCase):
    """specs/passfail/spec.md R1-R3."""

    def _make(self, fetchone_row=None):
        cursor = FakeCursor(fetchone_rows=[fetchone_row] if fetchone_row else [])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        return make_importer(MyqaPassFailImport, conn=conn)

    def test_happy_path(self):
        # spec "PassFail import (happy path)" — text stored as string_value
        # (engine routes via isinstance(val, str) branch).
        imp = self._make({"AcceptanceCriteria": "Visual check OK, no deviations"})
        results = imp.extract_results("pf-1")
        self.assertEqual(
            results["myqa_passfail_acceptance_criteria"],
            "Visual check OK, no deviations",
        )
        self.assertEqual(results["myqa_passfail_taskid"], "pf-1")

    def test_null_acceptance_criteria(self):
        # spec "NULL AcceptanceCriteria" — None stored, no exception
        imp = self._make({"AcceptanceCriteria": None})
        results = imp.extract_results("pf-null")
        self.assertIsNone(results["myqa_passfail_acceptance_criteria"])

    def test_long_text(self):
        # spec "Long AcceptanceCriteria text" — full text stored
        long_text = "x" * 500
        imp = self._make({"AcceptanceCriteria": long_text})
        results = imp.extract_results("pf-long")
        self.assertEqual(len(results["myqa_passfail_acceptance_criteria"]), 500)

    def test_empty_result_set(self):
        imp = self._make(fetchone_row=None)
        results = imp.extract_results("pf-empty")
        self.assertEqual(results, {"myqa_passfail_taskid": "pf-empty"})

    def test_no_passstatus_or_testconditions_in_sql(self):
        # spec R1: removes broken PassStatus + MQA_TestConditions reads.
        imp = self._make({"AcceptanceCriteria": "ok"})
        imp.extract_results("pf-1")
        sql, _ = imp.conn.cursor.return_value.executed[0]
        self.assertNotIn("PassStatus", sql)
        self.assertNotIn("MQA_TestConditions", sql)


class TestPassFailDiscover(unittest.TestCase):
    def test_single_string_spec(self):
        # spec R4 — single Test, type='string', no tolerance
        cursor = FakeCursor(fetchone_rows=[])
        conn = mock.Mock()
        conn.cursor.return_value = cursor
        imp = make_importer(MyqaPassFailImport, conn=conn)
        specs = imp.discover_setup_tests()
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec["slug"], "myqa_passfail_acceptance_criteria")
        self.assertEqual(spec["type"], "string")
        self.assertIsNone(spec["warn"])
        self.assertIsNone(spec["fail"])


if __name__ == "__main__":
    unittest.main()
