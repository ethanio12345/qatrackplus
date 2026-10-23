"""Flag historical test results that can't apply to a unit, then close out.

Two junk families exist in myQA-sourced data:

1. **Energy-inapplicable readings** — myQA task templates contain conditions
   for every beam energy on every machine, so linacs without electrons (or
   without 18X) imported junk placeholder readings (e.g. 0.03) that fail
   tolerance and permanently block auto-review of the affected sessions.
   Detection is driven by ``unit_energy_caps`` in ``myqa_centre_config.yaml``.

2. **Constant placeholder readings** — because myQA has no "skip" for an
   individual condition, staff sometimes enter a filler value (0.5, 1, 0.03,
   ...) just so the task can be completed. The signature is a numeric series
   where every reading within the stuck sessions is identical
   (``--constant-readings``); detection is scoped to sessions that are still
   unreviewed, since the same test may legitimately vary (or be quantized)
   in reviewed history. Count-type metrics whose constants are legitimate
   (picket-fence failing peaks = 0, MU counters, half-life, ...) are
   excluded by name.

This command:

  1. (dry-run by default) reports findings per unit/test list/test, including
     how many sessions would become fully reviewed once the junk is flagged;
  2. with ``--apply``, marks those TestInstances skipped (commented,
     pass_fail=not_done) and re-runs auto-approval on the affected sessions —
     sessions whose only blocker was junk then clear the unreviewed queue,
     while genuine failures keep requiring review;
  3. optionally deactivates the per-unit UnitTestInfos (``--deactivate-utis``),
     all UTCs of chosen units (``--deactivate-utcs --units 4,5``), or every
     UTC assigned to a retired TestList
     (``--deactivate-list-utcs "<list name>"``);
  4. optionally force-closes any sessions still unreviewed on chosen
     (decommissioned) units (``--force-close-unreviewed --units 4,5``) so
     their record is complete — data is preserved, only the review flags are
     set.

Idempotent: already-skipped TestInstances and already-inactive UTIs/UTCs are
no-ops, so the command can be re-run safely.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Min, Q
from django.utils import timezone

from qatrack.myqa_import import (
    _load_centre_config,
    classify_test_energy,
    energy_applicable,
    get_unit_energy_caps,
)
from qatrack.qa.models import (
    TestInstance,
    TestList,
    TestListInstance,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.qa.utils import get_internal_user
from qatrack.units.models import Unit

# Tests whose value is legitimately constant (counts of fixed things, physical
# constants, ...) must never be flagged by --constant-readings. Matched
# case-insensitively against the Test name.
_COUNT_TYPE_RE = None  # compiled lazily via _count_type_regex()

_COUNT_TYPE_PATTERNS = (
    r"peak",  # picket fence / leaf positional accuracy peak counts
    r"counter",  # "Backup MU counter (MU)"
    r"\bmu\b",  # "MU2 (MU)" — but not "MV"/"murky"
    r"half.life",  # Ir-192 half-life is a physical constant
    r"serial",  # recorded device serial numbers
    r"pressure",  # environmental constants
    r"temperature",
    r"taskid",  # import dedup metadata
)


def _count_type_regex():
    global _COUNT_TYPE_RE
    if _COUNT_TYPE_RE is None:
        import re

        _COUNT_TYPE_RE = re.compile("|".join(_COUNT_TYPE_PATTERNS), re.IGNORECASE)
    return _COUNT_TYPE_RE


def _energy_label(test_name: str) -> str:
    """Human label for the beam energy a test belongs to."""
    kind, energy = classify_test_energy(test_name)
    if kind == "electron":
        return "electron" if energy is None else f"{energy}MeV electron"
    if kind == "photon":
        return f"{energy} photon"
    return "non-energy"


def _caps_comment(unit, ti):
    return f"Not applicable: {unit.name} has no {_energy_label(ti.unit_test_info.test.name)} beam (unit_energy_caps)"


def _constant_comment(unit, ti):
    return (
        f"Not applicable: placeholder readings — '{ti.unit_test_info.test.name}' "
        f"recorded as {ti.value} on every entry (auto-flagged)"
    )


class Command(BaseCommand):
    help = (
        "Flag TestInstances that can't apply to a unit (beam energies the unit "
        "lacks per unit_energy_caps, and/or constant placeholder reading "
        "series), re-run auto-approval on the affected sessions, and "
        "optionally deactivate UnitTestInfos / UnitTestCollections or "
        "force-close remaining unreviewed sessions on decommissioned units."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Perform the changes (default: dry-run report only).",
        )
        parser.add_argument(
            "--constant-readings",
            action="store_true",
            help="Scan for constant placeholder reading series (every "
            "reading of a test identical within sessions that are still "
            "unreviewed) on linac units instead of the energy-caps scan. "
            "Count-type tests (peaks, MU counters, half-life, ...) are "
            "excluded.",
        )
        parser.add_argument(
            "--min-readings",
            type=int,
            default=10,
            help="Minimum number of readings for a series to be considered "
            "by --constant-readings (default: 10).",
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
            "--deactivate-list-utcs",
            action="append",
            default=[],
            metavar="LIST",
            help="Deactivate every UnitTestCollection assigned to the given "
            "TestList (name or slug), on all units — for retired lists. "
            "Repeatable.",
        )
        parser.add_argument(
            "--force-close-unreviewed",
            action="store_true",
            help="Mark any sessions still unreviewed on the units given by "
            "--units as reviewed (decommissioned machines — data preserved, "
            "review flags set).",
        )
        parser.add_argument(
            "--units",
            default="",
            help="Comma-separated unit numbers: restrict the TestInstance "
            "scan (and select units for --deactivate-utcs / "
            "--force-close-unreviewed), e.g. --units 4,5.",
        )

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scoped_units(self, unit_numbers, linacs_only=False):
        units = Unit.objects.all().order_by("name")
        if unit_numbers:
            return units.filter(number__in=unit_numbers)
        if linacs_only:
            linac_types = tuple(
                _load_centre_config().get("linac_unit_type_names") or []
            )
            units = units.filter(type__name__in=linac_types)
        return units

    def _iter_findings(self, unit_numbers):
        """Yield ``(unit, inapplicable_tis)`` per capped unit (energy mode).

        ``inapplicable_tis`` are TestInstances (already-skipped ones
        included) whose test is classified as an energy the unit lacks.
        """
        for unit in self._scoped_units(unit_numbers):
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
                yield unit, inapplicable

    def _iter_constant_findings(self, unit_numbers, min_readings):
        """Yield ``(unit, placeholder_tis)`` per linac unit (constant mode).

        A test's readings form a placeholder series when at least
        ``min_readings`` non-skipped numeric readings exist **in sessions
        that are still unreviewed** and every one of them is identical.
        Scoping to unreviewed sessions is deliberate: junk fillers are what
        keep sessions stuck in the review queue, while the same test may
        legitimately vary (or be quantized) in already-reviewed history —
        e.g. CBCT lp/mm resolution values repeat by design. Count-type tests
        are excluded by name.
        """
        for unit in self._scoped_units(unit_numbers, linacs_only=True):
            series = (
                TestInstance.objects.filter(
                    unit_test_info__unit=unit,
                    value__isnull=False,
                    skipped=False,
                    test_list_instance__all_reviewed=False,
                )
                .values("unit_test_info__test_id", "unit_test_info__test__name")
                .annotate(
                    n=Count("id"),
                    n_distinct=Count("value", distinct=True),
                    constant=Min("value"),
                )
                .filter(n__gte=min_readings, n_distinct=1)
            )
            placeholder_tis = []
            for row in series:
                test_name = row["unit_test_info__test__name"]
                if _count_type_regex().search(test_name):
                    continue  # legitimately constant (peak counts, MU, ...)
                tis = list(
                    TestInstance.objects.filter(
                        unit_test_info__unit=unit,
                        unit_test_info__test_id=row["unit_test_info__test_id"],
                        skipped=False,
                        value=row["constant"],
                        test_list_instance__all_reviewed=False,
                    ).select_related(
                        "unit_test_info__test",
                        "test_list_instance__test_list",
                    )
                )
                placeholder_tis.extend(tis)
            if placeholder_tis:
                yield unit, placeholder_tis

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _label(self, ti, mode):
        if mode == "constant":
            return "constant placeholder"
        return _energy_label(ti.unit_test_info.test.name)

    def _report(self, unit, tis, opts, mode):
        """Print per-unit findings; return count of TLIs that would become
        fully reviewed."""
        by_list_test = defaultdict(lambda: [0, set()])  # (list, test) -> [n, tli_ids]
        tis_by_tli = defaultdict(list)
        for ti in tis:
            list_name = ti.test_list_instance.test_list.name
            test_name = ti.unit_test_info.test.name
            by_list_test[(list_name, test_name)][0] += 1
            by_list_test[(list_name, test_name)][1].add(ti.test_list_instance_id)
            tis_by_tli[ti.test_list_instance_id].append(ti.pk)

        n_would_approve = 0
        for (list_name, test_name), (n, tli_ids) in sorted(by_list_test.items()):
            label = self._label(
                next(t for t in tis if t.unit_test_info.test.name == test_name), mode
            )
            self.stdout.write(
                f"  {list_name:<55.55} {test_name:<45.45} {n:>5} TI(s) in {len(tli_ids):>4} session(s) [{label}]"
            )

        if opts["apply"]:
            return 0  # real numbers reported after mutation

        for tli_id in tis_by_tli:
            # Would the session become fully reviewed once the flagged TIs
            # are skipped? Only if no *other* TI still requires review and
            # the session isn't already reviewed.
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

    def _apply_skips(self, unit, tis, comment_fn):
        """Skip flagged TIs, re-run auto-approval on their sessions."""
        internal_user = get_internal_user()
        already = 0
        to_update = []
        for ti in tis:
            if ti.skipped:
                already += 1
                continue
            ti.skipped = True
            ti.comment = comment_fn(unit, ti)
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
        mode = "constant" if opts["constant_readings"] else "energy"

        self._handle_list_utc_deactivation(opts)

        if opts["constant_readings"]:
            findings = list(
                self._iter_constant_findings(unit_numbers, opts["min_readings"])
            )
        else:
            findings = list(self._iter_findings(unit_numbers))

        if not findings:
            self.stdout.write("No flaggable TestInstances found — nothing to do.")
        else:
            comment_fn = _constant_comment if mode == "constant" else _caps_comment
            total_tis = 0
            total_approved = 0
            for unit, tis in findings:
                self.stdout.write(
                    self.style.MIGRATE_HEADING(
                        f"Unit {unit.number} ({unit.name}): {len(tis)} flaggable TI(s)"
                    )
                )
                if opts["apply"]:
                    n_tis, n_approved = self._apply_skips(unit, tis, comment_fn)
                    total_tis += n_tis
                    total_approved += n_approved
                else:
                    total_approved += self._report(unit, tis, opts, mode)

            if opts["apply"] and opts["deactivate_utis"] and mode == "energy":
                self._deactivate_utis(findings)

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

        if opts["deactivate_utcs"]:
            if not unit_numbers:
                raise CommandError(
                    "--deactivate-utcs requires --units <n,n,...> to name the units."
                )
            if opts["apply"]:
                self._deactivate_utcs(unit_numbers)
            else:
                self._preview_utc_deactivation(unit_numbers)

        if opts["force_close_unreviewed"]:
            if not unit_numbers:
                raise CommandError(
                    "--force-close-unreviewed requires --units <n,n,...> to name the units."
                )
            self._force_close_unreviewed(unit_numbers, opts["apply"])

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

    def _handle_list_utc_deactivation(self, opts):
        """--deactivate-list-utcs: retire every UTC assigned to a TestList."""
        for ref in opts["deactivate_list_utcs"]:
            test_list = TestList.objects.filter(Q(name=ref) | Q(slug=ref)).first()
            if test_list is None:
                raise CommandError(f"No TestList found matching {ref!r}")
            qs = UnitTestCollection.objects.filter(
                content_type_id=self._testlist_content_type_id(),
                object_id=test_list.pk,
                active=True,
            )
            if opts["apply"]:
                n = qs.update(active=False, auto_schedule=False)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deactivated {n} UTC(s) assigned to '{test_list.name}'."
                    )
                )
            else:
                self.stdout.write(
                    f"Would deactivate {qs.count()} UTC(s) assigned to '{test_list.name}' "
                    "(dry run — re-run with --apply)."
                )

    @staticmethod
    def _testlist_content_type_id():
        from django.contrib.contenttypes.models import ContentType

        return ContentType.objects.get_for_model(TestList).pk

    def _deactivate_utis(self, findings):
        total = 0
        for unit, tis in findings:
            test_ids = {ti.unit_test_info.test_id for ti in tis}
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

    def _force_close_unreviewed(self, unit_numbers, apply):
        qs = TestListInstance.objects.filter(
            all_reviewed=False,
            unit_test_collection__unit__number__in=unit_numbers,
        )
        if not apply:
            self.stdout.write(
                f"Would force-close {qs.count()} unreviewed session(s) on unit(s) "
                f"{unit_numbers} (dry run — re-run with --apply)."
            )
            return
        internal_user = get_internal_user()
        now = timezone.now()
        n = qs.update(all_reviewed=True, reviewed=now, reviewed_by=internal_user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Force-closed {n} unreviewed session(s) on unit(s) {unit_numbers} "
                f"(reviewed_by={internal_user.username})."
            )
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
