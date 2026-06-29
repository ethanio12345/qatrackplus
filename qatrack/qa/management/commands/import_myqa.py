"""Import myQA results into QATrack+ for one or all TaskNames."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Import myQA results into QATrack+ for one or all TaskNames. "
        "Sessions are queried by exact TaskName match and all execution "
        "types present in each session are aggregated into one "
        "TestListInstance."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--task-name",
            type=str,
            default=None,
            help="Only import sessions for this specific TaskName (default: all discovered)",
        )
        parser.add_argument(
            "--unit",
            type=int,
            default=None,
            help="Only import sessions for this unit number (e.g. 3 for LA317)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Look back this many days for sessions to import (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview only, no database writes",
        )

    def handle(self, *args, **kwargs):
        from qatrack.qa.tasks import import_myqa_all

        summary = import_myqa_all(
            task_name=kwargs.get("task_name"),
            unit=kwargs.get("unit"),
            days=kwargs.get("days", 30),
            dry_run=kwargs.get("dry_run", False),
        )

        self.stdout.write(
            f"Imported: {summary['imported']}, "
            f"Skipped (dup): {summary['skipped_dup']}, "
            f"Skipped (empty): {summary.get('skipped_empty', 0)}, "
            f"Skipped (err): {summary['skipped_err']}, "
            f"Total found: {summary['total']}"
        )

        if summary["skipped_err"] > 0:
            self.stdout.write(
                self.style.WARNING(f"{summary['skipped_err']} errors occurred")
            )
