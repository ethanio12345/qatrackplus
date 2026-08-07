"""Dynamic setup of myQA TestLists, Tests, Memberships, UTCs and UTIs.

Replaces the previous importer-class-driven setup with TaskName-driven
discovery (specs/dynamic-taskname-discovery). For each myQA TaskName we:

* Create one TestList named verbatim from the TaskName (slug =
  ``slugify(TaskName)``).
* Create / reuse shared Tests by ``slugify(condition_name)`` (NO list prefix)
  — the same condition name in two tasks maps to the same Test, shared via
  TestListMembership.
* Apply enrichment (specs/descriptive-test-names) to produce descriptive
  ``Test.name`` values: strip number prefixes, expand abbreviations, apply
  YAML overrides. Slugs stay derived from the RAW condition name.
* Disambiguate duplicate condition names within a single task by appending
  ``_2``, ``_3`` … to the slug, and `` 2``, `` 3`` to the display name.
* Set ``Test.description`` to record the original myQA condition name and
  contributing TaskName(s) for provenance.
* Create one taskid Test per TestList (slug ``{list_slug}_taskid``) for
  dedup during import.
* Create UnitTestCollections + UnitTestInfos only for units that actually
  have execution data for the TaskName (no blanket LINAC_MAP loop).
* Generate ``docs/myqa_test_mapping.{csv,md}`` traceability artifacts.
* Do NOT assign tolerances — shared tests cannot have conflicting tolerances
  across tasks. Users configure tolerances per-unit through the admin after
  setup.
"""

import csv
import os
from functools import lru_cache
from itertools import groupby

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from qatrack.myqa_import import (
    discover_condition_metadata,
    discover_conditions,
    discover_task_protocol,
    discover_tasknames,
    discover_units_for_taskname,
    enrich_test_name,
    ensure_frequencies_exist,
    ensure_statuses_exist,
    get_connection,
    infer_frequency,
    load_name_overrides,
    slugify_name,
)
from qatrack.qa.models import (
    Category,
    Frequency,
    Test,
    TestList,
    TestListMembership,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.qa.utils import get_internal_user
from qatrack.units.models import Unit


def _default_category() -> Category:
    """Resolve the default Category for new Tests.

    Tries slug ``"uncategorised"`` (QATrack+ default catch-all), then the
    first Category by PK, then PK 1 (legacy fallback). Robust against
    centres that have re-seeded ``qa_category`` with different PKs.

    Cached via :func:`functools.lru_cache` so the DB lookup happens at most
    once per process — ``setup_myqa_tests`` creates thousands of Tests and
    would otherwise re-query for each.
    """
    return _default_category_cached()


@lru_cache(maxsize=1)
def _default_category_cached() -> Category:
    try:
        return Category.objects.get(slug="uncategorised")
    except Category.DoesNotExist:
        pass
    first = Category.objects.order_by("id").first()
    if first is not None:
        return first
    # Catastrophic case: no Categories at all. Legacy behaviour is to use
    # PK 1; let that raise DoesNotExist naturally so the operator notices.
    return Category.objects.get(pk=1)


_MAPPING_COLUMNS = [
    "testlist_name",
    "testlist_slug",
    "myqa_condition_name",
    "qatrack_test_name",
    "test_slug",
    "execution_type",
    "source_table",
]

# Repo root = 5 dirnames up from this file
# (qatrack/qa/management/commands/setup_myqa_tests.py)
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)


def _disambiguate(
    condition_names: list[dict],
    taskname: str,
    overrides: dict[tuple[str, str], str],
    metadata: dict[str, dict] | None = None,
) -> list[dict]:
    """Disambiguate raw condition names into unique slugs AND display names.

    Per spec dynamic-taskname-discovery R4: when a TaskName has multiple
    conditions that slugify to the same value, the second and subsequent get
    ``_2``, ``_3`` suffixes on the slug. Additionally, enriched display names
    that collide (e.g. ``01. Vrt`` and ``02. Vrt`` both enrich to ``Vertical``)
    get `` 2``, `` 3`` numeric suffixes to satisfy the ``Test.name`` UNIQUE
    constraint.

    Returns a list of dicts with ``name`` (enriched display), ``slug``,
    ``type``, ``source``, ``raw_name``, and optional ``metadata`` keys.
    """
    if metadata is None:
        metadata = {}
    slug_counts: dict[str, int] = {}
    display_counts: dict[str, int] = {}
    out: list[dict] = []
    for cond in condition_names:
        raw_name = cond["name"]
        enriched = enrich_test_name(raw_name, taskname, overrides)
        base_slug = slugify_name(raw_name)

        # Slug disambiguation (from raw names — unchanged behaviour).
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        n_slug = slug_counts[base_slug]
        slug = base_slug if n_slug == 1 else f"{base_slug}_{n_slug}"

        # Display name disambiguation (from enriched names).
        display_counts[enriched] = display_counts.get(enriched, 0) + 1
        n_display = display_counts[enriched]
        display = enriched if n_display == 1 else f"{enriched} {n_display}"

        out.append(
            {
                "name": display,
                "slug": slug,
                "type": cond["type"],
                "source": cond.get("source", ""),
                "raw_name": raw_name,
                "metadata": metadata.get(raw_name, {}),
            }
        )
    return out


class Command(BaseCommand):
    help = (
        "One-time setup of myQA TestLists, Tests, Memberships, UTCs and UTIs. "
        "Discovers all TaskNames from myQA dynamically and creates one "
        "TestList per TaskName with shared Tests named by condition name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview only: list discovered TaskNames and condition counts, no DB writes",
        )
        parser.add_argument(
            "--task-name",
            default=None,
            help="Only run setup for this specific TaskName (default: all discovered TaskNames)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        only_taskname = options.get("task_name")

        internal_user = get_internal_user()

        # Create the once_off / other Frequencies that infer_frequency can
        # return for commissioning / unrecognised TaskNames (they're not part
        # of the default QATrack+ frequency set). Idempotent.
        if not dry_run:
            ensure_frequencies_exist()
            ensure_statuses_exist()

        # Load YAML overrides for descriptive test names (descriptive-test-names D3).
        overrides = load_name_overrides()

        conn = get_connection()
        try:
            if only_taskname:
                tasknames = [only_taskname]
            else:
                tasknames = discover_tasknames(conn)
        finally:
            conn.close()

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nDiscovered {len(tasknames)} TaskName(s) from myQA"
            )
        )

        totals = {
            "test_lists": 0,
            "tests": 0,
            "memberships": 0,
            "utcs": 0,
            "utis": 0,
        }

        # Accumulate mapping data for docs/myqa_test_mapping.{csv,md}.
        self._mapping_rows: list[dict] = []

        for taskname in tasknames:
            counts = self._setup_one_taskname(
                taskname=taskname,
                internal_user=internal_user,
                dry_run=dry_run,
                overrides=overrides,
            )
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {totals['test_lists']} test lists, {totals['tests']} tests, "
                f"{totals['memberships']} memberships, "
                f"{totals['utcs']} UTCs, {totals['utis']} UTIs"
            )
        )

        # Generate traceability mapping document (non-dry-run only).
        if not dry_run and self._mapping_rows:
            docs_dir = os.path.join(_REPO_ROOT, "docs")
            self._write_mapping_csv(docs_dir)
            self._write_mapping_md(docs_dir)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Mapping document written: {len(self._mapping_rows)} rows to docs/"
                )
            )

    def _setup_one_taskname(
        self,
        taskname: str,
        internal_user,
        dry_run: bool,
        overrides: dict[tuple[str, str], str],
    ) -> dict[str, int]:
        """Run setup for a single TaskName. Returns a counts dict."""
        counts = {
            "test_lists": 0,
            "tests": 0,
            "memberships": 0,
            "utcs": 0,
            "utis": 0,
        }
        list_slug = slugify_name(taskname)

        conn = get_connection()
        try:
            conditions = discover_conditions(conn, taskname)
            unit_numbers = discover_units_for_taskname(conn, taskname)
            cond_metadata = discover_condition_metadata(conn, taskname)
            protocol = discover_task_protocol(conn, taskname)
        finally:
            conn.close()

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n--- {taskname} ---"))
        self.stdout.write(
            f"  slug={list_slug}, {len(conditions)} condition(s), "
            f"{len(unit_numbers)} unit(s) with data, "
            f"{len(cond_metadata)} with descriptions"
        )

        if not conditions:
            self.stdout.write(self.style.WARNING("  SKIP: no conditions discovered"))
            return counts

        # Disambiguate + enrich display names.
        specs = _disambiguate(conditions, taskname, overrides, cond_metadata)

        if dry_run:
            for spec in specs:
                self.stdout.write(
                    f"    - {spec['slug']} ({spec['type']}) \"{spec['name']}\""
                    f"  [raw: \"{spec['raw_name']}\"]"
                )
            self.stdout.write(f"    units: {unit_numbers}")
            return counts

        # Resolve Frequency from TaskName (design D6).
        freq_slug = infer_frequency(taskname)
        try:
            freq = Frequency.objects.get(slug=freq_slug)
        except Frequency.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    f"  Frequency '{freq_slug}' not found — falling back to 'daily'"
                )
            )
            freq = Frequency.objects.get(slug="daily")

        with transaction.atomic():
            # 1. TestList (name=TaskName verbatim, slug=slugify(TaskName)).
            tl_desc = f'Auto-created TestList for myQA TaskName "{taskname}"'
            if protocol:
                tl_desc += f"\nProtocol: {protocol}"
            test_list, tl_created = TestList.objects.get_or_create(
                slug=list_slug,
                defaults={
                    "name": taskname,
                    "description": tl_desc,
                    "created_by": internal_user,
                    "modified_by": internal_user,
                },
            )
            if tl_created:
                counts["test_lists"] += 1
            else:
                # Update name + description if the list pre-existed or
                # protocol info changed.
                changed = False
                if test_list.name != taskname:
                    test_list.name = taskname
                    changed = True
                if test_list.description != tl_desc:
                    test_list.description = tl_desc
                    changed = True
                if changed:
                    test_list.save(update_fields=["name", "description"])

            # 2. taskid Test + membership (order=0).
            taskid_slug = f"{list_slug}_taskid"
            taskid_test, taskid_created = Test.objects.get_or_create(
                slug=taskid_slug,
                defaults={
                    "name": f"{taskname} Task ID",
                    "type": "string",
                    "category": _default_category(),
                    "created_by": internal_user,
                    "modified_by": internal_user,
                },
            )
            if taskid_created:
                counts["tests"] += 1
            _, taskid_mb_created = TestListMembership.objects.get_or_create(
                test_list=test_list,
                test=taskid_test,
                defaults={"order": 0},
            )
            if taskid_mb_created:
                counts["memberships"] += 1

            # 3. Per-condition Tests (shared, enriched names) + Memberships.
            created_tests: list[Test] = [taskid_test]
            for i, spec in enumerate(specs):
                # Use a savepoint so a UNIQUE-name constraint violation during
                # get_or_create doesn't poison the outer transaction.
                try:
                    with transaction.atomic():
                        test, t_created = Test.objects.get_or_create(
                            slug=spec["slug"],
                            defaults={
                                "name": spec["name"],
                                "type": spec.get("type", "simple"),
                                "category": _default_category(),
                                "created_by": internal_user,
                                "modified_by": internal_user,
                            },
                        )
                except Exception:
                    # Test.name has a UNIQUE constraint — if a Test with the
                    # same name but different slug pre-exists, fall back to a
                    # name lookup so the shared Test is still linked.
                    test = Test.objects.filter(name=spec["name"]).first()
                    if test is None:
                        raise
                    t_created = False

                # Set / update provenance description with myQA metadata.
                self._update_test_description(
                    test,
                    spec["raw_name"],
                    taskname,
                    t_created,
                    spec.get("metadata", {}),
                )

                # Update enriched display name on existing Tests (e.g. after
                # enrichment rules change). Wrap in a savepoint + try/except
                # because Test.name has a UNIQUE constraint.
                if not t_created and test.name != spec["name"]:
                    try:
                        with transaction.atomic():
                            test.name = spec["name"]
                            test.save(update_fields=["name"])
                    except Exception:
                        pass  # Name collision — keep existing name

                if t_created:
                    counts["tests"] += 1
                created_tests.append(test)

                _, mb_created = TestListMembership.objects.get_or_create(
                    test_list=test_list,
                    test=test,
                    defaults={"order": i + 1},
                )
                if mb_created:
                    counts["memberships"] += 1

                # Collect mapping data for traceability document.
                self._mapping_rows.append(
                    {
                        "testlist_name": taskname,
                        "testlist_slug": list_slug,
                        "myqa_condition_name": spec["raw_name"],
                        "qatrack_test_name": spec["name"],
                        "test_slug": spec["slug"],
                        "execution_type": spec["type"],
                        "source_table": spec.get("source", ""),
                    }
                )

            # 4. UTC + UTI per unit that actually has data for this TaskName.
            ct = ContentType.objects.get_for_model(test_list)

            if not unit_numbers:
                self.stdout.write(
                    self.style.NOTICE(
                        "  No units with data — skipping UTC/UTI creation"
                    )
                )
                return counts

            units_for_list = list(Unit.objects.filter(number__in=unit_numbers))
            missing = set(unit_numbers) - {u.number for u in units_for_list}
            for missing_num in sorted(missing):
                self.stdout.write(
                    self.style.WARNING(
                        f"  Unit number {missing_num} not found — skipping"
                    )
                )
            if not units_for_list:
                return counts

            # Pre-fetch existing UTIs for the tests in this list so we can
            # skip them without per-unit queries (large task × unit combos).
            test_ids = [t.pk for t in created_tests]
            unit_ids = [u.pk for u in units_for_list]
            existing_uti_keys: set[tuple[int, int]] = set()
            for chunk in [test_ids[i : i + 500] for i in range(0, len(test_ids), 500)]:
                for uti in UnitTestInfo.objects.filter(
                    test_id__in=chunk, unit_id__in=unit_ids
                ):
                    existing_uti_keys.add((uti.unit_id, uti.test_id))

            utis_to_create: list[UnitTestInfo] = []
            for unit in units_for_list:
                # Surface device-classification misses so the centre knows to
                # extend myqa_centre_config.yaml. Per Change B design D7:
                # print to stderr so it's visible without disrupting stdout
                # parsing. Only "Unknown Device" (the YAML's fallback
                # unit_type) is checked — "Other" is a UnitClass name, not
                # a UnitType name, so it would never appear here.
                if unit.type and unit.type.name == "Unknown Device":
                    self.stderr.write(
                        self.style.WARNING(
                            f"  NOTICE: unit {unit.number} ({unit.name!r}) has "
                            f"type={unit.type.name!r} — fell through to "
                            f"device_classes fallback. Consider extending "
                            f"myqa_centre_config.yaml."
                        )
                    )
                utc, utc_created = UnitTestCollection.objects.get_or_create(
                    unit=unit,
                    frequency=freq,
                    content_type=ct,
                    object_id=test_list.pk,
                    defaults={
                        "active": True,
                        "auto_schedule": True,
                    },
                )
                if utc_created:
                    counts["utcs"] += 1
                    # Make visible to all groups so the UTC shows up in the
                    # review interface.
                    from django.contrib.auth.models import Group

                    utc.visible_to.set(Group.objects.all())

                for test in created_tests:
                    if (unit.pk, test.pk) in existing_uti_keys:
                        continue
                    # tolerance=None per spec myqa-dosimetry-tolerances R1.
                    utis_to_create.append(
                        UnitTestInfo(unit=unit, test=test, tolerance=None)
                    )

            if utis_to_create:
                UnitTestInfo.objects.bulk_create(
                    utis_to_create, ignore_conflicts=True, batch_size=1000
                )
                counts["utis"] += len(utis_to_create)

        return counts

    # ------------------------------------------------------------------
    # Provenance + mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_metadata_block(metadata: dict) -> str:
        """Format myQA metadata (description, tolerances) into a text block."""
        parts: list[str] = []
        test_step = metadata.get("test_step", "")
        category = metadata.get("category", "")
        desc = metadata.get("description", "")
        expected = metadata.get("expected")
        warn_on = metadata.get("warn_on")
        fail_on = metadata.get("fail_on")

        if test_step:
            label = f" [{category}]" if category else ""
            parts.append(f'Test step: "{test_step}"{label}')
        if desc:
            parts.append(desc)
        # Include tolerance reference values (informational only — actual
        # tolerances are configured per-unit in the QATrack+ admin).
        tol_parts: list[str] = []
        if expected is not None:
            tol_parts.append(f"expected={expected}")
        if warn_on is not None and warn_on != 0:
            tol_parts.append(f"warn=\u00b1{warn_on}")
        if fail_on is not None and fail_on != 0:
            tol_parts.append(f"fail=\u00b1{fail_on}")
        if tol_parts:
            parts.append("myQA tolerances: " + ", ".join(tol_parts))
        return "\n".join(parts)

    def _update_test_description(
        self,
        test: Test,
        raw_name: str,
        taskname: str,
        created: bool,
        metadata: dict | None = None,
    ) -> None:
        """Set or update ``Test.description`` with myQA provenance + metadata.

        Format on creation::
            myQA condition: '<raw>' (from TaskNames: '<tn>')
            Test step: "<step>" [<category>]
            <description from myQA>
            myQA tolerances: expected=X, warn=±Y, fail=±Z

        On existing Test: appends taskname if not listed. Also adds the
        metadata block if the test doesn't have one yet and we have data.
        """
        if metadata is None:
            metadata = {}

        meta_block = self._format_metadata_block(metadata)

        if created:
            lines = [f"myQA condition: '{raw_name}' (from TaskNames: '{taskname}')"]
            if meta_block:
                lines.append(meta_block)
            test.description = "\n".join(lines)
            test.save(update_fields=["description"])
            return

        desc = test.description or ""

        # If the test has no metadata block yet and we have one, add it.
        has_meta = "\n" in desc or "Test step:" in desc
        if not has_meta and meta_block:
            if "from TaskNames:" in desc:
                desc = desc + "\n" + meta_block
                test.description = desc
                test.save(update_fields=["description"])
            else:
                lines = [f"myQA condition: '{raw_name}' (from TaskNames: '{taskname}')"]
                if meta_block:
                    lines.append(meta_block)
                test.description = "\n".join(lines)
                test.save(update_fields=["description"])
            return

        # Already has metadata — just ensure the taskname is listed.
        if taskname in desc:
            return

        if "from TaskNames:" in desc:
            idx = desc.rfind(")")
            if idx > 0:
                test.description = desc[:idx].rstrip() + f", '{taskname}')"
                test.save(update_fields=["description"])
        else:
            lines = [f"myQA condition: '{raw_name}' (from TaskNames: '{taskname}')"]
            if meta_block:
                lines.append(meta_block)
            test.description = "\n".join(lines)
            test.save(update_fields=["description"])

    def _write_mapping_csv(self, docs_dir: str) -> None:
        """Write ``docs/myqa_test_mapping.csv`` — one row per TestListMembership."""
        os.makedirs(docs_dir, exist_ok=True)
        path = os.path.join(docs_dir, "myqa_test_mapping.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_MAPPING_COLUMNS)
            writer.writeheader()
            writer.writerows(self._mapping_rows)

    def _write_mapping_md(self, docs_dir: str) -> None:
        """Write ``docs/myqa_test_mapping.md`` — grouped by TestList."""
        os.makedirs(docs_dir, exist_ok=True)
        path = os.path.join(docs_dir, "myqa_test_mapping.md")
        rows_sorted = sorted(
            self._mapping_rows,
            key=lambda r: (r["testlist_slug"], r["test_slug"]),
        )
        with open(path, "w") as f:
            f.write("# myQA Test Mapping\n\n")
            f.write(
                "Auto-generated by `setup_myqa_tests`. Maps myQA condition "
                "names to QATrack+ Test names.\n\n"
            )
            for tl_slug, group in groupby(
                rows_sorted, key=lambda r: r["testlist_slug"]
            ):
                group_list = list(group)
                tl_name = group_list[0]["testlist_name"]
                f.write(f"## {tl_name}\n\n")
                f.write(f"`{tl_slug}`\n\n")
                f.write(
                    "| myQA Condition | QATrack+ Test Name | Slug | Type | Source |\n"
                )
                f.write("|---|---|---|---|---|\n")
                for row in group_list:
                    # Escape pipe characters in cell values for Markdown tables.
                    cells = [
                        row["myqa_condition_name"].replace("|", "\\|"),
                        row["qatrack_test_name"].replace("|", "\\|"),
                        row["test_slug"],
                        row["execution_type"],
                        row["source_table"],
                    ]
                    f.write("| " + " | ".join(cells) + " |\n")
                f.write("\n")
