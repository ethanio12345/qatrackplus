from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Import myQA results into QATrack+ for specified task types and units'

    def add_arguments(self, parser):
        parser.add_argument(
            '--task',
            type=str,
            default=None,
            help='Filter to specific task type (e.g. myqa_numeric, myqa_profile)',
        )
        parser.add_argument(
            '--unit',
            type=int,
            default=None,
            help='Filter to specific unit number (e.g. 3 for LA317)',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Look back this many days for sessions to import (default: 30)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview only, no database writes',
        )

    def handle(self, *args, **kwargs):
        from qatrack.qa.tasks import import_myqa_all
        summary = import_myqa_all(
            task=kwargs.get('task'),
            unit=kwargs.get('unit'),
            days=kwargs.get('days', 30),
            dry_run=kwargs.get('dry_run', False),
        )

        self.stdout.write(
            f"Imported: {summary['imported']}, "
            f"Skipped (dup): {summary['skipped_dup']}, "
            f"Skipped (err): {summary['skipped_err']}, "
            f"Total found: {summary['total']}"
        )

        if summary['skipped_err'] > 0:
            self.stdout.write(self.style.WARNING(f"{summary['skipped_err']} errors occurred"))
