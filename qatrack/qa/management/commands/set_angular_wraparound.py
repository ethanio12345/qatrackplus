"""Convert angular/rotational Tests to the wraparound type and re-evaluate.

Angular quantities (gantry/collimator/couch/table angle indicators, rotation
accuracy, etc.) are circular: 0.1° and 359.9° are only 0.2° apart. QATrack+
already supports this via ``Test.type == 'wraparound'`` with ``wrap_low``/
``wrap_high`` bounds (``difference_wraparound``), but in this instance every
angular test is ``type='simple'``, so differences are computed linearly
(0.1 vs 359.9 = 359.8°).

This command selects the angular tests (curated name patterns, wedge and
non-angle measurements excluded), sets ``type='wraparound'`` with
``wrap_low=0`` / ``wrap_high=360``, and re-evaluates ``pass_fail`` on all their
TestInstances so the stored status reflects the wrapped difference.

``--dry-run`` (default) previews; ``--apply`` executes. Idempotent.
"""

import re

from django.core.management.base import BaseCommand

from qatrack.qa.models import WRAPAROUND, Test, TestInstance

# Name patterns whose VALUE is an angle (degrees, 0-360).
INCLUDE = re.compile(
    r"angle (indicator|sensor|accuracy)|rotation accuracy|table angle|"
    r"couch angle|gantry angle|collimator angle|gantry =|true zero",
    re.I,
)
# Non-angle measurements that mention rotation/angle contextually, plus wedge.
EXCLUDE = re.compile(
    r"wedge|symmetry|flatness|output|constancy|stability|vs\.|with gantry|"
    r"induced|shift|enhanced|beam|deviation|isocen|position|offset|skew|"
    r"displacement|relative to b0|level",
    re.I,
)
# Negative-angle conventions (e.g. "Table angle -45°") don't fit [0, 360].
NEGATIVE = re.compile(r"-\s*\d+\s*°|-\s*\d+\s*deg", re.I)


def select_angular_tests():
    qs = Test.objects.filter(type="simple")
    out = []
    for t in qs:
        if not INCLUDE.search(t.name):
            continue
        if EXCLUDE.search(t.name) or NEGATIVE.search(t.name):
            continue
        out.append(t)
    return out


class Command(BaseCommand):
    help = (
        "Set angular/rotational Tests to wraparound (0-360) and re-evaluate pass_fail."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Apply (default: dry run).",
        )

    def handle(self, *args, **opts):
        tests = select_angular_tests()
        if not tests:
            self.stdout.write("No angular tests matched.")
            return

        # Affected TestInstances (have a numeric value)
        test_ids = [t.pk for t in tests]
        tis = TestInstance.objects.filter(unit_test_info__test__in=test_ids).filter(
            value__isnull=False
        )

        # Count TIs whose |value-ref|>180 (the ones currently mis-displayed).
        boundary_pks = []
        for ti in tis.filter(reference__isnull=False).select_related("reference"):
            try:
                if abs(float(ti.value) - float(ti.reference.value)) > 180:
                    boundary_pks.append(ti.pk)
            except (TypeError, ValueError):
                pass

        self.stdout.write(
            "Angular tests to convert: %d  |  TestInstances to re-evaluate: %d  |  "
            "TIs crossing 0/360 boundary: %d"
            % (len(tests), tis.count(), len(boundary_pks))
        )
        for t in sorted(tests, key=lambda x: x.name):
            self.stdout.write("  %-58s (id=%s)" % (t.name[:56], t.pk))

        if not opts["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run — no changes. Re-run with --apply to convert."
                )
            )
            return

        # 1. Flip the tests to wraparound.
        n_tests = Test.objects.filter(pk__in=test_ids).update(
            type=WRAPAROUND, wrap_low=0, wrap_high=360
        )
        self.stdout.write(
            self.style.SUCCESS("Converted %d Test(s) to wraparound [0, 360]." % n_tests)
        )

        # 2. Re-evaluate pass_fail on their numeric TestInstances.
        n_tis = 0
        for ti in TestInstance.objects.filter(
            unit_test_info__test__in=test_ids, value__isnull=False
        ).select_related(
            "unit_test_info__test", "reference", "tolerance", "test_list_instance"
        ):
            ti.calculate_pass_fail()
            ti.save(update_fields=["pass_fail"])
            n_tis += 1
        self.stdout.write(
            self.style.SUCCESS("Re-evaluated pass_fail on %d TestInstance(s)." % n_tis)
        )
