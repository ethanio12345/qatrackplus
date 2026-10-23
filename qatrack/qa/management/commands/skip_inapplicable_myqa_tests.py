"""Flag historical test results for beam energies a unit doesn't have.

myQA task templates contain conditions for every beam energy on every
machine, so linacs without electrons (or without 18X) imported junk
placeholder readings (e.g. 0.03) that fail tolerance and permanently block
auto-review of the affected sessions.

This command, driven by ``unit_energy_caps`` in ``myqa_centre_config.yaml``:

  1. scans TestInstances on capped units and finds tests classified as an
     energy the unit lacks;
  2. (dry-run by default) reports findings per unit/test list/test, including
     how many sessions would become fully reviewed once the junk is flagged;
  3. with ``--apply``, marks those TestInstances skipped (commented,
     pass_fail=not_done) and re-runs auto-approval on the affected sessions —
     sessions whose only blocker was the junk energy readings then clear the
     unreviewed queue, while genuine failures keep requiring review;
  4. optionally deactivates the per-unit UnitTestInfos
     (``--deactivate-utis``) so those tests stop being offered/reported for
     the unit, and/or deactivates all UTCs of chosen units
     (``--deactivate-utcs --units 4,5``) for retired machines.

Idempotent: already-skipped TestInstances and already-inactive UTIs/UTCs are
no-ops, so the command can be re-run safely.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from qatrack.myqa_import import (
    classify_test_energy,
    energy_applicable,
    get_unit_energy_caps,
)
from qatrack.qa.models import (
    TestInstance,
    TestListInstance,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.qa.utils import get_internal_user
from qatrack.units.models import Unit


def _energy_label(test_name: str) -> str:
    """Human label for the beam energy a test belongs to."""
    kind, energy = classify_test_energy(test_name)
    if kind == "electron":
        return "electron" if energy is None else f"{energy}MeV electron"
    if kind == "photon":
        return f"{energy} photon"
    return "non-energy"


class Command(BaseCommand):
    help = (
        "Mark TestInstances for beam energies a unit doesn't have as Skipped "
        "(per unit_energy_caps in myqa_centre_config.yaml), re-run auto-"
        "approval on the affected sessions, and optionally deactivate the "
        "unit's UnitTestInfos / UnitTestCollections."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Perform the changes (default: dry-run report only).",
        )
        parser.add_argument(
            "--deactivate-utis",
            action="store_true",
            help="Also set active=False on UnitTestInfos for inapplicable "
            "tests so they stop being offered/reported for the unit.",
        )
        parser.add_argument(
            "--deactivate-utcs",
            action="store_true",
            help="Also deactivate every UnitTestCollection of the units "
            "given by --units (retired machines).",
        )
        parser.add_argument(
            "--units",
            default="",
            help="Comma-separated unit numbers: restrict the TestInstance "
            "scan (and select units for --deactivate-utcs), e.g. --units 4,5.",
        )

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _iter_findings(self, unit_numbers):
        """Yield ``(unit, caps, inapplicable_tis)`` per capped unit.

        ``inapplicable_tis`` are TestInstances (already-skipped ones
        included) whose test is classified as an energy the unit lacks.
        """
        units = Unit.objects.all().order_by("name")
        if unit_numbers:
            units = units.filter(number__in=unit_numbers)
        for unit in units:
            caps = get_unit_energy_caps(unit.number)
            if caps is None:
                continue
            qs = (
                TestInstance.objects.filter(unit_test_info__unit=unit)
                .select_related(
                    "unit_test_info__test",
                    "test_list_instance__test_list",
                )
                .iterator(chunk_size=2000)
            )
            inapplicable = [
                ti
                for ti in qs
                if not energy_applicable(ti.unit_test_info.test.name, caps)
            ]
            if inapplicable:
                yield unit, caps, inapplicable

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _report(self, unit, inapplicable, opts):
        """Print per-unit findings; return count of TLIs that would become
        fully reviewed."""
        by_list_test = defaultdict(lambda: [0, set()])  # (list, test) -> [n, tli_ids]
        tis_by_tli = defaultdict(list)
        for ti in inapplicable:
            list_name = ti.test_list_instance.test_list.name
            test_name = ti.unit_test_info.test.name
            by_list_test[(list_name, test_name)][0] += 1
            by_list_test[(list_name, test_name)][1].add(ti.test_list_instance_id)
            tis_by_tli[ti.test_list_instance_id].append(ti.pk)

        n_would_approve = 0
        for (list_name, test_name), (n, tli_ids) in sorted(by_list_test.items()):
            label = _energy_label(test_name)
            self.stdout.write(
                f"  {list_name:<55.55} {test_name:<45.45} {n:>5} TI(s) in {len(tli_ids):>4} session(s) [{label}]"
            )

        if opts["apply"]:
            return 0  # real numbers reported after mutation

        for tli_id in tis_by_tli:
            # Would the session become fully reviewed once the inapplicable
            # TIs are skipped? Only if no *other* TI still requires review
            # and the session isn't already reviewed.
            still_blocked = (
                TestInstance.objects.filter(test_list_instance_id=tli_id)
                .exclude(pk__in=tis_by_tli[tli_id])
                .filter(status__requires_review=True)
                .exists()
            )
            already_reviewed = not TestInstance.objects.filter(
                test_list_instance_id=tli_id, status__requires_review=True
            ).exists()
            if not already_reviewed and not still_blocked:
                n_would_approve += 1

        self.stdout.write(
            self.style.NOTICE(
                f"  => {n_would_approve} session(s) would become fully reviewed"
            )
        )
        return n_would_approve

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def _apply_skips(self, unit, inapplicable):
        """Skip inapplicable TIs, re-run auto-approval on their sessions."""
        internal_user = get_internal_user()
        already = 0
        to_update = []
        for ti in inapplicable:
            if ti.skipped:
                already += 1
                continue
            ti.skipped = True
            ti.comment = f"Not applicable: {unit.name} has no {_energy_label(ti.unit_test_info.test.name)} beam (unit_energy_caps)"
            # skipped=True => pass_fail=not_done => Default AutoReviewRuleSet
            # maps it to Approved, so it no longer blocks review.
            ti.calculate_pass_fail()
            to_update.append(ti)

        for i in range(0, len(to_update), 1000):
            TestInstance.objects.bulk_update(
                to_update[i : i + 1000],
                ["skipped", "comment", "pass_fail"],
                batch_size=1000,
            )

        n_approved = 0
        tli_ids = {ti.test_list_instance_id for ti in to_update}
        for tli in TestListInstance.objects.filter(id__in=tli_ids).iterator():
            if tli.auto_approve(review_user=internal_user):
                n_approved += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  {unit.name}: flagged {len(to_update)} TI(s) skipped ({already} already done); "
                f"{n_approved} session(s) auto-approved."
            )
        )
        return len(to_update), n_approved

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        unit_numbers = self._parse_units(opts["units"])

        if opts["deactivate_utcs"]:
            if not unit_numbers:
                raise CommandError(
                    "--deactivate-utcs requires --units <n,n,...> to name the units."
                )
            if not opts["apply"]:
                self._preview_utc_deactivation(unit_numbers)

        findings = list(self._iter_findings(unit_numbers))
        if not findings:
            self.stdout.write("No inapplicable TestInstances found — nothing to do.")
            if opts["deactivate_utcs"] and opts["apply"]:
                self._deactivate_utcs(unit_numbers)
            return

        total_tis = 0
        total_approved = 0
        for unit, _caps, inapplicable in findings:
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"Unit {unit.number} ({unit.name}): {len(inapplicable)} inapplicable TI(s)"
                )
            )
            if opts["apply"]:
                n_tis, n_approved = self._apply_skips(unit, inapplicable)
                total_tis += n_tis
                total_approved += n_approved
            else:
                total_approved += self._report(unit, inapplicable, opts)

        if opts["apply"] and opts["deactivate_utis"]:
            self._deactivate_utis(findings)

        if opts["deactivate_utcs"] and opts["apply"]:
            self._deactivate_utcs(unit_numbers)

        if opts["apply"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done: {total_tis} TI(s) flagged; {total_approved} session(s) auto-approved."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run — {total_approved} session(s) would become fully reviewed. "
                    "Re-run with --apply to make the changes."
                )
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_units(raw):
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            return [int(part) for part in raw.split(",") if part.strip()]
        except ValueError:
            raise CommandError("--units must be comma-separated integers, e.g. 4,5")

    def _deactivate_utis(self, findings):
        total = 0
        for unit, _caps, inapplicable in findings:
            test_ids = {ti.unit_test_info.test_id for ti in inapplicable}
            n = UnitTestInfo.objects.filter(
                unit=unit, test_id__in=test_ids, active=True
            ).update(active=False)
            total += n
            self.stdout.write(f"  {unit.name}: deactivated {n} UTI(s)")
        self.stdout.write(self.style.SUCCESS(f"Deactivated {total} UTI(s) total."))

    def _deactivate_utcs(self, unit_numbers):
        n = UnitTestCollection.objects.filter(
            unit__number__in=unit_numbers, active=True
        ).update(active=False, auto_schedule=False)
        self.stdout.write(
            self.style.SUCCESS(f"Deactivated {n} UTC(s) on unit(s) {unit_numbers}")
        )

    def _preview_utc_deactivation(self, unit_numbers):
        names = list(
            Unit.objects.filter(number__in=unit_numbers).values_list("name", flat=True)
        )
        counts = {}
        for number in unit_numbers:
            counts[number] = UnitTestCollection.objects.filter(
                unit__number=number, active=True
            ).count()
        self.stdout.write(
            "Would deactivate UTCs: "
            + ", ".join(
                f"{number} ({name}: {counts.get(number, 0)} active)"
                for number, name in zip(unit_numbers, names)
            )
        )
        self.stdout.write(
            self.style.WARNING("Dry run — re-run with --apply to make the changes.")
        )
