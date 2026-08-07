"""Create QATrack+ Unit rows from the myQA device map (myqa_device_map.yaml).

UnitClass / UnitType / Site assignment is driven by myqa_centre_config.yaml
(loaded by qatrack.myqa_import._load_centre_config). Edit that YAML — not
this file — when deploying at a new centre.
"""

import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from qatrack.myqa_import import LINAC_MAP, _load_centre_config
from qatrack.units.models import Site, Unit, UnitClass, UnitType


def _classify_device(device_name: str) -> tuple[str, str]:
    """Return ``(unit_class_name, unit_type_name)`` for a myQA device name.

    Iterates ``centre_config["device_classes"]`` in order; first matching
    ``pattern`` (Python re.search) wins. Falls back to ``("Other",
    "Unknown Device")``.
    """
    primary = device_name[0] if isinstance(device_name, list) else device_name
    cfg = _load_centre_config()
    for rule in cfg.get("device_classes", []):
        if re.search(rule["pattern"], primary):
            return rule["unit_class"], rule["unit_type"]
    return "Other", "Unknown Device"


def _site_for(device_name: str) -> tuple[str, str] | None:
    """Derive ``(site_slug, site_name)`` from the device-name prefix.

    Iterates ``centre_config["sites"]`` in order; first site whose
    ``device_prefixes`` matches (case-sensitive ``str.startswith``) wins.
    Returns None if no site matches — the caller leaves Unit.site unset so
    the assignment can be reviewed manually.
    """
    primary = device_name[0] if isinstance(device_name, list) else device_name
    cfg = _load_centre_config()
    for site in cfg.get("sites", []):
        for prefix in site.get("device_prefixes", []):
            if primary.startswith(prefix):
                return site["slug"], site["name"]
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
        "as needed. Classification rules come from myqa_centre_config.yaml "
        "(edit that file, not this command, when deploying at a new centre). "
        "Existing units are left unchanged."
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
            cls_name, type_name = _classify_device(device_name)
            site_info = _site_for(device_name)

            # Resolve UnitClass + UnitType (get_or_create)
            unit_class, _ = UnitClass.objects.get_or_create(name=cls_name)
            unit_type, _ = UnitType.objects.get_or_create(
                name=type_name,
                defaults={"unit_class": unit_class},
            )

            # Resolve Site (get_or_create)
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
