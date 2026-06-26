"""Dynamic myQA import engine.

This module implements the TaskName-driven discovery and import system that
replaces the previous hardcoded importer-class architecture (24+ classes with
broad ``task_name_patterns``). The new model:

* One TestList per myQA TaskName (242 tasks), named verbatim from myQA.
* Tests named by myQA condition name, shared across TestLists via
  :class:`~qatrack.qa.models.TestListMembership`. Slugs are bare
  ``slugify(condition_name)`` (no list prefix).
* Each myQA session is read across ALL execution types present (Numeric,
  PassFail, Profile, Wedge, Energy, Output, MLC, CBCT, Planar, VMAT,
  Winston-Lutz) and the results are merged into a single TestListInstance.
* Tolerances are NOT set during setup — shared tests cannot have conflicting
  tolerances across tasks. Users configure per-unit tolerances through the
  QATrack+ admin after setup.

See ``openspec/changes/myqa-dynamic-taskname-import/`` for the full design.
"""

import json
import os
import re
from typing import Any

import pymssql
import yaml
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from qatrack.qa.models import (
    Reference,
    Test,
    TestInstance,
    TestInstanceStatus,
    TestList,
    TestListInstance,
    Tolerance,
    UnitTestCollection,
    UnitTestInfo,
)

MYQA_DB_SETTINGS = {
    "server": settings.MYQA_DB_SERVER,
    "database": settings.MYQA_DB_NAME,
    "username": settings.MYQA_DB_USERNAME,
    "password": settings.MYQA_DB_PASSWORD,
}

# Maps QATrack+ unit numbers to myQA RadiationDeviceName strings. Values are
# verified against the production myQA database. Devices renamed over time use
# a list so all name variants map to the same unit.
#
# The mapping is loaded from myqa_device_map.yaml at import time.
_DEVICE_MAP_PATH = os.path.join(
    os.path.dirname(__file__), "qa", "management", "commands", "myqa_device_map.yaml"
)


def _load_device_map() -> dict[int, str | list[str]]:
    with open(_DEVICE_MAP_PATH) as f:
        data = yaml.safe_load(f)
    return {int(k): v for k, v in data.items()}


LINAC_MAP = _load_device_map()


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def get_connection():
    """Open a pymssql connection to the myQA database."""
    return pymssql.connect(
        server=MYQA_DB_SETTINGS["server"],
        database=MYQA_DB_SETTINGS["database"],
        user=MYQA_DB_SETTINGS["username"],
        password=MYQA_DB_SETTINGS["password"],
    )


def _fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    """Execute a dict-cursor query and return all rows."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(sql, params)
    return cursor.fetchall()


def _result(
    value, expected=None, warn=None, fail=None, relative=False, round_to=4
) -> dict[str, Any]:
    """Build a standardized extractor result dict with value cleanup."""
    if round_to and isinstance(value, (int, float)) and not isinstance(value, bool):
        value = round(value, round_to)
    return {
        "value": value,
        "expected": expected,
        "warn": warn,
        "fail": fail,
        "relative": relative,
    }


# Django Test.name max_length — used by truncation in _energy_prefixed.
_TEST_NAME_MAX_LEN = 128


def build_device_to_unit_map() -> dict[str, int]:
    """Reverse LINAC_MAP: myQA RadiationDeviceName -> QATrack+ unit number."""
    mapping: dict[str, int] = {}
    for unit_num, names in LINAC_MAP.items():
        if isinstance(names, str):
            names = [names]
        for n in names:
            mapping[n] = unit_num
    return mapping


# ---------------------------------------------------------------------------
# Slug / name helpers
# ---------------------------------------------------------------------------


def slugify_name(name: str) -> str:
    """Slugify a condition/test name with NO list prefix.

    Same condition name across different tasks produces the same slug, so the
    Test object is shared via TestListMembership (specs/dynamic-taskname-
    discovery R3). Disambiguation of duplicates within a single task happens
    in setup_myqa_tests via ``_2`` / ``_3`` suffixes.
    """
    slug = (name or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_")


def clean_roi_name(name: str) -> str:
    """Strip leading/trailing brackets from a VMAT ROI name.

    VMAT ROI rows have ``Name`` like ``[2.0 cm/s]`` — the brackets are myQA
    display decoration.
    """
    return (name or "").strip("[]")


# ---------------------------------------------------------------------------
# Name enrichment (descriptive-test-names)
# ---------------------------------------------------------------------------

# Conservative abbreviation table. Word-boundary matched so that ``SN`` inside
# ``SNC`` is NOT expanded. Standard physics terms (MU, FFF, NDwQ, TPR, RAKR,
# Dmax, kQQ) are intentionally absent — they must remain untouched.
_ABBREVIATIONS: dict[str, str] = {
    "Vrt": "Vertical",
    "Lng": "Longitudinal",
    "Lat": "Lateral",
    "SN": "Serial Number",
}

# Pre-compiled regex: matches any abbreviation key at a word boundary.
_ABBR_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _ABBREVIATIONS) + r")\b")

_NUMBER_PREFIX_RE = re.compile(r"^\d+\.\s*")

_OVERRIDE_PATH = os.path.join(
    os.path.dirname(__file__),
    "qa",
    "management",
    "commands",
    "myqa_name_overrides.yaml",
)


def load_name_overrides() -> dict[tuple[str, str], str]:
    """Load the YAML override file for myQA test names.

    Returns a ``{(taskname, condition_name): descriptive_name}`` dict. The
    special taskname ``"*"`` applies an override to all TaskNames. Returns
    ``{}`` if the file is absent or empty.
    """
    if not os.path.exists(_OVERRIDE_PATH):
        return {}
    with open(_OVERRIDE_PATH) as f:
        data = yaml.safe_load(f) or {}
    flat: dict[tuple[str, str], str] = {}
    for taskname, conditions in data.items():
        if not isinstance(conditions, dict):
            continue
        for cond_name, desc_name in conditions.items():
            flat[(taskname, cond_name)] = desc_name
    return flat


def enrich_test_name(
    condition_name: str,
    taskname: str,
    overrides: dict[tuple[str, str], str] | None = None,
) -> str:
    """Apply enrichment rules to produce a descriptive Test display name.

    Rules applied in order:
    1. Strip leading sequence-number prefix (``01. ``, ``00. ``, etc.).
    2. Expand word-boundary abbreviations (Vrt→Vertical, Lng→Longitudinal,
       Lat→Lateral, SN→Serial Number).
    3. Apply YAML override if one matches (specific taskname, then wildcard
       ``*``). An override replaces the result of rules 1+2 entirely.

    The slug is NOT computed here — callers must derive it from the raw name
    via :func:`slugify_name` so that enrichment doesn't break FK references.
    """
    name = condition_name or ""

    # 1. Strip sequence-number prefix.
    name = _NUMBER_PREFIX_RE.sub("", name)

    # 2. Expand abbreviations at word boundaries.
    name = _ABBR_RE.sub(lambda m: _ABBREVIATIONS[m.group(1)], name)

    # 3. Apply override (specific taskname first, then wildcard "*").
    if overrides:
        override = overrides.get((taskname, condition_name))
        if override is None:
            override = overrides.get(("*", condition_name))
        if override is not None:
            name = override

    return name


# ---------------------------------------------------------------------------
# State mapping (myQA execution states → QATrack+ import behaviour)
# ---------------------------------------------------------------------------

# myQA State enum (from MQA_TestExecutions.State):
#   10 = Not started  → skip import (no TestInstance)
#   30 = In progress  → import if value present, status = Unreviewed
#   40 = Completed    → import normally, status = Approved
#   50 = Flagged/overridden → import, status = Approved (values may still pass)
#   60 = Skipped/NA   → import with value, status = Skipped
# Pass/fail is determined by comparing the value against myQA tolerances,
# NOT by the myQA workflow state.
MYQA_STATE_MAP: dict[int, str] = {
    10: "skip",
    30: "unreviewed",
    40: "approved",
    50: "approved",
    60: "skipped",
}


def ensure_statuses_exist():
    """Create the ``Skipped`` TestInstanceStatus if it doesn't exist.

    Used for myQA State=60 tests that were intentionally skipped / N/A.
    ``valid=False`` so they don't count towards completion metrics.
    ``requires_review=False`` so they don't appear in the unreviewed queue.
    Idempotent — safe to call on every setup run.
    """
    TestInstanceStatus.objects.get_or_create(
        slug="skipped",
        defaults={
            "name": "Skipped",
            "description": "Test was skipped or not applicable in myQA (State=60).",
            "is_default": False,
            "requires_review": False,
            "valid": False,
            "export_by_default": False,
        },
    )


# ---------------------------------------------------------------------------
# Frequency inference (design D6)
# ---------------------------------------------------------------------------

# Frequency codes appear in the dotted path as a single capital letter, e.g.
# "5.Tmt.Linac.D" (daily) or "5.Tmt.Linac.M.Dosimetry" (monthly — the M is the
# frequency code, "Dosimetry" is a longer segment that must NOT match). The
# pattern "\.X(?:[^a-z]|$)" matches ".X" only when X is followed by a non-
# lowercase-letter (digit, space, dot, dash) or end-of-string, so ".d" in
# ".dosimetry" is correctly rejected.
_FREQ_DAILY = re.compile(r"\.d(?:[^a-z]|$)")
_FREQ_WEEKLY = re.compile(r"\.w(?:[^a-z]|$)")
_FREQ_MONTHLY = re.compile(r"\.m(?:[^a-z]|$)")
_FREQ_QUARTERLY = re.compile(r"\.q(?:[^a-z]|$)")
_FREQ_ANNUAL = re.compile(r"\.y(?:[^a-z]|$)")
_FREQ_6MONTHLY = re.compile(r"\.6m(?:[^a-z]|$)")
_FREQ_COMMISSIONING = re.compile(r"\.c(?:[^a-z]|$)")


def infer_frequency(taskname: str) -> str:
    """Infer the QATrack+ Frequency slug from a TaskName's naming convention.

    Returns one of: ``daily``, ``weekly``, ``monthly``, ``quarterly``,
    ``semi-annual`` (biannual / 6-monthly), ``annual``, ``once_off``
    (commissioning), or ``other`` (unknown / unrecognised). The ``once_off``
    and ``other`` Frequencies are created on demand by
    :func:`ensure_frequencies_exist`.
    """
    tn = (taskname or "").lower()

    # Commissioning -> once_off (one-time commissioning QA).
    if _FREQ_COMMISSIONING.search(tn) or "commissioning" in tn:
        return "once_off"
    # 6-monthly -> semi-annual (biannual; the existing biannual frequency).
    if (
        _FREQ_6MONTHLY.search(tn)
        or "6 monthly" in tn
        or "6-monthly" in tn
        or "biannual" in tn
    ):
        return "semi-annual"
    # Daily (.D, .D2, .D%, or the word "Daily")
    if _FREQ_DAILY.search(tn) or "daily" in tn:
        return "daily"
    # Weekly
    if _FREQ_WEEKLY.search(tn) or "weekly" in tn:
        return "weekly"
    # Quarterly
    if _FREQ_QUARTERLY.search(tn) or "quarterly" in tn:
        return "quarterly"
    # Annual / yearly
    if _FREQ_ANNUAL.search(tn) or "annual" in tn or "yearly" in tn:
        return "annual"
    # Monthly (checked after the more-specific patterns above so that e.g.
    # ".D2" doesn't accidentally match the daily branch and skip monthly)
    if _FREQ_MONTHLY.search(tn) or "monthly" in tn:
        return "monthly"
    # Unrecognised TaskName -> "other" (catch-all; user reassigns in admin).
    return "other"


def ensure_frequencies_exist():
    """Create the ``once_off`` and ``other`` Frequencies if they don't exist.

    These two are not part of the default QATrack+ frequency set (which only
    ships daily/weekly/fortnightly/monthly/quarterly/semi-annual/annual) but
    are needed by :func:`infer_frequency` for commissioning (.C) TaskNames and
    unrecognised TaskNames. Idempotent — safe to call on every setup run.

    ``nominal_interval`` is required by the model (PositiveIntegerField, NOT
    NULL) but is normally derived from the ``recurrences`` rule via
    ``calc_nominal_interval``. For these special Frequencies we set it
    directly to a high value (so they sort last in admin / overview views)
    and provide an empty recurrence so no due-date scheduling fires.
    """
    from qatrack.qa.models import Frequency

    defaults = [
        # once_off: effectively never recurs. High nominal_interval so it
        # sorts below all real frequencies in lists. window_end wide enough
        # that a once-off task never appears "overdue" immediately.
        {
            "slug": "once_off",
            "name": "Once Off",
            "nominal_interval": 36500,  # ~100 years
            "window_end": 365,
        },
        # other: catch-all for unrecognised TaskNames. User reassigns to the
        # correct frequency through the admin after setup.
        {
            "slug": "other",
            "name": "Other",
            "nominal_interval": 366,  # just above annual so it sorts last
            "window_end": 30,
        },
    ]
    for d in defaults:
        Frequency.objects.get_or_create(
            slug=d["slug"],
            defaults={
                "name": d["name"],
                "nominal_interval": d["nominal_interval"],
                "window_end": d["window_end"],
            },
        )


# ---------------------------------------------------------------------------
# Discovery: TaskNames + their conditions
# ---------------------------------------------------------------------------


def discover_tasknames(conn) -> list[str]:
    """Return all distinct TaskNames from myQA (specs R1).

    Queries ``SELECT DISTINCT TaskName FROM MQA_TestExecutions WHERE TaskName
    IS NOT NULL``. Result is sorted for deterministic setup ordering.
    """
    return [
        row["TaskName"]
        for row in _fetchall(
            conn,
            """
            SELECT DISTINCT TaskName
            FROM MQA_TestExecutions
            WHERE TaskName IS NOT NULL
            ORDER BY TaskName
            """,
        )
    ]


def discover_task_protocol(conn, taskname: str) -> str:
    """Return the protocol name for a TaskName from myQA.

    The protocol name describes the overall QA protocol/template that the
    task follows (e.g. ``"TG-142 + PlugIn (template ver. 2020-002)"``).
    Returns empty string if no protocol is found.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT TOP 1 te.ProtocolName
        FROM MQA_TestExecutions te
        WHERE te.TaskName = %s AND te.ProtocolName IS NOT NULL
        """,
        (taskname,),
    )
    row = cursor.fetchone()
    return (row["ProtocolName"] or "").strip() if row else ""


def discover_units_for_taskname(conn, taskname: str) -> list[int]:
    """Return QATrack+ unit numbers that have execution data for ``taskname``.

    Used during setup to create UTCs / UTIs only for units that actually have
    data (specs/dynamic-taskname-discovery R7). Unknown devices (not in
    LINAC_MAP) are skipped.
    """
    device_to_unit = build_device_to_unit_map()
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT te.RadiationDeviceName
        FROM MQA_TestExecutions te
        WHERE te.TaskName = %s
          AND te.RadiationDeviceName IS NOT NULL
        """,
        (taskname,),
    )
    units: set[int] = set()
    for row in cursor.fetchall():
        unit_num = device_to_unit.get(row["RadiationDeviceName"])
        if unit_num is not None:
            units.add(unit_num)
    return sorted(units)


def discover_conditions(conn, taskname: str) -> list[dict[str, Any]]:
    """Return all distinct conditions for a TaskName across all exec types.

    Returns a list of ``{"name": str, "type": "simple" | "string"}`` dicts.
    Conditions are gathered from every specialized extractor that has data for
    this TaskName (specs/dynamic-taskname-discovery R3, multi-type-session-
    import R5).
    """
    conditions: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _add(name: str, ctype: str = "simple", source: str = "") -> None:
        if not name:
            return
        if name in seen_names:
            return
        seen_names.add(name)
        conditions.append({"name": name, "type": ctype, "source": source})

    for label, fn, ctype in _DISCOVERERS:
        for name in fn(conn, taskname):
            _add(name, ctype, label)

    return conditions


def discover_condition_metadata(conn, taskname: str) -> dict[str, dict[str, Any]]:
    """Fetch test step descriptions, categories, and tolerance references for
    conditions in a TaskName.

    Joins Numeric conditions through to their parent TestExecution to get the
    description / category / test step name, plus the tolerance reference values
    (Expected, WarnOn, FailOn) from the condition execution.

    Returns ``{condition_name: {"test_step": str, "description": str,
    "category": str, "expected": float|None, "warn_on": float|None,
    "fail_on": float|None}}``.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT tcne.Name AS condition_name,
               te.Name AS test_step,
               te.Description AS description,
               te.Category AS category,
               tcne.Expected AS expected,
               tcne.WarnOn AS warn_on,
               tcne.FailOn AS fail_on
        FROM MQA_Numeric_TestConditionExecutions tcne
        JOIN MQA_TestImplementationExecutions tie
            ON tcne.NumericTestExecution_Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND tcne.Name IS NOT NULL
        """,
        (taskname,),
    )
    result: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall():
        name = row["condition_name"]
        desc = (row.get("description") or "").strip()
        # Prefer rows with non-empty descriptions; keep first otherwise.
        if name not in result or (desc and not result[name]["description"]):
            result[name] = {
                "test_step": (row.get("test_step") or "").strip(),
                "description": desc,
                "category": (row.get("category") or "").strip(),
                "expected": row.get("expected"),
                "warn_on": row.get("warn_on"),
                "fail_on": row.get("fail_on"),
            }
    return result


# ---------------------------------------------------------------------------
# Per-type discovery helpers (condition names per TaskName)
# ---------------------------------------------------------------------------


def discover_numeric_conditions(conn, taskname: str) -> list[str]:
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT tcne.Name, te.Name AS test_step
        FROM MQA_Numeric_TestConditionExecutions tcne
        JOIN MQA_TestImplementationExecutions tie
            ON tcne.NumericTestExecution_Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND tcne.Name IS NOT NULL AND te.State != 10
        ORDER BY tcne.Name
        """,
        (taskname,),
    )
    rows = cursor.fetchall()
    # When multiple test steps (energies) produce the same condition names,
    # prefix with the energy code parsed from the test step name.
    test_steps = {r["test_step"] for r in rows if r["test_step"]}
    multi = len(test_steps) > 1
    seen: set[str] = set()
    result: list[str] = []
    for r in rows:
        name = _energy_prefixed(r["Name"], r["test_step"], multi)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _energy_prefixed(condition: str, test_step: str | None, multi: bool) -> str:
    """Prefix condition name with energy code when multiple test steps exist.

    For test steps like ``"6MV_6 MV_200x200 mm_100 MU"`` the first token
    (``6MV``) is used. For descriptive test steps without ``_`` separators,
    falls back to ``_test_step_prefix``. Result is truncated to keep total
    name under 128 chars.
    """
    if not multi or not test_step:
        return condition
    energy = test_step.split("_")[0]
    # If the "energy" token is too long, it's a descriptive name — use
    # _test_step_prefix instead for a cleaner, shorter prefix.
    if len(energy) > 20:
        energy = _test_step_prefix(test_step)
    name = f"{energy} {condition}" if energy else condition
    # Safety: truncate to fit Test.name max_length (128 chars).
    if len(name) > _TEST_NAME_MAX_LEN:
        name = name[:125] + "..."
    return name


def discover_passfail_conditions(conn, taskname: str) -> list[str]:
    """Return per-test PassFail condition names (TestExecution Names).

    Each PassFail test execution becomes a separate condition, replacing the
    old single "Acceptance Criteria" approach. State=10 tests are excluded.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT te.Name
        FROM MQA_PassFail_TestExecutions pfte
        JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND te.Name IS NOT NULL AND te.State != 10
        ORDER BY te.Name
        """,
        (taskname,),
    )
    return [row["Name"] for row in cursor.fetchall()]


def _profile_condition_name(
    display_name: str, profile_direction: int | None, test_step: str | None, multi: bool
) -> str:
    """Build a unique condition name for a Profile result.

    Appends ``(crossline)`` / ``(inline)`` based on ProfileDirection when
    the DisplayName doesn't already contain direction info. Prefixes with
    test step descriptor when multiple test steps exist.
    """
    _DIR_MAP = {1: "crossline", 2: "inline"}
    dir_name = _DIR_MAP.get(profile_direction or 0, "")
    if dir_name and dir_name not in display_name.lower():
        name = f"{display_name} ({dir_name})"
    else:
        name = display_name
    if multi and test_step:
        prefix = _test_step_prefix(test_step)
        if prefix:
            name = f"{prefix} {name}"
    return name


def discover_profile_conditions(conn, taskname: str) -> list[str]:
    """Profile results have a DisplayName column + ProfileDirection + test step.

    Direction is appended when not already in the name. Energy prefix is added
    when multiple test steps exist.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT dpr.DisplayName, dpr.ProfileDirection, te.Name AS test_step
        FROM MQA_Dosimetry_Profile_Results dpr
        JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
            ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
        JOIN MQA_Dosimetry_Profile_TestExecutions dpte
            ON dpqie.Id = dpte.ProfileQueueItem_Id
        JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND dpr.DisplayName IS NOT NULL
        """,
        (taskname,),
    )
    rows = cursor.fetchall()
    test_steps = {r["test_step"] for r in rows if r["test_step"]}
    multi = len(test_steps) > 1
    seen: set[str] = set()
    result: list[str] = []
    for r in rows:
        name = _profile_condition_name(
            r["DisplayName"], r.get("ProfileDirection"), r["test_step"], multi
        )
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def discover_wedge_conditions(conn, taskname: str) -> list[str]:
    """Wedge has no DisplayName column — derive a name per distinct energy.

    Returns ``Wedge Constancy {energy}x`` so the same measurement across
    sessions produces the same condition name (shared Test).
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT wte.BeamQuality_EnergyValue
        FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
        JOIN MQA_Dosimetry_Wedge_TestExecutions wte
            ON wqie.WedgeConstancyExecution_Id = wte.Id
        JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND wte.BeamQuality_EnergyValue IS NOT NULL
        ORDER BY wte.BeamQuality_EnergyValue
        """,
        (taskname,),
    )
    return [
        f"Wedge Constancy {int(row['BeamQuality_EnergyValue'])}x"
        for row in cursor.fetchall()
    ]


def discover_output_conditions(conn, taskname: str) -> list[str]:
    """Output dosimetry has no DisplayName — derive per distinct energy.

    Returns ``Output {energy}x`` so the same measurement produces the same
    condition name across sessions.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT cqie.BeamQuality_EnergyValue
        FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
        JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON oqie.Id = cqie.Id
        JOIN MQA_Dosimetry_Output_TestExecutions ote
            ON oqie.OutputConstancyExecution_Id = ote.Id
        JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
        ORDER BY cqie.BeamQuality_EnergyValue
        """,
        (taskname,),
    )
    return [
        f"Output {int(row['BeamQuality_EnergyValue'])}x" for row in cursor.fetchall()
    ]


def discover_energy_conditions(conn, taskname: str) -> list[str]:
    """Energy chamber measurements keyed by (energy, fff, chamber).

    Returns ``Energy {energy}{fff?} ch{chamber}`` for each distinct combo.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT cqie.BeamQuality_EnergyValue,
                        cqie.BeamQuality_IsFlatteningFilterFree,
                        ece.ChamberNumber
        FROM MQA_Dosimetry_Energy_ChamberExecutions ece
        JOIN MQA_Dosimetry_Energy_QueueItemExecutions eqie
            ON ece.EnergyConstancyQueueItemExecution_Id = eqie.Id
        JOIN MQA_Dosimetry_Energy_TestExecutions ete ON eqie.EnergyConstancyExecution_Id = ete.Id
        JOIN MQA_TestImplementationExecutions tie ON ete.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON eqie.Id = cqie.Id
        WHERE te.TaskName = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
        ORDER BY cqie.BeamQuality_EnergyValue, ece.ChamberNumber
        """,
        (taskname,),
    )
    names: list[str] = []
    for row in cursor.fetchall():
        energy = int(round(row["BeamQuality_EnergyValue"] or 0))
        fff = "fff" if row.get("BeamQuality_IsFlatteningFilterFree") else ""
        chamber = int(row.get("ChamberNumber") or 1)
        names.append(f"Energy {energy}{fff} ch{chamber}")
    return names


# Pattern B (denormalized wide-row) column-prefix maps. Each entry maps a
# human-readable condition name to the SQL column whose value to read. Used
# by both discover_* and extract_* for the same types so slugs match.
_MLC_METRICS = {
    "Failing Peaks": "FailingPeaks_Result_Value_Value",
    "Maximum Deviation": "MaximumDeviation_Result_Value_Value",
    "Interstrip Ratio": "InterstripRatio_Result_Value_Value",
    "Standard Deviation": "StandardDeviation_Result_Value_Value",
    "Isocenter To Strip Distance": "IsocenterToStripDistance_Result_Value_Value",
}
_MLC_VALUE_ONLY = {"Total Peaks": "TotalPeaks"}
_MLC_STRING = {"Leaves That Failed": "LeavesThatFailed"}

_CBCT_METRICS = {
    "Scaling Discrepancy": "ScalingDiscrepancy_Result_Value_Value",
    "Geometric Distortion": "GeometricDistortion_Result_Value_Value",
    "Spatial Resolution": "SpatialResolution_Result_Value_Value",
    "Overall Uniformity": "OverallUniformity_Result_Value_Value",
    "Minimum Uniformity": "MinimumUniformity_Result_Value_Value",
    "Contrast": "Contrast_Result_Value_Value",
    "CNR": "CNR_Result_Value_Value",
    "Max Hu Deviation": "MaxHuDeviation_Result_Value_Value",
    "Measured Slice Width": "MeasuredSliceWidth_Result_Value_Value",
}
_CBCT_VALUE_ONLY = {"Slice Width Difference": "SliceWidthDifference_Value"}

_PLANAR_METRICS = {
    "Scaling Discrepancy": "ScalingDiscrepancy_Result_Value_Value",
    "Spatial Resolution": "SpatialResolution_Result_Value_Value",
    "Minimum Uniformity": "MinimumUniformity_Result_Value_Value",
    "Contrast": "Contrast_Result_Value_Value",
    "CNR": "CNR_Result_Value_Value",
    "X Offset": "XOffset_Result_Value_Value",
    "Y Offset": "YOffset_Result_Value_Value",
}

_VMAT_PARENT_NAME = "Normalization Value"


def _test_step_prefix(test_step: str | None) -> str:
    """Extract a short prefix from a test step name for condition disambiguation.

    e.g. ``"5.Tmt.Linac.M.VMAT.06 - Leaf Positional Accuracy"`` → ``"Leaf Positional Accuracy"``
    """
    if not test_step:
        return ""
    if " - " in test_step:
        return test_step.rsplit(" - ", 1)[-1].strip()
    return test_step.strip()


def _discover_pattern_b_conditions(
    conn,
    taskname: str,
    *,
    metrics: dict,
    value_only: dict | None = None,
    string_cols: dict | None = None,
    results_table: str,
    exec_table: str,
    exec_alias: str,
    join_col: str,
) -> list[str]:
    """Discovery for Pattern B types. Returns condition names, prefixed with
    test step name when multiple test steps exist in the data.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        f"""
        SELECT DISTINCT te.Name AS test_step
        FROM {results_table} r
        JOIN {exec_table} {exec_alias} ON r.{join_col} = {exec_alias}.Id
        JOIN MQA_TestImplementationExecutions tie ON {exec_alias}.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
        """,
        (taskname,),
    )
    test_steps = [row["test_step"] for row in cursor.fetchall() if row["test_step"]]
    if not test_steps:
        return []  # No data for this TaskName — don't add spurious conditions
    multi = len(set(test_steps)) > 1

    names = list(metrics.keys())
    if value_only:
        names.extend(value_only.keys())
    if string_cols:
        names.extend(string_cols.keys())

    if multi:
        prefixed: list[str] = []
        for ts in set(test_steps):
            prefix = _test_step_prefix(ts)
            for n in names:
                prefixed.append(f"{prefix} {n}" if prefix else n)
        return sorted(set(prefixed))
    return names


def discover_mlc_conditions(conn, taskname: str) -> list[str]:
    return _discover_pattern_b_conditions(
        conn,
        taskname,
        metrics=_MLC_METRICS,
        value_only=_MLC_VALUE_ONLY,
        string_cols=_MLC_STRING,
        results_table="MQA_MDL_MlcQA_Results",
        exec_table="MQA_MDL_MlcQA_TestExecutions",
        exec_alias="mte",
        join_col="MlcQATestExecutionBase_Id",
    )


def discover_cbct_conditions(conn, taskname: str) -> list[str]:
    return _discover_pattern_b_conditions(
        conn,
        taskname,
        metrics=_CBCT_METRICS,
        value_only=_CBCT_VALUE_ONLY,
        results_table="MQA_MDL_Cbct_Results",
        exec_table="MQA_MDL_Cbct_TestExecutions",
        exec_alias="cte",
        join_col="Id",  # Cbct_Results.Id shares UUID with Cbct_TestExecutions.Id
    )


def discover_planar_conditions(conn, taskname: str) -> list[str]:
    return _discover_pattern_b_conditions(
        conn,
        taskname,
        metrics=_PLANAR_METRICS,
        results_table="MQA_MDL_Planar_Results",
        exec_table="MQA_MDL_Planar_TestExecutions",
        exec_alias="pte",
        join_col="Id",
    )


def discover_vmat_conditions(conn, taskname: str) -> list[str]:
    """VMAT = parent Normalization + per-ROI Mean / Std Dev. Prefixes when
    multiple test steps exist."""
    cursor = conn.cursor(as_dict=True)
    # Check if data exists + get test steps
    cursor.execute(
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_MDL_VmatDmlc_Results r
        JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
        JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
        """,
        (taskname,),
    )
    test_steps = [row["test_step"] for row in cursor.fetchall() if row["test_step"]]
    if not test_steps:
        return []
    multi = len(set(test_steps)) > 1

    names = [_VMAT_PARENT_NAME]
    cursor.execute(
        """
        SELECT DISTINCT rr.Name, te.Name AS test_step
        FROM MQA_MDL_VmatDmlc_RoiResults rr
        JOIN MQA_MDL_VmatDmlc_Results r ON rr.VmatDmlcResult_Id = r.Id
        JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
        JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND rr.Name IS NOT NULL
        """,
        (taskname,),
    )
    seen: set[str] = set()
    for row in cursor.fetchall():
        cleaned = clean_roi_name(row["Name"])
        prefix = _test_step_prefix(row.get("test_step")) if multi else ""
        for suffix in ("mean", "std dev"):
            full = f"{prefix} {cleaned} {suffix}" if prefix else f"{cleaned} {suffix}"
            if full not in seen:
                seen.add(full)
                names.append(full)
    return names


def discover_winston_lutz_conditions(conn, taskname: str) -> list[str]:
    """Winston-Lutz: two metrics per test step. Prefixes when multiple steps."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
        JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
        """,
        (taskname,),
    )
    test_steps = [row["test_step"] for row in cursor.fetchall() if row["test_step"]]
    if not test_steps:
        return []  # No data for this TaskName — don't add spurious conditions
    multi = len(set(test_steps)) > 1
    base = ["Maximum Deviation 2D", "Deviation 3D"]
    if multi:
        result = []
        for ts in set(test_steps):
            prefix = _test_step_prefix(ts)
            for n in base:
                result.append(f"{prefix} {n}" if prefix else n)
        return sorted(set(result))
    return base


# ---------------------------------------------------------------------------
# Per-type extractors (return {condition_name: {"value": ..., "state": int}})
# ---------------------------------------------------------------------------


def extract_numeric(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, dict[str, Any]]:
    """Numeric: row-per-condition. Filters State=10 (not started).

    When a session has multiple test steps (energies), condition names are
    prefixed with the energy code (e.g. ``"6MV Flatness"``).  When
    ``multi_override`` is provided it takes precedence over the session-level
    computation so that prefixing matches the TaskName-level ``discover_*``
    behaviour.

    Returns ``{condition_name: {"value": Actual, "state": int, "expected": float,
    "warn": float, "fail": float, "relative": bool}}``.
    """
    rows = _fetchall(
        conn,
        """
        SELECT tcne.Name, tcne.Actual, te.State, te.Name AS test_step,
               tcne.Expected, tcne.WarnOn, tcne.FailOn, tcne.IsRelative
        FROM MQA_Numeric_TestConditionExecutions tcne
        JOIN MQA_TestImplementationExecutions tie
            ON tcne.NumericTestExecution_Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s AND te.State != 10
        """,
        (execution_id,),
    )
    if multi_override is not None:
        multi = multi_override
    else:
        test_steps = {r["test_step"] for r in rows if r["test_step"]}
        multi = len(test_steps) > 1

    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["Name"]:
            continue
        name = _energy_prefixed(row["Name"], row["test_step"], multi)
        results[name] = {
            "value": row["Actual"],
            "state": row["State"],
            "expected": row.get("Expected"),
            "warn": row.get("WarnOn"),
            "fail": row.get("FailOn"),
            "relative": bool(row.get("IsRelative")),
        }
    return results


def extract_passfail(conn, execution_id: str) -> dict[str, dict[str, Any]]:
    """PassFail: all tests in session, keyed by TestExecution Name.

    Returns ``{test_name: {"value": AcceptanceCriteria, "state": int}}``.
    Filters State=10 (not started).
    """
    results: dict[str, dict[str, Any]] = {}
    for row in _fetchall(
        conn,
        """
        SELECT te.Name, pfte.AcceptanceCriteria, te.State
        FROM MQA_PassFail_TestExecutions pfte
        JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s AND te.State != 10
        ORDER BY te.Name
        """,
        (execution_id,),
    ):
        if row["Name"]:
            results[row["Name"]] = {
                "value": row.get("AcceptanceCriteria"),
                "state": row["State"],
            }
    return results


def extract_profile(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    """Profile: key by DisplayName + direction + energy. Includes tolerance data."""
    rows = _fetchall(
        conn,
        """
        SELECT dpr.Actual, dpr.DisplayName, dpr.Expected, dpr.Warn, dpr.Fail,
               dpr.ProfileDirection, te.Name AS test_step
        FROM MQA_Dosimetry_Profile_Results dpr
        JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
            ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
        JOIN MQA_Dosimetry_Profile_TestExecutions dpte
            ON dpqie.Id = dpte.ProfileQueueItem_Id
        JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s AND dpr.DisplayName IS NOT NULL
        """,
        (execution_id,),
    )
    if multi_override is not None:
        multi = multi_override
    else:
        test_steps = {r["test_step"] for r in rows if r["test_step"]}
        multi = len(test_steps) > 1
    results: dict[str, Any] = {}
    for row in rows:
        name = _profile_condition_name(
            row["DisplayName"], row.get("ProfileDirection"), row["test_step"], multi
        )
        results[name] = _result(
            row["Actual"], row.get("Expected"), row.get("Warn"), row.get("Fail")
        )
    return results


def extract_wedge(conn, execution_id: str) -> dict[str, Any]:
    """Wedge: key by ``Wedge Constancy {energy}x``. Includes tolerance data."""
    rows = _fetchall(
        conn,
        """
        SELECT wqie.ActualValue, wqie.ExpectedValue,
               wqie.Tolerance_Warn, wqie.Tolerance_Fail,
               wte.BeamQuality_EnergyValue
        FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
        JOIN MQA_Dosimetry_Wedge_TestExecutions wte
            ON wqie.WedgeConstancyExecution_Id = wte.Id
        JOIN MQA_TestImplementationExecutions tie ON wte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s AND wte.BeamQuality_EnergyValue IS NOT NULL
        """,
        (execution_id,),
    )
    results: dict[str, Any] = {}
    for row in rows:
        energy = int(round(row["BeamQuality_EnergyValue"] or 0))
        results[f"Wedge Constancy {energy}x"] = _result(
            row["ActualValue"],
            row.get("ExpectedValue"),
            row.get("Tolerance_Warn"),
            row.get("Tolerance_Fail"),
            relative=True,
        )
    return results


def extract_output(conn, execution_id: str) -> dict[str, Any]:
    """Output: key by ``Output {energy}x``. Includes tolerance data."""
    rows = _fetchall(
        conn,
        """
        SELECT oqie.Actual, oqie.Expected, oqie.WarningTolerance, oqie.ErrorTolerance,
               cqie.BeamQuality_EnergyValue
        FROM MQA_Dosimetry_Output_QueueItemExecutions oqie
        JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON oqie.Id = cqie.Id
        JOIN MQA_Dosimetry_Output_TestExecutions ote
            ON oqie.OutputConstancyExecution_Id = ote.Id
        JOIN MQA_TestImplementationExecutions tie ON ote.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
        """,
        (execution_id,),
    )
    results: dict[str, Any] = {}
    for row in rows:
        energy = int(round(row["BeamQuality_EnergyValue"] or 0))
        results[f"Output {energy}x"] = _result(
            row["Actual"],
            row.get("Expected"),
            row.get("WarningTolerance"),
            row.get("ErrorTolerance"),
            relative=True,
        )
    return results


def extract_energy(conn, execution_id: str) -> dict[str, Any]:
    """Energy: key by ``Energy {energy}{fff?} ch{chamber}``. Includes tolerance data."""
    rows = _fetchall(
        conn,
        """
        SELECT ece.Actual, ece.Expected, ece.WarningTolerance, ece.ErrorTolerance,
               cqie.BeamQuality_EnergyValue,
               cqie.BeamQuality_IsFlatteningFilterFree,
               ece.ChamberNumber
        FROM MQA_Dosimetry_Energy_ChamberExecutions ece
        JOIN MQA_Dosimetry_Energy_QueueItemExecutions eqie
            ON ece.EnergyConstancyQueueItemExecution_Id = eqie.Id
        JOIN MQA_Dosimetry_Energy_TestExecutions ete ON eqie.EnergyConstancyExecution_Id = ete.Id
        JOIN MQA_TestImplementationExecutions tie ON ete.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        JOIN MQA_Dosimetry_Common_QueueItemExecutions cqie ON eqie.Id = cqie.Id
        WHERE te.TaskExecutionId = %s AND cqie.BeamQuality_EnergyValue IS NOT NULL
        """,
        (execution_id,),
    )
    results: dict[str, Any] = {}
    for row in rows:
        energy = int(round(row["BeamQuality_EnergyValue"] or 0))
        fff = "fff" if row.get("BeamQuality_IsFlatteningFilterFree") else ""
        chamber = int(row.get("ChamberNumber") or 1)
        results[f"Energy {energy}{fff} ch{chamber}"] = _result(
            row["Actual"],
            row.get("Expected"),
            row.get("WarningTolerance"),
            row.get("ErrorTolerance"),
            relative=True,
        )
    return results


def _extract_pattern_b(
    conn,
    execution_id: str,
    *,
    metrics: dict,
    value_only: dict | None = None,
    string_cols: dict | None = None,
    results_table: str,
    exec_table: str,
    exec_alias: str,
    join_col: str,
    multi_override: bool | None = None,
) -> dict[str, Any]:
    """Generic Pattern B extractor: iterates all result rows for a session,
    reading value + tolerance columns. When multiple test steps produce
    multiple rows, metrics are prefixed with the test step name.
    """
    all_metrics = {**metrics}
    if value_only:
        all_metrics.update(value_only)
    if string_cols:
        all_metrics.update(string_cols)
    if not all_metrics:
        return {}

    # Build column list: values + tolerances
    select_cols = ["te.Name AS test_step"]
    for human_name, col in all_metrics.items():
        select_cols.append(f"r.{col}")
        for suffix in ("_Result_Value_Value", "_Value"):
            if col.endswith(suffix):
                prefix = col[: -len(suffix)]
                select_cols.append(
                    f"r.{prefix}_AcceptanceCriterion_ExpectedValue_Value"
                )
                select_cols.append(
                    f"r.{prefix}_AcceptanceCriterion_Tolerances_Warn_Value"
                )
                select_cols.append(
                    f"r.{prefix}_AcceptanceCriterion_Tolerances_Fail_Value"
                )
                break

    select_clause = ", ".join(select_cols)
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        f"""
        SELECT {select_clause}
        FROM {results_table} r
        JOIN {exec_table} {exec_alias} ON r.{join_col} = {exec_alias}.Id
        JOIN MQA_TestImplementationExecutions tie ON {exec_alias}.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s
        """,
        (execution_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return {}

    if multi_override is not None:
        multi = multi_override
    else:
        test_steps = {r["test_step"] for r in rows if r.get("test_step")}
        multi = len(test_steps) > 1

    results: dict[str, Any] = {}
    for row in rows:
        prefix = _test_step_prefix(row.get("test_step")) if multi else ""
        for human_name, col in all_metrics.items():
            val = row.get(col)
            if val is None:
                continue
            full_name = f"{prefix} {human_name}" if prefix else human_name

            tol_prefix = None
            for suffix in ("_Result_Value_Value", "_Value"):
                if col.endswith(suffix):
                    tol_prefix = col[: -len(suffix)]
                    break

            expected = warn = fail = None
            if tol_prefix:
                expected = row.get(
                    f"{tol_prefix}_AcceptanceCriterion_ExpectedValue_Value"
                )
                warn = row.get(
                    f"{tol_prefix}_AcceptanceCriterion_Tolerances_Warn_Value"
                )
                fail = row.get(
                    f"{tol_prefix}_AcceptanceCriterion_Tolerances_Fail_Value"
                )

            results[full_name] = {
                "value": val,
                "expected": expected,
                "warn": warn,
                "fail": fail,
                "relative": False,
            }
    return results


def extract_mlc(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    return _extract_pattern_b(
        conn,
        execution_id,
        metrics=_MLC_METRICS,
        value_only=_MLC_VALUE_ONLY,
        string_cols=_MLC_STRING,
        results_table="MQA_MDL_MlcQA_Results",
        exec_table="MQA_MDL_MlcQA_TestExecutions",
        exec_alias="mte",
        join_col="MlcQATestExecutionBase_Id",
        multi_override=multi_override,
    )


def extract_cbct(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    return _extract_pattern_b(
        conn,
        execution_id,
        metrics=_CBCT_METRICS,
        value_only=_CBCT_VALUE_ONLY,
        results_table="MQA_MDL_Cbct_Results",
        exec_table="MQA_MDL_Cbct_TestExecutions",
        exec_alias="cte",
        join_col="Id",
        multi_override=multi_override,
    )


def extract_planar(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    return _extract_pattern_b(
        conn,
        execution_id,
        metrics=_PLANAR_METRICS,
        results_table="MQA_MDL_Planar_Results",
        exec_table="MQA_MDL_Planar_TestExecutions",
        exec_alias="pte",
        join_col="Id",
        multi_override=multi_override,
    )


def extract_vmat(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    """VMAT = parent NormalizationValue + per-ROI Mean / Std Dev.
    Prefixes ROI names with test step when multiple test steps exist."""
    cursor = conn.cursor(as_dict=True)

    # Parent + children in one query with test_step
    cursor.execute(
        """
        SELECT te.Name AS test_step,
               r.NormalizationValueResult_Value_Value,
               rr.Name AS roi_name, rr.Mean_Value_Value,
               rr.StandardDeviation_Value_Value, rr.Rank
        FROM MQA_MDL_VmatDmlc_Results r
        JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
        JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        LEFT JOIN MQA_MDL_VmatDmlc_RoiResults rr ON rr.VmatDmlcResult_Id = r.Id
        WHERE te.TaskExecutionId = %s
        ORDER BY te.Name, rr.Rank
        """,
        (execution_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return {}

    if multi_override is not None:
        multi = multi_override
    else:
        test_steps = {r["test_step"] for r in rows if r.get("test_step")}
        multi = len(test_steps) > 1

    results: dict[str, Any] = {}
    for row in rows:
        prefix = _test_step_prefix(row.get("test_step")) if multi else ""
        # Parent value — discover always emits this unprefixed (one shared
        # Test), so extract must match.
        parent_name = _VMAT_PARENT_NAME
        norm = row.get("NormalizationValueResult_Value_Value")
        if norm is not None and parent_name not in results:
            results[parent_name] = {"value": norm}
        # Child ROI values
        roi = row.get("roi_name")
        if roi:
            cleaned = clean_roi_name(roi)
            for suffix, col in [
                ("mean", "Mean_Value_Value"),
                ("std dev", "StandardDeviation_Value_Value"),
            ]:
                full = (
                    f"{prefix} {cleaned} {suffix}" if prefix else f"{cleaned} {suffix}"
                )
                results[full] = {"value": row.get(col)}
    return results


def extract_winston_lutz(
    conn, execution_id: str, *, multi_override: bool | None = None
) -> dict[str, Any]:
    """Winston-Lutz: two metrics per test step. Iterates all test steps."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT te.Name AS test_step,
               wl.MaximumDeviation2D, wl.Deviation3D,
               wl.Expected, wl.Tolerance_Warn, wl.Tolerance_Fail
        FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
        JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskExecutionId = %s
        """,
        (execution_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return {}

    if multi_override is not None:
        multi = multi_override
    else:
        test_steps = {r["test_step"] for r in rows if r.get("test_step")}
        multi = len(test_steps) > 1

    results: dict[str, Any] = {}
    for row in rows:
        prefix = _test_step_prefix(row.get("test_step")) if multi else ""
        expected = row.get("Expected")
        warn = row.get("Tolerance_Warn")
        fail = row.get("Tolerance_Fail")
        for metric, col in [
            ("Maximum Deviation 2D", "MaximumDeviation2D"),
            ("Deviation 3D", "Deviation3D"),
        ]:
            full_name = f"{prefix} {metric}" if prefix else metric
            results[full_name] = {
                "value": row.get(col),
                "expected": expected,
                "warn": warn,
                "fail": fail,
                "relative": False,
            }
    return results


# DISTINCT test_step queries per execution type that uses the multi flag.
# Single source of truth — each query string is defined ONCE here and used
# only by compute_multi_flags. The discover_* functions embed the same
# JOIN/WHERE in their own queries; if a schema change is needed, update
# both the query here and the corresponding discover_* function.
_MULTI_FLAG_SQL: list[tuple[str, str]] = [
    (
        "Numeric",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_Numeric_TestConditionExecutions tcne
        JOIN MQA_TestImplementationExecutions tie
            ON tcne.NumericTestExecution_Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s AND te.State != 10
    """,
    ),
    (
        "Profile",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_Dosimetry_Profile_Results dpr
        JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
            ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
        JOIN MQA_Dosimetry_Profile_TestExecutions dpte
            ON dpqie.Id = dpte.ProfileQueueItem_Id
        JOIN MQA_TestImplementationExecutions tie ON dpte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
    (
        "VMAT",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_MDL_VmatDmlc_Results r
        JOIN MQA_MDL_VmatDmlc_TestExecutions vte ON r.Id = vte.Id
        JOIN MQA_TestImplementationExecutions tie ON vte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
    (
        "WinstonLutz",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_IsoCheck_WinstonLutz_TestExecutions wl
        JOIN MQA_TestImplementationExecutions tie ON wl.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
    # Pattern B types — generated from table metadata.
    (
        "MLC",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_MDL_MlcQA_Results r
        JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
        JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
    (
        "CBCT",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_MDL_Cbct_Results r
        JOIN MQA_MDL_Cbct_TestExecutions cte ON r.Id = cte.Id
        JOIN MQA_TestImplementationExecutions tie ON cte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
    (
        "Planar",
        """
        SELECT DISTINCT te.Name AS test_step
        FROM MQA_MDL_Planar_Results r
        JOIN MQA_MDL_Planar_TestExecutions pte ON r.Id = pte.Id
        JOIN MQA_TestImplementationExecutions tie ON pte.Id = tie.Id
        JOIN MQA_TestExecutions te ON tie.Id = te.Id
        WHERE te.TaskName = %s
    """,
    ),
]

# Parallel to _EXTRACTORS — maps each execution type to its discover function
# and condition type. Used by discover_conditions to iterate all types.
_DISCOVERERS = [
    ("Numeric", discover_numeric_conditions, "simple"),
    ("PassFail", discover_passfail_conditions, "string"),
    ("Profile", discover_profile_conditions, "simple"),
    ("Wedge", discover_wedge_conditions, "simple"),
    ("Output", discover_output_conditions, "simple"),
    ("Energy", discover_energy_conditions, "simple"),
    ("MLC", discover_mlc_conditions, "simple"),
    ("CBCT", discover_cbct_conditions, "simple"),
    ("Planar", discover_planar_conditions, "simple"),
    ("VMAT", discover_vmat_conditions, "simple"),
    ("WinstonLutz", discover_winston_lutz_conditions, "simple"),
]


def compute_multi_flags(conn, taskname: str) -> dict[str, bool]:
    """Compute the ``multi`` flag for each execution type at the TaskName level.

    Returns a dict keyed by the ``_EXTRACTORS`` label
    (``"Numeric"``, ``"Profile"``, ``"MLC"``, …).  Types that don't use a
    multi flag (PassFail, Wedge, Output, Energy) are omitted.
    """
    flags: dict[str, bool] = {}
    for label, sql in _MULTI_FLAG_SQL:
        rows = _fetchall(conn, sql, (taskname,))
        steps = {r["test_step"] for r in rows if r["test_step"]}
        flags[label] = len(steps) > 1
    return flags


# Order matters only for readability — extract_all_types merges everything
# into one dict before TestInstance creation.
_EXTRACTORS = [
    ("Numeric", extract_numeric),
    ("PassFail", extract_passfail),
    ("Profile", extract_profile),
    ("Wedge", extract_wedge),
    ("Output", extract_output),
    ("Energy", extract_energy),
    ("MLC", extract_mlc),
    ("CBCT", extract_cbct),
    ("Planar", extract_planar),
    ("VMAT", extract_vmat),
    ("WinstonLutz", extract_winston_lutz),
]


def extract_all_types(
    conn, execution_id: str, multi_flags: dict[str, bool] | None = None
) -> dict[str, dict[str, Any]]:
    """Run every specialized extractor against ``execution_id`` and merge.

    Returns ``{condition_name: {"value": ..., "state": int}}``. Non-Numeric/
    PassFail extractors (Profile, Wedge, etc.) have their bare values wrapped
    as ``{"value": val, "state": 40}`` (completed — these are automated
    measurements with no explicit per-test state).

    Empty results from an extractor (session has no data for that type) are
    skipped.

    When ``multi_flags`` is provided the corresponding ``multi_override`` is
    passed to each extractor so that test-step prefixing matches the
    TaskName-level discover behaviour.
    """
    merged: dict[str, dict[str, Any]] = {}
    for label, fn in _EXTRACTORS:
        kwargs: dict[str, Any] = {}
        if multi_flags and label in multi_flags:
            kwargs["multi_override"] = multi_flags[label]
        try:
            partial = fn(conn, execution_id, **kwargs)
        except Exception as e:  # noqa: BLE001 — log and continue with other types
            partial = {"_error": f"{type(e).__name__}: {e}"}
        if partial:
            for name, val in partial.items():
                if name == "_error":
                    continue
                if isinstance(val, dict) and "value" in val:
                    merged[name] = val
                else:
                    merged[name] = {"value": val, "state": 40}
    return merged


# ---------------------------------------------------------------------------
# Session querying + import
# ---------------------------------------------------------------------------


def _get_or_create_tolerance(
    warn: float | None,
    fail: float | None,
    relative: bool,
    internal_user,
) -> Tolerance | None:
    """Create or find a QATrack+ Tolerance from myQA warn/fail values.

    myQA stores relative tolerances as fractions (0.015 = 1.5%); QATrack+
    percent tolerances are in percent (1.5 = 1.5%). Limits are symmetric.
    """
    if warn is None or fail is None:
        return None

    if relative:
        tol_type = "percent"
        tol_high = round(warn * 100, 6)
        act_high = round(fail * 100, 6)
    else:
        tol_type = "absolute"
        tol_high = round(warn, 6)
        act_high = round(fail, 6)

    name = (
        f"{'Percent' if relative else 'Absolute'}"
        f"(-{act_high:.3f}, -{tol_high:.3f}, {tol_high:.3f}, {act_high:.3f})"
    )

    tol, _ = Tolerance.objects.get_or_create(
        type=tol_type,
        act_low=-act_high,
        tol_low=-tol_high,
        tol_high=tol_high,
        act_high=act_high,
        defaults={
            "name": name,
            "created_by": internal_user,
            "modified_by": internal_user,
        },
    )
    return tol


def _get_or_create_reference(
    expected: float | None,
    test_name: str,
    internal_user,
) -> Reference | None:
    """Create or find a QATrack+ Reference from myQA Expected value."""
    if expected is None:
        return None

    ref, _ = Reference.objects.get_or_create(
        type="absolute",
        value=expected,
        defaults={
            "name": f"{test_name} (myQA baseline)",
            "created_by": internal_user,
            "modified_by": internal_user,
        },
    )
    return ref


def _compute_pass_fail(
    value: float | None,
    expected: float | None,
    warn: float | None,
    fail: float | None,
    relative: bool,
) -> str:
    """Compute QATrack+ pass_fail from value vs myQA tolerance.

    Returns one of: ``ok``, ``tolerance``, ``action``, ``no_tol``.
    """
    if value is None or expected is None or warn is None or fail is None:
        return "no_tol"

    if relative:
        if expected == 0:
            return "no_tol"
        dev = abs(value - expected) / abs(expected) * 100
        tol_limit = warn * 100
        act_limit = fail * 100
    else:
        dev = abs(value - expected)
        tol_limit = warn
        act_limit = fail

    if dev <= tol_limit:
        return "ok"
    elif dev <= act_limit:
        return "tolerance"
    else:
        return "action"


def query_sessions(conn, taskname: str, days: int) -> list[dict[str, Any]]:
    """Query sessions for a TaskName within the last ``days`` days.

    Sessions are matched by EXACT TaskName equality (no LIKE patterns). Unit
    numbers are resolved through LINAC_MAP; unknown devices are skipped per
    spec myqa-device-expansion.
    """
    cutoff = timezone.now() - timezone.timedelta(days=days)
    cutoff_naive = cutoff.replace(hour=0, minute=0, second=0, microsecond=0).replace(
        tzinfo=None
    )
    now_naive = timezone.now().replace(tzinfo=None)

    device_to_unit = build_device_to_unit_map()
    cursor = conn.cursor(as_dict=True)
    # DISTINCT because MQA_TestExecutions has one row per test implementation
    # within a session — the same TaskExecutionId appears in multiple rows.
    # Session-level fields (TaskName, RadiationDeviceName, ReferenceDate,
    # FinishingDate) are denormalised and identical across those rows.
    cursor.execute(
        """
        SELECT DISTINCT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate,
               te.TaskName, te.RadiationDeviceName
        FROM MQA_TestExecutions te
        WHERE te.TaskName = %s
          AND te.ReferenceDate IS NOT NULL
          AND te.ReferenceDate >= %s
          AND te.ReferenceDate <= %s
        ORDER BY te.ReferenceDate, te.FinishingDate
        """,
        (taskname, cutoff_naive, now_naive),
    )

    sessions: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        device = row["RadiationDeviceName"]
        unit_num = device_to_unit.get(device)
        if unit_num is None:
            continue
        sessions.append(
            {
                "task_execution_id": str(row["TaskExecutionId"]),
                "reference_date": row["ReferenceDate"],
                "finishing_date": row["FinishingDate"],
                "task_name": row["TaskName"],
                "unit_number": unit_num,
                "linac_name": device,
            }
        )
    return sessions


def duplicate_check(taskname: str, execution_id: str, unit_number: int) -> bool:
    """True if a taskid TestInstance storing ``execution_id`` already exists."""
    taskid_slug = f"{slugify_name(taskname)}_taskid"
    return TestInstance.objects.filter(
        unit_test_info__test__slug=taskid_slug,
        unit_test_info__unit__number=unit_number,
        string_value=execution_id,
    ).exists()


def import_session(
    conn,
    taskname: str,
    session: dict[str, Any],
    internal_user,
    default_status,
    status_map: dict[str, TestInstanceStatus],
    multi_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Import one myQA session as a single TestListInstance.

    Aggregates results from every execution type present in the session into
    one TestListInstance under the TaskName's TestList. Stores a taskid
    TestInstance carrying the myQA TaskExecutionId (UUID) for dedup.

    Results are ``{condition_name: {"value": ..., "state": int}}`` dicts.
    State=10 conditions are already filtered out by extractors. State is
    mapped to a QATrack+ TestInstanceStatus via ``MYQA_STATE_MAP``.
    """
    unit_number = session["unit_number"]
    execution_id = session["task_execution_id"]
    ref_date = session["reference_date"]
    fin_date = session["finishing_date"] or ref_date

    list_slug = slugify_name(taskname)
    taskid_slug = f"{list_slug}_taskid"

    if duplicate_check(taskname, execution_id, unit_number):
        return {
            "status": "skipped_dup",
            "reason": f"duplicate taskid {execution_id[:8]}...",
        }

    results = extract_all_types(conn, execution_id, multi_flags=multi_flags)
    if not results:
        return {"status": "skipped_empty", "reason": "no data for this session"}

    try:
        test_list = TestList.objects.get(slug=list_slug)
    except TestList.DoesNotExist:
        return {"status": "error", "reason": f"No TestList for slug {list_slug}"}

    ct = ContentType.objects.get_for_model(test_list)
    utc = UnitTestCollection.objects.filter(
        unit__number=unit_number, content_type=ct, object_id=test_list.pk
    ).first()
    if utc is None:
        return {
            "status": "error",
            "reason": f"No UTC for unit {unit_number} / list {list_slug}",
        }

    # Look up Tests by slug within this TestList's memberships. Also build a
    # name→test fallback for the Test.name UNIQUE constraint case: when two
    # conditions enrich to the same name (e.g., "01. Pressure" and "07.
    # Pressure" both → "Pressure"), setup links the TestList to the first
    # Test by name. The import's slug lookup misses, so we fall back to name.
    tests_by_slug: dict[str, Test] = {}
    tests_by_name: dict[str, Test] = {}
    for test in Test.objects.filter(testlistmembership__test_list=test_list):
        tests_by_slug[test.slug] = test
        tests_by_name[test.name] = test

    utis_by_slug: dict[str, UnitTestInfo] = {}
    for uti in UnitTestInfo.objects.filter(
        unit__number=unit_number, test__in=list(tests_by_slug.values())
    ).select_related("test"):
        utis_by_slug[uti.test.slug] = uti

    try:
        with transaction.atomic():
            tli = TestListInstance(
                unit_test_collection=utc,
                test_list=test_list,
                work_started=ref_date,
                work_completed=fin_date or timezone.now(),
                in_progress=False,
                include_for_scheduling=False,
                day=0,
                created_by=internal_user,
                modified_by=internal_user,
                modified=timezone.now(),
            )
            tli.save()

            tis: list[TestInstance] = []
            utis_to_update: list[UnitTestInfo] = []
            for name, info in results.items():
                slug = slugify_name(name)
                test = tests_by_slug.get(slug)
                if test is None:
                    # Fallback: try enriched name then raw name (handles
                    # cross-TaskName UNIQUE name constraint collisions).
                    enriched_name = enrich_test_name(name, taskname, {})
                    test = tests_by_name.get(enriched_name) or tests_by_name.get(name)
                if test is None:
                    continue
                # Use the test's actual slug for UTI lookup.
                uti = utis_by_slug.get(test.slug)
                if uti is None:
                    continue

                # State-aware status mapping
                state = info.get("state", 40)
                state_action = MYQA_STATE_MAP.get(state, "unreviewed")
                if state_action == "skip":
                    continue  # State=10 — don't create TestInstance

                ti_status = status_map.get(state_action, default_status)
                val = info.get("value")

                # Tolerance + reference + pass_fail from myQA data
                expected = info.get("expected")
                warn = info.get("warn")
                fail = info.get("fail")
                relative = info.get("relative", False)

                numeric_val = (
                    float(val)
                    if isinstance(val, (int, float)) and not isinstance(val, bool)
                    else None
                )
                pass_fail = _compute_pass_fail(
                    numeric_val, expected, warn, fail, relative
                )

                # Update UTI tolerance + reference (handles rebaselining —
                # latest import's tolerances are applied).
                ti_ref = None
                ti_tol = None
                if expected is not None and (warn is not None or fail is not None):
                    new_tol = _get_or_create_tolerance(
                        warn, fail, relative, internal_user
                    )
                    new_ref = _get_or_create_reference(
                        expected, test.name, internal_user
                    )
                    if new_tol is not None and uti.tolerance_id != new_tol.pk:
                        uti.tolerance = new_tol
                        utis_to_update.append(uti)
                    if new_ref is not None and uti.reference_id != new_ref.pk:
                        uti.reference = new_ref
                        if uti not in utis_to_update:
                            utis_to_update.append(uti)
                    ti_ref = new_ref
                    ti_tol = new_tol

                tis.append(
                    TestInstance(
                        test_list_instance=tli,
                        unit_test_info=uti,
                        value=numeric_val,
                        string_value=str(val) if isinstance(val, str) else None,
                        reference=ti_ref,
                        tolerance=ti_tol,
                        work_started=ref_date,
                        work_completed=fin_date or timezone.now(),
                        created_by=internal_user,
                        modified_by=internal_user,
                        status=ti_status,
                        pass_fail=pass_fail,
                        order=0,
                    )
                )

            # taskid TestInstance for dedup
            taskid_test = tests_by_slug.get(taskid_slug)
            taskid_uti = utis_by_slug.get(taskid_slug)
            if taskid_test is not None and taskid_uti is not None:
                tis.append(
                    TestInstance(
                        test_list_instance=tli,
                        unit_test_info=taskid_uti,
                        string_value=execution_id,
                        work_started=ref_date,
                        work_completed=fin_date or timezone.now(),
                        created_by=internal_user,
                        modified_by=internal_user,
                        status=default_status,
                        pass_fail="no_tol",
                        order=0,
                    )
                )

            # Save UTI tolerance/reference updates before bulk_create.
            for uti in utis_to_update:
                uti.save(update_fields=["tolerance", "reference"])

            if tis:
                TestInstance.objects.bulk_create(tis)

        return {"status": "imported", "count": len(tis)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def import_myqa_results(META: dict) -> str:
    """django-q entry point. Delegates to ``qatrack.qa.tasks.import_myqa_all``.

    ``META`` keys:
      * ``task_name`` (str|None): limit to one TaskName; otherwise discover all.
      * ``days`` (int): lookback window (default 30).

    Returns a JSON summary string.
    """
    from qatrack.qa.tasks import import_myqa_all

    result = import_myqa_all(
        task_name=META.get("task_name"),
        days=int(META.get("days", 30)),
    )
    return json.dumps(result)
