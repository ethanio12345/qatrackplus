"""Generate and/or email the per-linac Daily Constancy QA bundle.

Companion to ``archive_linac_qa``; runs the daily-bundle generation synchronously
(reused by the django-q entry point which spawns this command detached).
"""

from django.core.management.base import BaseCommand

from qatrack.reports import qa_archive, qa_selection
from qatrack.reports.qc import daily_bundle


class Command(BaseCommand):
    help = (
        "Generate the per-linac Daily Constancy QA bundle PDFs for a window, "
        "packaged into a zip. Writes to the pdf folder (and mirrors to the "
        "network drive) by default; optionally email."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window",
            type=str,
            default="lastmonth",
            help="Time window: 'lastmonth' (default), 'month', or 'YYYY-MM'.",
        )
        parser.add_argument(
            "--email",
            type=str,
            default=None,
            help="Email the resulting zip to this Group name (size guard applies).",
        )
        parser.add_argument(
            "--out-dir",
            type=str,
            default=None,
            help="Write the resulting zip to this directory (default: <repo>/pdf).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print the resolved daily-constancy UTC per linac without rendering.",
        )

    def handle(self, *args, **opts):
        try:
            window_start, window_end = qa_selection.resolve_window(opts["window"])
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        label = window_start.strftime("%Y-%m")
        self.stdout.write("Window: %s (%s to %s)" % (label, window_start.date(), window_end.date()))

        units = qa_selection.active_linac_units()
        self.stdout.write("Active linacs: %d" % units.count())
        for unit in units:
            c = daily_bundle.resolve_current_daily_constancy_utc(unit)
            self.stdout.write(
                "  %-20s %s" % (unit.name, c.name if c else "SKIP (no Daily Constancy UTC)")
            )

        if opts["dry_run"]:
            return

        out_dir = opts["out_dir"] or qa_archive.default_out_dir()
        zip_path, summary = daily_bundle.generate_daily_bundles(window_start, window_end, out_dir)

        self.stdout.write(
            self.style.SUCCESS(
                "Rendered %d daily bundle(s) to %s (%d skipped)"
                % (summary["count"], zip_path, len(summary["skipped"]))
            )
        )

        mirror = qa_archive.copy_to_mirror(zip_path)
        if mirror:
            self.stdout.write(self.style.SUCCESS("Mirrored to %s" % mirror))
        else:
            self.stdout.write(
                self.style.WARNING("Mirror copy skipped (network drive unavailable?)")
            )

        if opts["email"]:
            recipients = qa_archive.recipients_for_group(opts["email"])
            if not recipients:
                self.stderr.write(
                    self.style.ERROR(
                        "No recipients found in group %r; email not sent." % opts["email"]
                    )
                )
            else:
                attached = qa_archive.email_archive(zip_path, recipients, summary)
                if attached:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Daily bundle emailed (attached) to %d recipient(s)." % len(recipients)
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "Daily bundle too large to attach; emailed on-site link to %d recipient(s)."
                            % len(recipients)
                        )
                    )
