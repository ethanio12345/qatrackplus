from django.core.management.base import BaseCommand

from qatrack.qa.tasks import import_matrix_monthly


class Command(BaseCommand):
    """A management command to import monthly matrix dosimetry data"""

    help = 'Import monthly matrix dosimetry results from myQA into QATrack+'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview only, no database writes',
        )
        parser.add_argument(
            '--unit',
            type=int,
            default=None,
            help='Only import for this specific unit number',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Look back this many days for sessions to import (default: 30)',
        )

    def handle(self, *args, **kwargs):
        import_matrix_monthly(
            dry_run=kwargs.get('dry_run', False),
            unit=kwargs.get('unit'),
            days=kwargs.get('days', 30),
        )
