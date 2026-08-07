"""Clear due dates on stale UnitTestCollections (no longer in clinical rotation).

A UTC is "stale" when it hasn't been performed in a long time relative to its
frequency. The rule is frequency-aware:

    stale if last run is None (never ran)
         OR days_since_last_run >= max(--floor, --multiplier * nominal_interval)

so a Daily suite stale 6 months is flagged (clearly decommissioned) while an
Annual suite stale 6 months is not (only ~2 cycles; could be legitimately
overdue). Flagged UTCs get ``due_date=None`` and ``auto_schedule=False`` so the
scheduler doesn't re-add a due date.

Default is a dry run (prints the selection); pass --apply to change records.
Idempotent.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from qatrack.qa.models import UnitTestCollection
from qatrack.reports.qa_selection import get_linac_unit_type_names

FLOOR_DEFAULT = 180
MULTIPLIER_DEFAULT = 3


def _days_since_last(utc, now):
    last = utc.last_instance.work_completed if utc.last_instance else None
    return None if last is None else (now - last).days


def _is_stale(utc, now, multiplier, floor):
    """True if the UTC is stale per the frequency-aware rule."""
    if utc.frequency is None:
        return False  # ad-hoc / manual scheduling; skip
    days = _days_since_last(utc, now)
    if days is None:
        return True  # never ran
    threshold = max(floor, multiplier * utc.frequency.nominal_interval)
    return days >= threshold


class Command(BaseCommand):
    help = (
        "Clear due_date (and set auto_schedule=False) on stale UTCs (frequency-aware)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--multiplier",
            type=float,
            default=MULTIPLIER_DEFAULT,
            help="Stale if days >= multiplier * nominal_interval (default %(default)s).",
        )
        parser.add_argument(
            "--floor",
            type=int,
            default=FLOOR_DEFAULT,
            help="Minimum days before any UTC is considered stale (default %(default)s).",
        )
        parser.add_argument(
            "--linacs-only",
            action="store_true",
            default=False,
            help="Restrict to linac unit types.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Apply changes (default: dry run).",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        qs = UnitTestCollection.objects.filter(
            active=True, due_date__isnull=False
        ).select_related("unit__type", "frequency", "last_instance")
        if opts["linacs_only"]:
            qs = qs.filter(unit__type__name__in=get_linac_unit_type_names())

        stale = [u for u in qs if _is_stale(u, now, opts["multiplier"], opts["floor"])]
        if not stale:
            self.stdout.write("No stale UTCs match the rule.")
            return

        self.stdout.write(
            "Rule: stale if never run OR days >= max(%d, %sx nominal_interval) | %d UTCs"
            % (opts["floor"], opts["multiplier"], len(stale))
        )
        for u in sorted(stale, key=lambda x: (x.unit.name, x.name)):
            self.stdout.write(
                "  %-20s %-42s %-12s last=%s"
                % (
                    u.unit.name,
                    u.name[:40],
                    (u.frequency.name if u.frequency else "adhoc"),
                    (
                        _days_since_last(u, now)
                        if _days_since_last(u, now) is not None
                        else "NEVER"
                    ),
                )
            )

        if not opts["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run — no changes. Re-run with --apply to clear due dates."
                )
            )
            return

        pks = [u.pk for u in stale]
        n = UnitTestCollection.objects.filter(pk__in=pks).update(
            due_date=None, auto_schedule=False
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Cleared due_date + set auto_schedule=False on %d UTC(s)." % n
            )
        )
