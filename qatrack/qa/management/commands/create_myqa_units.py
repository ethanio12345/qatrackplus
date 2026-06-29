"""Create QATrack+ Unit rows from the myQA device map (myqa_device_map.yaml)."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from qatrack.myqa_import import LINAC_MAP
from qatrack.units.models import Site, Unit, UnitClass, UnitType

# Maps a unit-number range to (UnitClass name, UnitType name). Drives
# UnitType creation + assignment so each device category is grouped correctly.
# Keys are (low, high) inclusive bounds; first match wins. Ranges adjusted to
# match the corrected LINAC_MAP numbering (avoids existing unit collisions).
UNIT_CATEGORIES = [
    ((1, 9), "Linac", "Treatment LINAC"),
    ((50, 50), "DXR", "Orthovoltage DXR"),
    ((100, 109), "Imaging", "Imaging Device"),
    # 206 must be checked before the 200-212 BCHC range (first match wins)
    ((206, 206), "Brachytherapy", "Brachytherapy Afterloader"),
    ((200, 212), "Ion Chamber", "BCHC Chamber / Electrometer"),
    ((305, 327), "Ion Chamber", "CPMCC Field Ion Chamber"),
    ((340, 344), "Ion Chamber", "Secondary Standard Chamber"),
    ((350, 357), "Ion Chamber", "Reference / Scanning Chamber"),
    ((365, 366), "Well Chamber", "Well Chamber"),
    ((375, 388), "Thermometer", "Thermometer"),
    ((395, 396), "Barometer", "Barometer"),
    ((400, 402), "Electrometer", "Electrometer"),
    ((410, 417), "Survey Meter", "Survey Meter / OSLD / Neutron Detector"),
    ((425, 429), "Detector", "Detector / Phantom"),
    ((435, 441), "Safety", "Audit / Safety / Security"),
]


def _category_for(number: int) -> tuple[str, str]:
    """Return (unit_class_name, unit_type_name) for a unit number."""
    for (low, high), cls_name, type_name in UNIT_CATEGORIES:
        if low <= number <= high:
            return cls_name, type_name
    return "Other", "Unknown Device"


def _site_for(device_name: str) -> tuple[str, str] | None:
    """Derive the (site_slug, site_name) from the device-name prefix.

    Returns None for devices without a known site prefix (LINACs etc.) — the
    command leaves site unset for those so the caller can review.

    Site mapping (verified against existing QATrack+ deployment):
      CPMCC → westmead-equipment, BCHC → blacktown-equipment.
    Non-equipment CPMCC/BCHC items (audits etc.) use the base site.
    """
    primary = device_name[0] if isinstance(device_name, list) else device_name
    if primary.startswith("CPMCC"):
        return "westmead-equipment", "Westmead Equipment"
    if primary.startswith("BCHC"):
        return "blacktown-equipment", "Blacktown Equipment"
    if primary.startswith(("Flexitron", "HDR")):
        return "westmead", "Westmead"
    if primary.startswith(("WSLHD", "RFT", "Source Security", "Radiation Safety")):
        return "westmead", "Westmead"
    if primary in ("Dosimetry Audits", "CPMCC - IAEA Audit"):
        return "westmead", "Westmead"
    return None


def _primary_name(device_name) -> str:
    """Return the display name (first list entry or the string itself)."""
    if isinstance(device_name, list):
        return device_name[0]
    return device_name


class Command(BaseCommand):
    help = (
        "Create QATrack+ Unit records for every device in LINAC_MAP that does "
        "not already exist. Creates missing Site / UnitClass / UnitType records "
        "as needed. Existing units are left unchanged (spec: 'Existing unit not "
        "modified')."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview which units would be created, no DB writes",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        existing_numbers = set(Unit.objects.values_list("number", flat=True))
        created_units = 0
        skipped = 0

        for number in sorted(LINAC_MAP):
            if number in existing_numbers:
                skipped += 1
                continue

            device_name = LINAC_MAP[number]
            name = _primary_name(device_name)
            cls_name, type_name = _category_for(number)
            site_info = _site_for(device_name)

            # Resolve UnitClass + UnitType (get_or_create; tasks 5.3)
            unit_class, _ = UnitClass.objects.get_or_create(name=cls_name)
            unit_type, _ = UnitType.objects.get_or_create(
                name=type_name,
                defaults={"unit_class": unit_class},
            )

            # Resolve Site (get_or_create; task 5.3)
            site = None
            site_label = "None"
            if site_info is not None:
                site_slug, site_name = site_info
                site, _ = Site.objects.get_or_create(
                    slug=site_slug,
                    defaults={"name": site_name},
                )
                site_label = site_name

            if dry_run:
                self.stdout.write(
                    f"  WOULD CREATE unit {number}: {name} ({type_name}, site={site_label})"
                )
                created_units += 1
                continue

            Unit.objects.create(
                number=number,
                name=name,
                type=unit_type,
                site=site,
                date_acceptance=timezone.now().date(),
                active=True,
            )
            self.stdout.write(f"  CREATED unit {number}: {name}")
            created_units += 1

        action = "would create" if dry_run else "created"
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {action} {created_units} units, skipped {skipped} existing"
            )
        )
