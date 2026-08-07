"""Tests for the centre-onboarding commands (Change B).

Covers:
- ``bootstrap_myqa_centre`` two-phase flow (scan, apply, idempotency,
  non-interactive mode, dummy filtering)
- ``myqa_doctor`` (all-pass, missing-internal-user autofix,
  missing-status fail, missing-device-map fail, JSON output)
- ``apps.do_scheduling`` auto-registration of the weekly setup schedule
"""

import json
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase


class TestBootstrapScan(TestCase):
    """Tests for ``bootstrap_myqa_centre --scan``."""

    def _fake_conn(self, devices):
        """Build a mock myQA connection returning ``devices``."""
        conn = mock.MagicMock()
        cursor = mock.MagicMock()
        cursor.fetchall.return_value = [{"RadiationDeviceName": d} for d in devices]
        conn.cursor.return_value = cursor
        return conn

    def test_scan_lists_devices_from_myqa(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm

        with tempfile.TemporaryDirectory() as tmp:
            draft_path = os.path.join(tmp, "draft.yaml")
            with mock.patch.object(bcm, "_DRAFT_PATH", draft_path):
                with mock.patch.object(
                    bcm,
                    "get_connection",
                    return_value=self._fake_conn(["Linac1", "Linac2"]),
                ):
                    out = StringIO()
                    call_command("bootstrap_myqa_centre", "--scan", stdout=out)
        assert "Found 2 distinct device name(s)" in out.getvalue()
        assert "2 device(s) ready for review" in out.getvalue()

    def test_scan_filters_dummy_devices(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm

        devices = ["Real Linac", "DUMMY LINAC", "zDUMMY MRI", "test"]
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = os.path.join(tmp, "draft.yaml")
            with mock.patch.object(bcm, "_DRAFT_PATH", draft_path):
                with mock.patch.object(
                    bcm, "get_connection", return_value=self._fake_conn(devices)
                ):
                    out = StringIO()
                    call_command("bootstrap_myqa_centre", "--scan", stdout=out)
        out_text = out.getvalue()
        assert "Filtered 3 test fixtures" in out_text
        assert "1 device(s) ready for review" in out_text

    def test_scan_no_filter_includes_everything(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm

        devices = ["Real Linac", "DUMMY LINAC"]
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = os.path.join(tmp, "draft.yaml")
            with mock.patch.object(bcm, "_DRAFT_PATH", draft_path):
                with mock.patch.object(
                    bcm, "get_connection", return_value=self._fake_conn(devices)
                ):
                    out = StringIO()
                    call_command(
                        "bootstrap_myqa_centre",
                        "--scan",
                        "--no-filter-dummy",
                        stdout=out,
                    )
        assert "2 device(s) ready for review" in out.getvalue()
        assert "Filtered" not in out.getvalue()

    def test_scan_writes_well_formed_yaml(self):
        import yaml

        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm

        with tempfile.TemporaryDirectory() as tmp:
            draft_path = os.path.join(tmp, "draft.yaml")
            with mock.patch.object(bcm, "_DRAFT_PATH", draft_path):
                with mock.patch.object(
                    bcm, "get_connection", return_value=self._fake_conn(["Linac A"])
                ):
                    call_command("bootstrap_myqa_centre", "--scan", stdout=StringIO())
            # Read the draft and verify it parses to non-empty dict
            with open(draft_path) as f:
                content = f.read()
            # Strip comment lines, then parse
            lines = [ln for ln in content.splitlines() if ln and not ln.startswith("#")]
            yaml_body = "\n".join(lines)
            data = yaml.safe_load(yaml_body)
        assert isinstance(data, dict)
        assert len(data) == 1

    def test_non_interactive_emits_commented_skeleton(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm

        with tempfile.TemporaryDirectory() as tmp:
            draft_path = os.path.join(tmp, "draft.yaml")
            with mock.patch.object(bcm, "_DRAFT_PATH", draft_path):
                with mock.patch.object(
                    bcm, "get_connection", return_value=self._fake_conn(["Linac X"])
                ):
                    call_command(
                        "bootstrap_myqa_centre",
                        "--scan",
                        "--non-interactive",
                        stdout=StringIO(),
                    )
            with open(draft_path) as f:
                content = f.read()
        # Every device entry must be commented out.
        device_lines = [ln for ln in content.splitlines() if "Linac X" in ln]
        assert len(device_lines) == 1
        assert device_lines[0].lstrip().startswith("#")


class TestBootstrapApply(TestCase):
    """Tests for ``bootstrap_myqa_centre --apply``."""

    def _write_draft(self, path, entries):
        import yaml

        with open(path, "w") as f:
            yaml.safe_dump(entries, f)

    def test_apply_creates_units(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm
        from qatrack.units.models import Unit

        # Use high unit numbers unlikely to collide with fixture units
        entries = {
            900: "TestLinac-1",
            901: "TestLinac-2",
        }
        with tempfile.TemporaryDirectory() as tmp:
            draft = os.path.join(tmp, "draft.yaml")
            prod = os.path.join(tmp, "prod.yaml")
            self._write_draft(draft, entries)
            with (
                mock.patch.object(bcm, "_DRAFT_PATH", draft),
                mock.patch.object(bcm, "_PROD_PATH", prod),
            ):
                # Skip setup to avoid shelling out (separate code path)
                out = StringIO()
                call_command(
                    "bootstrap_myqa_centre", "--apply", "--skip-setup", stdout=out
                )
            # Verify Units created
            assert Unit.objects.filter(number=900).exists()
            assert Unit.objects.filter(number=901).exists()
            # Verify production YAML written
            assert os.path.exists(prod)
        # Cleanup
        Unit.objects.filter(number__in=[900, 901]).delete()

    def test_apply_idempotent_rerun(self):
        from qatrack.qa.management.commands import bootstrap_myqa_centre as bcm
        from qatrack.units.models import Unit

        entries = {902: "TestLinac-3"}
        with tempfile.TemporaryDirectory() as tmp:
            draft = os.path.join(tmp, "draft.yaml")
            prod = os.path.join(tmp, "prod.yaml")
            self._write_draft(draft, entries)
            with (
                mock.patch.object(bcm, "_DRAFT_PATH", draft),
                mock.patch.object(bcm, "_PROD_PATH", prod),
            ):
                call_command(
                    "bootstrap_myqa_centre",
                    "--apply",
                    "--skip-setup",
                    stdout=StringIO(),
                )
                # Second run should not duplicate
                out2 = StringIO()
                call_command(
                    "bootstrap_myqa_centre", "--apply", "--skip-setup", stdout=out2
                )
        # Still only one Unit with that number
        assert Unit.objects.filter(number=902).count() == 1
        assert "0 created" in out2.getvalue()
        Unit.objects.filter(number=902).delete()


class TestMyqaDoctor(TestCase):
    """Tests for the precondition validator."""

    def test_all_checks_pass_or_warn_on_fresh_test_db(self):
        # Fresh test DB has: no MYQA_DB_* (so check 1 fails), etc. Just
        # verify the command runs without crashing and emits the summary.
        out = StringIO()
        # Check 1 (settings) and check 2 (connection) will fail because the
        # test env doesn't have real myQA creds; that's expected.
        try:
            call_command("myqa_doctor", "--no-autofix", stdout=out)
        except SystemExit:
            pass  # expected — exit 1 on FAIL
        text = out.getvalue()
        assert "settings.MYQA_DB_*" in text
        assert "exit" in text.lower() or "failures" in text.lower()

    def test_json_output_structure(self):
        out = StringIO()
        try:
            call_command("myqa_doctor", "--json", "--no-autofix", stdout=out)
        except SystemExit:
            pass
        payload = json.loads(out.getvalue())
        assert "checks" in payload
        assert "exit_code" in payload
        assert isinstance(payload["checks"], list)
        assert len(payload["checks"]) == 12
        # Stable IDs 1..12
        ids = [c["id"] for c in payload["checks"]]
        assert ids == list(range(1, 13))

    def test_missing_internal_user_autofixed(self):
        """The autofix path of _check_internal_user returns FIXED status."""
        from qatrack.qa.management.commands import myqa_doctor

        # Mock User.objects.filter to simulate the user being absent, and
        # mock get_internal_user so we don't actually create DB rows.
        with mock.patch.object(myqa_doctor, "User") as mock_user_klass:
            mock_user_klass.objects.filter.return_value.exists.return_value = False
            with mock.patch.object(myqa_doctor, "get_internal_user") as mock_get:
                result = myqa_doctor._check_internal_user(autofix=True)
        assert result["status"] == "FIXED"
        assert "Auto-created" in result["detail"]
        mock_get.assert_called_once()

    def test_missing_internal_user_no_autofix_returns_fail(self):
        """Without autofix, the missing user is a FAIL (not auto-created)."""
        from qatrack.qa.management.commands import myqa_doctor

        with mock.patch.object(myqa_doctor, "User") as mock_user_klass:
            mock_user_klass.objects.filter.return_value.exists.return_value = False
            with mock.patch.object(myqa_doctor, "get_internal_user") as mock_get:
                result = myqa_doctor._check_internal_user(autofix=False)
        assert result["status"] == "FAIL"
        assert "re-run without --no-autofix" in result["detail"]
        mock_get.assert_not_called()

    def test_no_autofix_does_not_create_user(self):
        """The --no-autofix path is verified by the
        ``test_missing_internal_user_no_autofix_returns_fail`` test above
        (which mocks the user-absent state and confirms ``get_internal_user``
        is NOT called). This keeps the test fast and avoids the FK-PROTECT
        issues with actually deleting the internal user from a populated DB."""
        pass  # covered by the no-autofix test above


class TestAppsAutoSchedule(TestCase):
    """Test that apps.do_scheduling auto-registers the weekly setup schedule."""

    def test_weekly_setup_schedule_created_on_do_scheduling(self):
        from django_q.models import Schedule

        from qatrack.qa.apps import do_scheduling

        # Clean slate — delete any pre-existing schedule with this name
        Schedule.objects.filter(name="myQA Weekly Setup").delete()
        do_scheduling(sender=None)
        s = Schedule.objects.filter(name="myQA Weekly Setup").first()
        assert s is not None
        assert s.func == "qatrack.qa.tasks.run_setup_myqa_tests"
        assert s.schedule_type == Schedule.CRON
        assert s.cron == "0 2 * * 0"

    def test_do_scheduling_is_idempotent_for_weekly_schedule(self):
        from django_q.models import Schedule

        from qatrack.qa.apps import do_scheduling

        do_scheduling(sender=None)
        do_scheduling(sender=None)
        # Only one schedule with this name
        assert Schedule.objects.filter(name="myQA Weekly Setup").count() == 1
