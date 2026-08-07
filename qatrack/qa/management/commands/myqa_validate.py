"""Read-only diff command: compare QATrack+ state to myQA source-of-truth.

For each (TaskName, unit) in scope over the given window:
  - session-count mismatch (myQA sessions vs QATrack+ TLIs)
  - per-session condition-count mismatch
  - per-condition value mismatch (within 4-decimal rounding)
  - per-condition tolerance mismatch
  - categorise unimported sessions as valueless_skip vs genuine_drop

Useful both at onboarding (centre's first trust-building step) and
operationally (BCHC running it after every big import to catch silent
drops). Read-only: SELECTs against myQA, ORM reads against QATrack+.
"""

import json
from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from qatrack.myqa_import import (
    compute_multi_flags,
    duplicate_check,
    extract_all_types,
    get_connection,
    query_sessions,
    slugify_name,
)
from qatrack.qa.models import TestInstance, TestListInstance

# Match the engine's value-rounding precision (myqa_import._result).
_VALUE_ROUND = 4


def _categorise_unimported(
    conn, taskname: str, sessions: list[dict], multi_flags: dict[str, bool]
) -> dict[str, int]:
    """For sessions myQA has but QATrack+ doesn't, classify each by
    whether it had values.

    Returns ``{"valueless_skip": N, "genuine_drop": M}``.
    """
    counts = {"valueless_skip": 0, "genuine_drop": 0}
    for s in sessions:
        if duplicate_check(taskname, s["task_execution_id"], s["unit_number"]):
            continue  # actually imported — skip
        try:
            results = extract_all_types(
                conn, s["task_execution_id"], multi_flags=multi_flags
            )
        except Exception:
            # If extraction itself fails, treat as genuine drop (surface it).
            counts["genuine_drop"] += 1
            continue
        has_value = any(
            isinstance(v, dict) and v.get("value") is not None for v in results.values()
        )
        if has_value:
            counts["genuine_drop"] += 1
        else:
            counts["valueless_skip"] += 1
    return counts


def _session_fidelity(
    conn,
    taskname: str,
    session: dict,
    multi_flags: dict[str, bool],
    tli: TestListInstance,
) -> dict[str, Any]:
    """Compare one myQA session to its QATrack+ TLI.

    Returns ``{"conditions_match": bool, "value_mismatches": [...],
    "tolerance_diffs": [...]}``.
    """
    # myQA side
    try:
        myqa_results = extract_all_types(
            conn, session["task_execution_id"], multi_flags=multi_flags
        )
    except Exception as e:
        return {
            "conditions_match": False,
            "value_mismatches": [],
            "tolerance_diffs": [],
            "error": f"extract failed: {e}",
        }

    # QATrack+ side — index TIs by their Test's slug (computed from raw name)
    qatrack_tis: dict[str, TestInstance] = {}
    for ti in tli.testinstance_set.all().select_related(
        "unit_test_info__test", "reference", "tolerance"
    ):
        qatrack_tis[ti.unit_test_info.test.slug] = ti

    myqa_keys = set()
    for raw_name in myqa_results.keys():
        myqa_keys.add(slugify_name(raw_name))

    qatrack_keys = set(qatrack_tis.keys())
    conditions_match = myqa_keys == qatrack_keys

    value_mismatches: list[dict[str, Any]] = []
    tolerance_diffs: list[dict[str, Any]] = []
    for raw_name, info in myqa_results.items():
        slug = slugify_name(raw_name)
        ti = qatrack_tis.get(slug)
        if ti is None:
            continue
        if not isinstance(info, dict):
            continue
        # Value comparison (within 4-decimal rounding)
        myqa_val = info.get("value")
        if (
            myqa_val is not None
            and ti.value is not None
            and isinstance(myqa_val, (int, float))
            and not isinstance(myqa_val, bool)
        ):
            if round(float(myqa_val), _VALUE_ROUND) != round(
                float(ti.value), _VALUE_ROUND
            ):
                value_mismatches.append(
                    {"condition": raw_name, "myqa": myqa_val, "qatrack": ti.value}
                )
        # Tolerance comparison — only flag if BOTH sides have values
        myqa_warn = info.get("warn")
        myqa_fail = info.get("fail")
        if myqa_warn is not None and myqa_fail is not None and ti.tolerance is not None:
            # The QATrack+ Tolerance was created from myQA values; warn if
            # they've drifted (e.g. admin edited the tolerance).
            myqa_warn_rounded = round(float(myqa_warn), _VALUE_ROUND)
            myqa_fail_rounded = round(float(myqa_fail), _VALUE_ROUND)
            qa_tol_high = (
                round(float(ti.tolerance.tol_high), _VALUE_ROUND)
                if ti.tolerance.tol_high is not None
                else None
            )
            qa_act_high = (
                round(float(ti.tolerance.act_high), _VALUE_ROUND)
                if ti.tolerance.act_high is not None
                else None
            )
            # Engine converts relative (myQA fraction) to percent (QATrack+).
            # Use the same logic: warn*100 if relative.
            relative = info.get("relative", False)
            scale = 100.0 if relative else 1.0
            if (
                qa_tol_high is not None
                and round(myqa_warn_rounded * scale, _VALUE_ROUND) != qa_tol_high
            ):
                tolerance_diffs.append(
                    {
                        "condition": raw_name,
                        "myqa_warn": myqa_warn_rounded * scale,
                        "qatrack_warn": qa_tol_high,
                    }
                )
            elif (
                qa_act_high is not None
                and round(myqa_fail_rounded * scale, _VALUE_ROUND) != qa_act_high
            ):
                tolerance_diffs.append(
                    {
                        "condition": raw_name,
                        "myqa_fail": myqa_fail_rounded * scale,
                        "qatrack_fail": qa_act_high,
                    }
                )

    return {
        "conditions_match": conditions_match,
        "value_mismatches": value_mismatches,
        "tolerance_diffs": tolerance_diffs,
    }


class Command(BaseCommand):
    help = (
        "Read-only diff of QATrack+ state against myQA for the given window. "
        "Reports session-count, condition-count, value, and tolerance "
        "mismatches per TestList+unit. Categorises unimported sessions as "
        "valueless_skip (OK) vs genuine_drop (investigate)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Look back this many days from now (default: 30)",
        )
        parser.add_argument(
            "--task-name",
            type=str,
            default=None,
            help="Limit to a single TaskName (default: all TestLists)",
        )
        parser.add_argument(
            "--unit",
            type=int,
            default=None,
            help="Limit to a single QATrack+ unit number",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Machine-readable JSON output for CI",
        )
        parser.add_argument(
            "--summary-only",
            action="store_true",
            default=False,
            help="Skip per-condition value/tolerance comparison for speed",
        )

    def handle(self, *args, **options):
        days = options["days"]
        only_taskname = options["task_name"]
        only_unit = options["unit"]
        as_json = options["json"]
        summary_only = options["summary_only"]

        conn = get_connection()
        try:
            tasknames = (
                [only_taskname] if only_taskname else self._recent_tasknames(conn, days)
            )
        finally:
            conn.close()

        # Build report structure
        results: list[dict[str, Any]] = []
        summary = {"pass": 0, "needs_review": 0, "fail": 0}

        for tn in tasknames:
            conn_for_tn = get_connection()  # fresh connection per taskname
            try:
                sessions = query_sessions(conn_for_tn, tn, days)
                if only_unit is not None:
                    sessions = [s for s in sessions if s["unit_number"] == only_unit]
                if not sessions:
                    continue

                multi_flags = compute_multi_flags(conn_for_tn, tn)

                # Group sessions by unit_number for reporting
                sessions_by_unit: dict[int, list[dict]] = defaultdict(list)
                for s in sessions:
                    sessions_by_unit[s["unit_number"]].append(s)

                for unit_num, unit_sessions in sessions_by_unit.items():
                    unit_result = self._validate_unit(
                        conn_for_tn,
                        tn,
                        unit_num,
                        unit_sessions,
                        multi_flags,
                        summary_only,
                    )
                    if unit_result is None:
                        continue  # e.g. no UTC for this unit
                    results.append(unit_result)
                    if unit_result["status"] == "pass":
                        summary["pass"] += 1
                    elif unit_result["status"] == "needs_review":
                        summary["needs_review"] += 1
                    else:
                        summary["fail"] += 1
            finally:
                conn_for_tn.close()
        conn.close()

        if as_json:
            self._emit_json(results, summary, days)
        else:
            self._emit_human(results, summary, days)

    def _recent_tasknames(self, conn, days: int) -> list[str]:
        """Return all TaskNames known to myQA.

        ``days`` is currently unused — the per-TaskName ``query_sessions``
        call inside ``handle`` already returns 0 sessions for TaskNames
        with no activity in the window, so iterating all TaskNames is
        correct (just not optimally fast). A future optimisation could
        push the date filter into the discovery SQL.
        """
        from qatrack.myqa_import import discover_tasknames

        return discover_tasknames(conn)

    def _validate_unit(
        self,
        conn,
        taskname: str,
        unit_number: int,
        sessions: list[dict],
        multi_flags: dict[str, bool],
        summary_only: bool,
    ) -> dict[str, Any] | None:
        """Build a result dict for one TaskName + unit."""
        # Dedupe sessions by task_execution_id — myQA sometimes returns the
        # same logical session under multiple rows (different test
        # implementations within one TaskExecutionId). Without dedup the
        # counts would be inflated and inconsistent.
        seen_exec_ids: set[str] = set()
        unique_sessions: list[dict] = []
        for s in sessions:
            eid = s["task_execution_id"]
            if eid in seen_exec_ids:
                continue
            seen_exec_ids.add(eid)
            unique_sessions.append(s)
        sessions = unique_sessions

        # Look up the QATrack+ TLIs for this taskname + unit, filtered to
        # the same window as the myQA sessions. query_sessions filters by
        # ReferenceDate; QATrack+ TLIs use work_started for the same purpose.
        list_slug = slugify_name(taskname)
        if not sessions:
            return None
        # Window bounds (use the min/max reference_date from the myQA sessions)
        from datetime import datetime

        ref_dates = [s["reference_date"] for s in sessions if s["reference_date"]]
        if not ref_dates:
            return None
        window_start = min(ref_dates)
        window_end = max(ref_dates)
        # Coerce to timezone-aware for comparison with TLI.work_started (USE_TZ)
        if isinstance(window_start, datetime) and window_start.tzinfo is None:
            from zoneinfo import ZoneInfo

            from django.conf import settings as dj_settings

            tz = ZoneInfo(getattr(dj_settings, "TIME_ZONE", "UTC"))
            window_start = window_start.replace(tzinfo=tz)
            window_end = window_end.replace(tzinfo=tz)
        tlis_qs = TestListInstance.objects.filter(
            unit_test_collection__unit__number=unit_number,
            test_list__slug=list_slug,
            work_started__gte=window_start,
            work_started__lte=window_end + timezone.timedelta(days=1),
        )
        tlis = list(tlis_qs)

        # Count sessions imported (use duplicate_check which scans ALL TLIs
        # ever, not just the window — a session imported long ago whose TLI
        # falls outside the window would otherwise be miscategorised as
        # "unimported" here).
        imported_exec_ids: set[str] = set()
        for s in sessions:
            if duplicate_check(taskname, s["task_execution_id"], unit_number):
                imported_exec_ids.add(s["task_execution_id"])

        # Categorise each session: imported / valueless_skip / genuine_drop
        valueless_skip = 0
        genuine_drop = 0
        for s in sessions:
            if s["task_execution_id"] in imported_exec_ids:
                continue
            # Unimported — categorise
            try:
                results = extract_all_types(
                    conn, s["task_execution_id"], multi_flags=multi_flags
                )
            except Exception:
                genuine_drop += 1
                continue
            if any(
                isinstance(v, dict) and v.get("value") is not None
                for v in results.values()
            ):
                genuine_drop += 1
            else:
                valueless_skip += 1

        status = "pass"
        conditions_mismatch_total = 0
        value_mismatch_total = 0
        tolerance_diff_total = 0

        if genuine_drop > 0:
            status = "needs_review" if status == "pass" else status

        if not summary_only and tlis:
            # Per-TLI fidelity check
            for tli in tlis:
                # Find the session that created this TLI
                taskid_ti = tli.testinstance_set.filter(
                    unit_test_info__test__slug=f"{list_slug}_taskid"
                ).first()
                if not taskid_ti or not taskid_ti.string_value:
                    continue
                matching_session = next(
                    (
                        s
                        for s in sessions
                        if s["task_execution_id"] == taskid_ti.string_value
                    ),
                    None,
                )
                if matching_session is None:
                    continue
                fidelity = _session_fidelity(
                    conn, taskname, matching_session, multi_flags, tli
                )
                if not fidelity.get("conditions_match", True):
                    conditions_mismatch_total += 1
                    status = "needs_review"
                value_mismatch_total += len(fidelity.get("value_mismatches", []))
                if fidelity.get("value_mismatches"):
                    status = "needs_review"
                tolerance_diff_total += len(fidelity.get("tolerance_diffs", []))
                if fidelity.get("tolerance_diffs") and status == "pass":
                    status = "needs_review"  # tolerance diffs are informational but flag for review

        # Get unit name for display
        from qatrack.units.models import Unit

        unit = Unit.objects.filter(number=unit_number).first()
        unit_name = unit.name if unit else "(unknown)"

        return {
            "taskname": taskname,
            "unit_number": unit_number,
            "unit_name": unit_name,
            "status": status,
            "sessions": {
                "myqa_in_window": len(sessions),
                "qatrack_in_window": len(tlis),
                "imported_total": len(imported_exec_ids),
                # Sessions myQA has that QATrack+ doesn't:
                "missing": valueless_skip + genuine_drop,
                "valueless_skip": valueless_skip,
                "genuine_drop": genuine_drop,
            },
            "conditions": {"mismatched_tlis": conditions_mismatch_total},
            "value_mismatches": value_mismatch_total,
            "tolerance_diffs": tolerance_diff_total,
        }

    def _emit_human(self, results: list[dict], summary: dict, days: int):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nValidating last {days} days against myQA...")
        )
        self.stdout.write("─" * 80)
        for r in results:
            sym = {"pass": "✓", "needs_review": "⚠", "fail": "✗"}[r["status"]]
            self.stdout.write(
                f"  {sym} {r['taskname'][:50]:<50} (unit {r['unit_number']}, {r['unit_name'][:20]})"
            )
            s = r["sessions"]
            self.stdout.write(
                f"      Sessions in window: myQA {s['myqa_in_window']:>3}  ↔  "
                f"QATrack+ {s['qatrack_in_window']:>3}  (imported total: {s['imported_total']})"
            )
            if s["valueless_skip"] or s["genuine_drop"]:
                self.stdout.write(
                    f"      Unimported: {s['valueless_skip']} valueless-skip (OK), "
                    f"{s['genuine_drop']} genuine-drop (investigate)"
                )
            if r["value_mismatches"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"      Value mismatches: {r['value_mismatches']}"
                    )
                )
            if r["tolerance_diffs"]:
                self.stdout.write(
                    self.style.WARNING(f"      Tolerance diffs: {r['tolerance_diffs']}")
                )
        self.stdout.write("─" * 80)
        self.stdout.write(
            f"\nSummary: {summary['pass']} pass, {summary['needs_review']} needs review, "
            f"{summary['fail']} fail"
        )
        if summary["needs_review"] or summary["fail"]:
            self.stdout.write(
                self.style.WARNING(
                    "Items marked 'needs review' may indicate silent data drops or "
                    "config drift. Investigate before relying on the data."
                )
            )

    def _emit_json(self, results: list[dict], summary: dict, days: int):
        payload = {
            "window_days": days,
            "summary": summary,
            "testlists": results,
        }
        self.stdout.write(json.dumps(payload, indent=2, default=str))
