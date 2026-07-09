from unittest import mock

from django.test import TestCase

from qatrack.myqa_import import import_session


class TestSkipValuelessSessions(TestCase):
    """import_session must skip a session whose extracted conditions all have
    NULL values (started/finished in myQA without entering readings)."""

    def _session(self, exec_id="exec-empty-1"):
        return {
            "task_execution_id": exec_id,
            "reference_date": None,
            "finishing_date": None,
            "task_name": "Whatever",
            "unit_number": 1,
            "linac_name": "LA1",
        }

    def _call(self, results):
        """Patch extract_all_types and call import_session with dummy args."""
        with mock.patch("qatrack.myqa_import.extract_all_types", return_value=results):
            return import_session(
                mock.MagicMock(),  # conn
                "Whatever",  # taskname
                self._session(),  # session
                mock.MagicMock(),  # internal_user
                mock.MagicMock(),  # default_status
                {},  # status_map
                {},  # multi_flags
            )

    def test_no_rows_is_skipped_empty(self):
        # extract_all_types returns {} -> skipped
        out = self._call({})
        assert out["status"] == "skipped_empty"

    def test_rows_but_all_values_null_is_skipped_empty(self):
        # rows exist (so the old `if not results` guard passed) but every value
        # is None -> must now be skipped as valueless.
        results = {
            "01. kr (average)": {"value": None, "state": 30},
            "02. kr (max)": {"value": None, "state": 30},
        }
        out = self._call(results)
        assert out["status"] == "skipped_empty"
        assert "no values" in out["reason"]

    def test_session_with_a_value_is_not_skipped_for_emptiness(self):
        # has at least one non-null value -> must NOT be skipped by the
        # valueless guard (it will proceed and hit a later missing-TestList
        # error, which is fine — we only assert it isn't skipped_empty).
        out = self._call({"output": {"value": 1.23, "state": 40}})
        assert out["status"] != "skipped_empty"
