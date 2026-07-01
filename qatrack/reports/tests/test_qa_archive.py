import zipfile
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from django.utils.text import slugify

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.reports import qa_archive
from qatrack.reports.qa_selection import LINAC_UNIT_TYPE_NAMES
from qatrack.units.models import UnitType


def _freq(name):
    freq, _ = models.Frequency.objects.get_or_create(
        name=name,
        defaults={
            "slug": name.lower(),
            "nominal_interval": 1,
            "window_end": 1,
            "recurrences": "",
        },
    )
    return freq


def _linac(name="linac"):
    tipe, _ = UnitType.objects.get_or_create(name=LINAC_UNIT_TYPE_NAMES[0])
    return utils.create_unit(name=name, tipe=tipe)


class TestGenerateArchive(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.window = (
            self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            self.now,
        )
        self.daily = _freq("Daily")
        self.unit = _linac("LA1")
        self.utc = utils.create_unit_test_collection(
            unit=self.unit,
            frequency=self.daily,
            test_collection=utils.create_test_list(name="Daily Constancy"),
        )
        utils.create_test_list_instance(
            unit_test_collection=self.utc, work_completed=self.now
        )

    def test_generate_archive_produces_zip_with_pdf(self):
        zip_path, summary = qa_archive.generate_archive(*self.window)
        assert summary["count"] == 1
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert len(names) == 1
            expected = "%s/%s_%s.pdf" % (
                slugify(self.unit.name),
                slugify(self.utc.name),
                self.window[0].strftime("%Y-%m"),
            )
            assert names[0] == expected
            assert zf.read(names[0])[:4] == b"%PDF"

    def test_generate_archive_out_dir(self):
        import tempfile

        out = tempfile.mkdtemp()
        zip_path, summary = qa_archive.generate_archive(*self.window, out_zip_path=out)
        assert zip_path.endswith(summary["zip_name"])
        assert summary["zip_name"] == "linac_qa_archive_%s.zip" % self.window[
            0
        ].strftime("%Y-%m")

    def test_render_utc_pdf_bytes(self):
        pdf_bytes = qa_archive.render_utc_pdf(self.utc, self.window)
        assert pdf_bytes[:4] == b"%PDF"

    def test_generate_archive_skips_render_errors(self):
        with mock.patch.object(
            qa_archive, "render_utc_pdf", side_effect=RuntimeError("boom")
        ):
            zip_path, summary = qa_archive.generate_archive(*self.window)
        assert summary["count"] == 0
        assert len(summary["skipped"]) == 1
        assert "boom" in summary["skipped"][0]["reason"]


class TestRecipientsAndEmail(TestCase):
    def test_recipients_for_missing_group(self):
        assert qa_archive.recipients_for_group("does-not-exist") == []

    def test_email_size_guard_skips_attachment_when_too_large(self):
        from django.contrib.auth.models import Group, User

        group = Group.objects.create(name="phys")
        User.objects.create_user("phys1", email="p@example.com")
        group.user_set.add(User.objects.get(username="phys1"))

        zip_path, summary = qa_archive.generate_archive(
            timezone.now() - timezone.timedelta(days=1), timezone.now()
        )
        with mock.patch.object(qa_archive, "send_email_to_users") as send:
            attached = qa_archive.email_archive(
                zip_path, ["x@example.com"], summary, max_attach_mb=0
            )
        assert attached is False
        # no attachment passed when over limit
        kwargs = send.call_args.kwargs
        assert kwargs["attachments"] == []
        assert kwargs["context"]["too_large"] is True


class TestMirror(TestCase):
    def test_copy_to_mirror_copies_zip(self):
        import os
        import shutil

        mirror = "/tmp/qa_mirror_test_%d" % os.getpid()
        try:
            zip_path, summary = qa_archive.generate_archive(
                timezone.now() - timezone.timedelta(days=1), timezone.now()
            )
            dest = qa_archive.copy_to_mirror(zip_path, mirror_dir=mirror)
            assert dest is not None
            assert os.path.exists(dest)
            assert os.path.basename(dest) == os.path.basename(zip_path)
        finally:
            shutil.rmtree(mirror, ignore_errors=True)

    def test_copy_to_mirror_failure_is_non_fatal(self):
        # an unwritable/missing path should return None, not raise
        dest = qa_archive.copy_to_mirror(
            "/does/not/exist.zip", mirror_dir="/proc/cannot/write/here"
        )
        assert dest is None


class TestDetachedSpawn(TestCase):
    """The django-q entry points must spawn the management command detached
    (so the long render isn't killed by the qcluster 60s task timeout)."""

    def test_run_linac_qa_archive_spawns_detached(self):
        from qatrack.reports import tasks

        with mock.patch.object(
            tasks, "_run_detached", return_value={"spawned": True}
        ) as spawn:
            res = tasks.run_linac_qa_archive(window="lastmonth")
        assert res["spawned"] is True
        spawn.assert_called_once()
        assert spawn.call_args.args[0] == "archive_linac_qa"
        assert "--window" in spawn.call_args.args[1]

    def test_run_daily_qa_bundle_spawns_detached(self):
        from qatrack.reports import tasks

        with mock.patch.object(
            tasks, "_run_detached", return_value={"spawned": True}
        ) as spawn:
            tasks.run_daily_qa_bundle(window="2026-06", email_group="physicists")
        assert spawn.call_args.args[0] == "daily_qa_bundle"
        args = spawn.call_args.args[1]
        assert "--window" in args and "2026-06" in args
        assert "--email" in args

    def test_run_linac_qa_archive_rejects_bad_window(self):
        from qatrack.reports import tasks

        with mock.patch.object(tasks, "_run_detached") as spawn:
            with self.assertRaises(ValueError):
                tasks.run_linac_qa_archive(window="nonsense")
        spawn.assert_not_called()
