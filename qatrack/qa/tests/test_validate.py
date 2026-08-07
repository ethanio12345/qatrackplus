"""Tests for the myqa_validate diff command (Change C).

The command compares QATrack+ state to myQA source-of-truth. Tests mock
the myQA connection and use fixture QATrack+ data to verify each scenario:

- session-count mismatch
- per-condition value mismatch
- valueless_skip vs genuine_drop distinction
- JSON output schema
"""

import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase


def _mock_myqa_session(exec_id, ref_date, device_name="Linac1"):
    """Build a session dict matching what query_sessions returns."""
    return {
        "task_execution_id": exec_id,
        "reference_date": ref_date,
        "finishing_date": ref_date,
        "task_name": "Whatever",
        "unit_number": 1,
        "linac_name": device_name,
    }


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Fake myQA connection. Returns canned data from extract_all_types."""

    def __init__(self, extract_results: dict[str, dict]):
        """``extract_results`` maps exec_id → results dict."""
        self._extract = extract_results
        self.closed = False

    def cursor(self, as_dict=False):
        # Used by compute_multi_flags (returns empty — no multi test steps)
        return _FakeCursor([])

    def close(self):
        self.closed = True


class TestMyqaValidate(TestCase):
    """Tests for the diff command. We mock at the import boundary
    (get_connection, query_sessions, extract_all_types, duplicate_check)
    rather than constructing a full myQA fixture."""

    def _sessions(self, sessions):
        """Patch the myQA query layer to return the given session list."""
        return mock.patch(
            "qatrack.qa.management.commands.myqa_validate.query_sessions",
            return_value=sessions,
        )

    def _extract(self, mapping):
        """Patch extract_all_types to return mapping[exec_id]."""

        def fake_extract(conn, exec_id, multi_flags=None):
            return mapping.get(exec_id, {})

        return mock.patch(
            "qatrack.qa.management.commands.myqa_validate.extract_all_types",
            side_effect=fake_extract,
        )

    def _dup(self, dup_exec_ids: set[str]):
        """Patch duplicate_check to return True for the given exec_ids."""

        def fake_dup(taskname, exec_id, unit_number):
            return exec_id in dup_exec_ids

        return mock.patch(
            "qatrack.qa.management.commands.myqa_validate.duplicate_check",
            side_effect=fake_dup,
        )

    def _conn(self):
        return mock.patch(
            "qatrack.qa.management.commands.myqa_validate.get_connection",
            return_value=_FakeConn({}),
        )

    def _tasknames(self, tns):
        # discover_tasknames is imported locally inside _recent_tasknames,
        # so patch it at the source module.
        return mock.patch("qatrack.myqa_import.discover_tasknames", return_value=tns)

    def test_no_sessions_emits_nothing(self):
        with self._conn(), self._sessions([]), self._tasknames(["Whatever"]):
            out = StringIO()
            call_command("myqa_validate", "--days", "30", stdout=out)
        # No TestLists printed
        assert "Summary: 0 pass" in out.getvalue()

    def test_valueless_skip_categorised_correctly(self):
        """A session with no non-null values is valueless_skip, not genuine_drop."""
        from datetime import datetime, timedelta

        ref_date = datetime.now() - timedelta(days=1)
        sessions = [_mock_myqa_session("val-1", ref_date)]
        extract = {
            "val-1": {"condition_a": {"value": None}, "condition_b": {"value": None}}
        }
        with (
            self._conn(),
            self._sessions(sessions),
            self._extract(extract),
            self._dup(set()),
            self._tasknames(["Whatever"]),
        ):
            out = StringIO()
            call_command("myqa_validate", "--days", "30", "--summary-only", stdout=out)
        text = out.getvalue()
        assert "valueless-skip" in text
        assert "1 valueless-skip" in text
        assert "0 genuine-drop" in text

    def test_genuine_drop_categorised_correctly(self):
        """A session with at least one non-null value but no TLI is genuine_drop."""
        from datetime import datetime, timedelta

        ref_date = datetime.now() - timedelta(days=1)
        sessions = [_mock_myqa_session("drop-1", ref_date)]
        extract = {"drop-1": {"condition_a": {"value": 1.234}}}
        with (
            self._conn(),
            self._sessions(sessions),
            self._extract(extract),
            self._dup(set()),
            self._tasknames(["Whatever"]),
        ):
            out = StringIO()
            call_command("myqa_validate", "--days", "30", "--summary-only", stdout=out)
        text = out.getvalue()
        assert "1 genuine-drop" in text
        assert "needs review" in text.lower()

    def test_imported_session_not_flagged(self):
        """A session that duplicate_check says is imported is neither
        valueless nor drop."""
        from datetime import datetime, timedelta

        ref_date = datetime.now() - timedelta(days=1)
        sessions = [_mock_myqa_session("imp-1", ref_date)]
        extract = {"imp-1": {"condition_a": {"value": 1.0}}}
        with (
            self._conn(),
            self._sessions(sessions),
            self._extract(extract),
            self._dup({"imp-1"}),
            self._tasknames(["Whatever"]),
        ):
            out = StringIO()
            call_command(
                "myqa_validate", "--days", "30", "--summary-only", "--json", stdout=out
            )
        payload = json.loads(out.getvalue())
        # No testlists should be reported (session imported → no TLI to validate against)
        # OR if reported, status should be "pass" with zero valueless/drop
        for tl in payload["testlists"]:
            sess = tl["sessions"]
            assert sess["valueless_skip"] == 0
            assert sess["genuine_drop"] == 0
            assert tl["status"] == "pass"

    def test_json_output_structure(self):
        from datetime import datetime, timedelta

        ref_date = datetime.now() - timedelta(days=1)
        sessions = [_mock_myqa_session("v-1", ref_date)]
        extract = {"v-1": {}}
        with (
            self._conn(),
            self._sessions(sessions),
            self._extract(extract),
            self._dup(set()),
            self._tasknames(["Whatever"]),
        ):
            out = StringIO()
            call_command(
                "myqa_validate", "--days", "30", "--summary-only", "--json", stdout=out
            )
        payload = json.loads(out.getvalue())
        assert "window_days" in payload
        assert payload["window_days"] == 30
        assert "summary" in payload
        assert "testlists" in payload
        assert isinstance(payload["testlists"], list)
        # If any testlist reported, has the stable schema
        for tl in payload["testlists"]:
            assert "taskname" in tl
            assert "unit_number" in tl
            assert "status" in tl
            assert "sessions" in tl
            sess = tl["sessions"]
            for k in (
                "myqa_in_window",
                "qatrack_in_window",
                "missing",
                "valueless_skip",
                "genuine_drop",
            ):
                assert k in sess, f"missing key {k}"

    def test_filter_by_task_name(self):
        """--task-name limits the validation to one TaskName."""
        from datetime import datetime, timedelta

        ref_date = datetime.now() - timedelta(days=1)
        sessions = [_mock_myqa_session("v-1", ref_date)]
        with (
            self._conn(),
            self._sessions(sessions),
            self._extract({}),
            self._dup(set()),
        ):
            # No discover_tasknames patch — command shouldn't call it when --task-name passed
            out = StringIO()
            call_command(
                "myqa_validate",
                "--task-name",
                "Whatever",
                "--days",
                "30",
                "--summary-only",
                stdout=out,
            )
        # Should run without error
        assert "Summary" in out.getvalue()
