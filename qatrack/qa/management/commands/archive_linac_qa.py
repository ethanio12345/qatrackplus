"""Generate and/or email the linac QA archive PDF bundle.

Mirrors the myQA command pattern (qatrack/qa/management/commands/import_myqa.py).
"""

from django.core.management.base import BaseCommand

from qatrack.reports import qa_archive, qa_selection


class Command(BaseCommand):
    help = (
        "Generate the linac QA archive: one PDF per canonical UnitTestCollection "
        "for the chosen window, packaged into a zip. Optionally email the zip "
        "to a group or write it to a directory."
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
            help="Write the resulting zip to this directory (created if missing).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print the selected UTC list without rendering any PDFs.",
        )

    def handle(self, *args, **opts):
        try:
            window_start, window_end = qa_selection.resolve_window(opts["window"])
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        label = window_start.strftime("%Y-%m")
        self.stdout.write(
            "Window: %s (%s to %s)" % (label, window_start.date(), window_end.date())
        )

        utcs = qa_selection.select_archive_utcs(window_start, window_end)
        if not utcs.exists():
            self.stdout.write(self.style.WARNING("No UTCs selected for %s." % label))
            return

        self.stdout.write("Selected %d UTC(s):" % utcs.count())
        for utc in utcs:
            self.stdout.write(
                "  %-20s %-45s %-12s TLI=%d"
                % (utc.unit.name, utc.name, utc.frequency.name, utc.tli_in_window)
            )

        if opts["dry_run"]:
            return

        zip_path, summary = qa_archive.generate_archive(
            window_start, window_end, opts["out_dir"]
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Rendered %d PDF(s) to %s (%d skipped)"
                % (summary["count"], zip_path, len(summary["skipped"]))
            )
        )

        if opts["email"]:
            recipients = qa_archive.recipients_for_group(opts["email"])
            if not recipients:
                self.stderr.write(
                    self.style.ERROR(
                        "No recipients found in group %r; email not sent."
                        % opts["email"]
                    )
                )
            else:
                attached = qa_archive.email_archive(zip_path, recipients, summary)
                if attached:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Archive emailed (attached) to %d recipient(s)."
                            % len(recipients)
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "Archive too large to attach; emailed on-site link to %d recipient(s)."
                            % len(recipients)
                        )
                    )
