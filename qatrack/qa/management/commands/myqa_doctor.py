"""Precondition validator for the myQA import system.

Runs a battery of checks covering settings, myQA connectivity, fixtures,
statuses, frequencies, user, categories, device-map integrity, and
dependencies. Exits 0 if all checks pass, exit 1 if any FAIL-severity check
fails. Designed as the first command a new centre runs after ``git clone``.

Inspired by ``manage.py check`` but specific to myQA deployment preconditions.
Each check has a stable integer ID for machine-parseable CI output (``--json``).

Auto-fixable preconditions (the "QATrack+ Internal" user, the "skipped"
status, missing Frequencies, the "Uncategorised" Category) are auto-created
on first run unless ``--no-autofix`` is passed.
"""

import json
import sys
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from qatrack.myqa_import import (
    _CENTRE_CONFIG_PATH,
    _DEVICE_MAP_PATH,
    ensure_frequencies_exist,
    ensure_statuses_exist,
    get_connection,
)
from qatrack.qa.models import AutoReviewRuleSet, Category, Frequency, TestInstanceStatus
from qatrack.qa.utils import get_internal_user
from qatrack.units.models import Unit

# Severity levels
OK = "OK"
FAIL = "FAIL"
WARN = "WARN"
FIXED = "FIXED"


def _check_settings(autofix: bool) -> dict[str, Any]:
    """Check 1: settings.MYQA_DB_* configured."""
    missing = [
        name
        for name in (
            "MYQA_DB_SERVER",
            "MYQA_DB_NAME",
            "MYQA_DB_USERNAME",
            "MYQA_DB_PASSWORD",
        )
        if not getattr(settings, name, None)
    ]
    if missing:
        return {
            "id": 1,
            "name": "settings.MYQA_DB_* configured",
            "status": FAIL,
            "detail": f"Missing: {', '.join(missing)}",
        }
    return {
        "id": 1,
        "name": "settings.MYQA_DB_* configured",
        "status": OK,
        "detail": "",
    }


def _check_connection(autofix: bool) -> dict[str, Any]:
    """Check 2: myQA connection works (SELECT 1, 5s timeout)."""
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        finally:
            conn.close()
    except Exception as e:
        return {
            "id": 2,
            "name": "myQA connection works",
            "status": FAIL,
            "detail": f"Connection failed: {type(e).__name__}: {e}",
        }
    return {"id": 2, "name": "myQA connection works", "status": OK, "detail": ""}


def _check_device_map(autofix: bool) -> dict[str, Any]:
    """Check 3: myqa_device_map.yaml exists with >= 1 entry."""
    import os

    import yaml

    if not os.path.exists(_DEVICE_MAP_PATH):
        return {
            "id": 3,
            "name": "myqa_device_map.yaml exists",
            "status": FAIL,
            "detail": f"Not found at {_DEVICE_MAP_PATH}. Run bootstrap_myqa_centre.",
        }
    try:
        with open(_DEVICE_MAP_PATH) as f:
            data = yaml.safe_load(f)
        n = len(data) if isinstance(data, dict) else 0
        if n == 0:
            return {
                "id": 3,
                "name": "myqa_device_map.yaml has >= 1 entry",
                "status": FAIL,
                "detail": "File exists but contains no entries",
            }
    except Exception as e:
        return {
            "id": 3,
            "name": "myqa_device_map.yaml parses",
            "status": FAIL,
            "detail": f"Parse failed: {e}",
        }
    return {
        "id": 3,
        "name": "myqa_device_map.yaml exists",
        "status": OK,
        "detail": f"{n} device(s) mapped",
    }


def _check_centre_config(autofix: bool) -> dict[str, Any]:
    """Check 4: myqa_centre_config.yaml exists (warn, not fail)."""
    import os

    if not os.path.exists(_CENTRE_CONFIG_PATH):
        return {
            "id": 4,
            "name": "myqa_centre_config.yaml exists",
            "status": WARN,
            "detail": (
                f"Not found at {_CENTRE_CONFIG_PATH}. Using in-code BCHC defaults "
                "with DeprecationWarning. Create the YAML to customise for your centre."
            ),
        }
    return {
        "id": 4,
        "name": "myqa_centre_config.yaml exists",
        "status": OK,
        "detail": "",
    }


def _check_internal_user(autofix: bool) -> dict[str, Any]:
    """Check 5: 'QATrack+ Internal' user exists (autofixable)."""
    exists = User.objects.filter(username="QATrack+ Internal").exists()
    if exists:
        return {
            "id": 5,
            "name": "'QATrack+ Internal' user exists",
            "status": OK,
            "detail": "",
        }
    if not autofix:
        return {
            "id": 5,
            "name": "'QATrack+ Internal' user exists",
            "status": FAIL,
            "detail": "Missing (would auto-create; re-run without --no-autofix)",
        }
    get_internal_user()
    return {
        "id": 5,
        "name": "'QATrack+ Internal' user exists",
        "status": FIXED,
        "detail": "Auto-created 'QATrack+ Internal' user",
    }


def _check_category(autofix: bool) -> dict[str, Any]:
    """Check 6: _default_category() resolves (autofixable)."""
    cat = Category.objects.filter(slug="uncategorised").first()
    if cat is not None:
        return {
            "id": 6,
            "name": "Default Category resolvable",
            "status": OK,
            "detail": "",
        }
    fallback = Category.objects.order_by("id").first()
    if fallback is not None:
        return {
            "id": 6,
            "name": "Default Category resolvable",
            "status": OK,
            "detail": f"Using '{fallback.name}' (no 'uncategorised' slug, will use first)",
        }
    if not autofix:
        return {
            "id": 6,
            "name": "Default Category resolvable",
            "status": FAIL,
            "detail": "No Categories exist (would auto-create 'Uncategorised'; re-run without --no-autofix)",
        }
    Category.objects.create(name="Uncategorised", slug="uncategorised")
    return {
        "id": 6,
        "name": "Default Category resolvable",
        "status": FIXED,
        "detail": "Auto-created 'Uncategorised' Category",
    }


def _check_status(slug: str, check_id: int, autofix: bool) -> dict[str, Any]:
    """Check 7 ('Approved' = FAIL) / 8 ('skipped' = WARN, autofixable)."""
    exists = TestInstanceStatus.objects.filter(slug=slug).exists()
    name_part = f"TestInstanceStatus '{slug}' exists"
    if exists:
        return {"id": check_id, "name": name_part, "status": OK, "detail": ""}
    if slug == "skipped" and autofix:
        ensure_statuses_exist()
        return {
            "id": check_id,
            "name": name_part,
            "status": FIXED,
            "detail": f"Auto-created '{slug}' status",
        }
    severity = FAIL if slug == "Approved" else WARN
    note = (
        ""
        if slug == "Approved"
        else " (would auto-create; re-run without --no-autofix)"
    )
    return {
        "id": check_id,
        "name": name_part,
        "status": severity,
        "detail": f"Missing slug '{slug}'{note}",
    }


def _check_frequencies(autofix: bool) -> dict[str, Any]:
    """Check 9: all required Frequency slugs exist (autofixable)."""
    required = {
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "annual",
        "once_off",
        "other",
    }
    have = set(
        Frequency.objects.filter(slug__in=required).values_list("slug", flat=True)
    )
    missing = required - have
    if not missing:
        return {
            "id": 9,
            "name": "Required Frequencies exist",
            "status": OK,
            "detail": "",
        }
    if not autofix:
        return {
            "id": 9,
            "name": "Required Frequencies exist",
            "status": WARN,
            "detail": f"Missing: {sorted(missing)} (would auto-create; re-run without --no-autofix)",
        }
    ensure_frequencies_exist()
    # ensure_frequencies_exist only creates once_off + other; daily/weekly/etc ship in fixtures
    still_missing = required - set(
        Frequency.objects.filter(slug__in=required).values_list("slug", flat=True)
    )
    if still_missing:
        return {
            "id": 9,
            "name": "Required Frequencies exist",
            "status": WARN,
            "detail": (
                f"Auto-created once_off/other. Still missing: {sorted(still_missing)} "
                "(load the default QATrack+ frequency fixture)"
            ),
        }
    return {
        "id": 9,
        "name": "Required Frequencies exist",
        "status": FIXED,
        "detail": "Auto-created once_off/other Frequencies",
    }


def _check_default_autoreview_ruleset(autofix: bool) -> dict[str, Any]:
    """Check 10: AutoReviewRuleSet with is_default=True exists (fail)."""
    exists = AutoReviewRuleSet.objects.filter(is_default=True).exists()
    if exists:
        return {
            "id": 10,
            "name": "Default AutoReviewRuleSet exists",
            "status": OK,
            "detail": "",
        }
    return {
        "id": 10,
        "name": "Default AutoReviewRuleSet exists",
        "status": FAIL,
        "detail": (
            "No AutoReviewRuleSet with is_default=True. TLIs will not auto-approve. "
            "Create one in admin: /admin/qa/autoreviewruleset/add/"
        ),
    }


def _check_device_map_units(autofix: bool) -> dict[str, Any]:
    """Check 11: every device in myqa_device_map.yaml has a matching Unit (warn)."""
    import os

    import yaml

    if not os.path.exists(_DEVICE_MAP_PATH):
        return {
            "id": 11,
            "name": "Device map Units exist",
            "status": WARN,
            "detail": "device map not found — run bootstrap_myqa_centre --apply first",
        }
    try:
        with open(_DEVICE_MAP_PATH) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {
                "id": 11,
                "name": "Device map Units exist",
                "status": FAIL,
                "detail": (
                    f"device map at {_DEVICE_MAP_PATH} did not parse to a dict "
                    f"(got {type(data).__name__})"
                ),
            }
        mapped_numbers = {int(k) for k in data.keys()}
    except (ValueError, TypeError) as e:
        return {
            "id": 11,
            "name": "Device map Units exist",
            "status": FAIL,
            "detail": f"device map has non-integer key(s): {e}",
        }
    except Exception as e:
        return {
            "id": 11,
            "name": "Device map Units exist",
            "status": FAIL,
            "detail": f"failed to parse device map: {e}",
        }
    have_numbers = set(
        Unit.objects.filter(number__in=mapped_numbers).values_list("number", flat=True)
    )
    missing = sorted(mapped_numbers - have_numbers)
    if not missing:
        return {"id": 11, "name": "Device map Units exist", "status": OK, "detail": ""}
    return {
        "id": 11,
        "name": "Device map Units exist",
        "status": WARN,
        "detail": (
            f"{len(missing)} mapped unit number(s) have no Unit row: {missing[:10]}"
            + (" ..." if len(missing) > 10 else "")
            + ". Run bootstrap_myqa_centre --apply or create_myqa_units."
        ),
    }


def _check_croniter(autofix: bool) -> dict[str, Any]:
    """Check 12: croniter installed (required for Schedule cron)."""
    try:
        import croniter  # noqa: F401
    except ImportError:
        return {
            "id": 12,
            "name": "croniter installed",
            "status": FAIL,
            "detail": "Install with: uv add croniter (required by django-q2 cron schedules)",
        }
    return {"id": 12, "name": "croniter installed", "status": OK, "detail": ""}


# Ordered list of checks (stable IDs; new checks append at end with new IDs)
_CHECKS = [
    _check_settings,
    _check_connection,
    _check_device_map,
    _check_centre_config,
    _check_internal_user,
    _check_category,
    lambda autofix: _check_status("Approved", 7, autofix),
    lambda autofix: _check_status("skipped", 8, autofix),
    _check_frequencies,
    _check_default_autoreview_ruleset,
    _check_device_map_units,
    _check_croniter,
]


class Command(BaseCommand):
    help = (
        "Validate myQA import preconditions. 12 checks covering settings, "
        "connection, fixtures, statuses, frequencies, user, categories, "
        "device-map integrity, and dependencies. Exits 1 if any FAIL check."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-autofix",
            action="store_true",
            default=False,
            help="Preview only; do not auto-create missing users/statuses/frequencies",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Emit JSON for CI integration",
        )

    def handle(self, *args, **options):
        autofix = not options["no_autofix"]
        as_json = options["json"]

        results = [check(autofix) for check in _CHECKS]

        if as_json:
            has_fail = any(r["status"] == FAIL for r in results)
            payload = {"checks": results, "exit_code": 1 if has_fail else 0}
            self.stdout.write(json.dumps(payload, indent=2))
            sys.exit(payload["exit_code"])

        # Human-readable
        for r in results:
            label = {
                OK: self.style.SUCCESS(f"[{OK}]"),
                FAIL: self.style.ERROR(f"[{FAIL}]"),
                WARN: self.style.WARNING(f"[{WARN}]"),
                FIXED: self.style.SUCCESS(f"[{FIXED}]"),
            }[r["status"]]
            detail = f" — {r['detail']}" if r["detail"] else ""
            self.stdout.write(f"  {label} #{r['id']:>2} {r['name']}{detail}")

        n_fail = sum(1 for r in results if r["status"] == FAIL)
        n_warn = sum(1 for r in results if r["status"] == WARN)
        n_fixed = sum(1 for r in results if r["status"] == FIXED)
        n_ok = sum(1 for r in results if r["status"] == OK)

        self.stdout.write("")
        summary = f"{n_ok} OK, {n_fixed} fixed, {n_warn} warnings, {n_fail} failures"
        if n_fail:
            self.stdout.write(self.style.ERROR(f"✗ {summary} (exit 1)"))
            sys.exit(1)
        elif n_warn:
            self.stdout.write(self.style.WARNING(f"⚠ {summary} (exit 0)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"✓ {summary} (exit 0)"))
