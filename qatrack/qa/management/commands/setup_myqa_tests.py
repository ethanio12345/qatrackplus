from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from qatrack.myqa_import import (
    TASK_TYPE_REGISTRY,
    UNITS_PER_LIST,
)
from qatrack.qa.models import (
    Frequency,
    Test,
    TestList,
    TestListMembership,
    Tolerance,
    UnitTestCollection,
    UnitTestInfo,
)
from qatrack.units.models import Unit


def get_or_create_tolerance(
    warn_on: float | None,
    fail_on: float | None,
    is_relative: bool = False,
    limit_tendency: int = 0,
    created_by=None,
) -> Tolerance | None:
    """Create or fetch a QATrack+ Tolerance mirroring myQA WarnOn/FailOn.

    ``limit_tendency``: 0=two-sided, 1=lower-only, 2=upper-only. Any other
    value returns None (caller creates the Test with no Tolerance). Mirrors
    myqa_import.myqa_to_qatrack_tolerance but also sets audit fields.
    """
    if warn_on is None and fail_on is None:
        return None

    tol_type = "percent" if is_relative else "absolute"

    if limit_tendency == 0:
        tol_lower = -(warn_on or 0)
        tol_upper = +(warn_on or 0)
        act_lower = -(fail_on or 0)
        act_upper = +(fail_on or 0)
    elif limit_tendency == 1:
        tol_lower = -(fail_on or 0)
        tol_upper = None
        act_lower = -(fail_on or 0)
        act_upper = None
    elif limit_tendency == 2:
        tol_lower = None
        tol_upper = fail_on
        act_lower = None
        act_upper = fail_on
    else:
        # specs/numeric/spec.md "LimitTendency out of range" — Test is created
        # with no Tolerance.
        return None

    tol, _ = Tolerance.objects.get_or_create(
        type=tol_type,
        tol_low=tol_lower,
        tol_high=tol_upper,
        act_low=act_lower,
        act_high=act_upper,
        defaults={
            "created_by": created_by,
            "modified_by": created_by,
        },
    )
    return tol


class Command(BaseCommand):
    help = "One-time setup of myQA test lists, tests, tolerances, and unit collections"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview only, no database writes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help=(
                "Re-create existing test lists and tests if they already exist. "
                "DANGEROUS on main-spec lists (myqa_daily_*, myqa_dxr_daily): "
                "deletes existing Tests/TestListMemberships whose slug starts "
                "with the list slug. Verify no production TestListInstances "
                "reference these slugs before running."
            ),
        )
        parser.add_argument(
            "--task-type",
            default=None,
            help="Only run setup for this TASK_TYPE_REGISTRY key (default: all)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)
        only_task_type = options.get("task_type")

        internal_user = User.objects.get(username="QATrack+ Internal")

        totals = {
            "test_lists": 0,
            "tests": 0,
            "tolerances": 0,
            "memberships": 0,
            "utcs": 0,
            "utis": 0,
        }

        for task_key, importer_cls in TASK_TYPE_REGISTRY.items():
            if only_task_type and task_key != only_task_type:
                continue

            self.stdout.write(
                self.style.MIGRATE_HEADING(f"\n--- Processing {task_key} (list={importer_cls.list_slug}) ---")
            )

            with importer_cls() as importer:
                counts = self._setup_one_importer(
                    importer,
                    task_key=task_key,
                    internal_user=internal_user,
                    dry_run=dry_run,
                    force=force,
                )

            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {totals['test_lists']} test lists, {totals['tests']} tests, "
                f"{totals['tolerances']} tolerances, {totals['memberships']} memberships, "
                f"{totals['utcs']} UTCs, {totals['utis']} UTIs created"
            )
        )

    def _setup_one_importer(
        self,
        importer,
        task_key: str,
        internal_user,
        dry_run: bool,
        force: bool,
    ) -> dict[str, int]:
        """Run setup for a single importer. Returns a counts dict."""
        counts = {
            "test_lists": 0,
            "tests": 0,
            "tolerances": 0,
            "memberships": 0,
            "utcs": 0,
            "utis": 0,
        }

        list_slug = importer.list_slug
        list_name = f"myQA {importer.execution_type} Import"

        # --- 1. Discover test specs from the importer (per-type dispatch). ---
        try:
            specs = importer.discover_setup_tests()
        except NotImplementedError:
            self.stdout.write(f"  SKIP {list_slug}: setup not implemented for this type")
            return counts

        if not specs:
            self.stdout.write(f"  SKIP {list_slug}: no test specs (setup not implemented or no source data)")
            return counts

        self.stdout.write(f"  Found {len(specs)} test specs")
        if dry_run:
            for spec in specs:
                tol_tag = ""
                if spec.get("warn") is not None or spec.get("fail") is not None:
                    tol_tag = f" warn={spec.get('warn')} fail={spec.get('fail')}"
                self.stdout.write(f"    - {spec['slug']} ({spec['type']}){tol_tag}")
            return counts

        # --- 2. Resolve Frequency early so a bad slug fails fast. ---
        freq = Frequency.objects.get(slug=importer.frequency)

        # --- 3. TestList (with --force safety per design.md M1 table). ---
        test_list, tl_created = TestList.objects.get_or_create(
            slug=list_slug,
            defaults={
                "name": list_name,
                "description": f"Auto-created test list for myQA {importer.execution_type} imports",
                "created_by": internal_user,
                "modified_by": internal_user,
            },
        )
        if not tl_created and force:
            # Design `--force` safety: deletes TestListMemberships and Tests by
            # slug prefix. Per-list risk: main-spec lists (myqa_daily_constancy,
            # myqa_daily_physics, myqa_dxr_daily) WILL lose existing data.
            # Order matters: UTIs PROTECT Tests (UnitTestInfo.test FK is
            # on_delete=PROTECT), so UTIs must be deleted first.
            TestListMembership.objects.filter(test_list=test_list).delete()
            old_test_ids = Test.objects.filter(slug__startswith=f"{list_slug}_").values_list("pk", flat=True)
            UnitTestInfo.objects.filter(test_id__in=old_test_ids).delete()
            Test.objects.filter(slug__startswith=f"{list_slug}_").delete()
            test_list.name = list_name
            test_list.save()
        elif not tl_created:
            self.stdout.write(self.style.WARNING(f"  TestList {list_slug} already exists (use --force to re-create)"))
            return counts

        counts["test_lists"] += 1

        with transaction.atomic():
            # --- 4. Dedup `taskid` Test + membership (order=0). ---
            taskid_test, taskid_created = Test.objects.get_or_create(
                slug=f"{list_slug}_taskid",
                defaults={
                    "name": f"{list_slug} Task ID",
                    "type": "string",
                    "category_id": 1,
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

            # --- 5. Per-spec: Test + Tolerance + TestListMembership. ---
            # Engine silently drops TestInstances for slugs lacking a Test
            # (myqa_import.py:209-211), so the importer's emitted slugs MUST
            # all have Tests created here.
            created_tests: list[Test] = [taskid_test]
            for i, spec in enumerate(specs):
                test, t_created = Test.objects.get_or_create(
                    slug=spec["slug"],
                    defaults={
                        "name": spec.get("name") or spec["slug"],
                        "type": spec.get("type", "numerical"),
                        "category_id": 1,
                        "created_by": internal_user,
                        "modified_by": internal_user,
                    },
                )
                if t_created:
                    counts["tests"] += 1
                created_tests.append(test)

                tol = get_or_create_tolerance(
                    warn_on=spec.get("warn"),
                    fail_on=spec.get("fail"),
                    is_relative=bool(spec.get("is_relative", False)),
                    limit_tendency=int(spec.get("limit_tendency", 0) or 0),
                    created_by=internal_user,
                )
                if tol is not None:
                    counts["tolerances"] += 1

                _, mb_created = TestListMembership.objects.get_or_create(
                    test_list=test_list,
                    test=test,
                    defaults={"order": i + 1},
                )
                if mb_created:
                    counts["memberships"] += 1

            # --- 6. UTC + UTI per unit (per UNITS_PER_LIST, design M8). ---
            # Critical: the engine's import_session (myqa_import.py:186,213)
            # silently drops every TestInstance if a UTI is missing, so UTI
            # creation is REQUIRED (not optional) for the import path to work.
            ct = ContentType.objects.get_for_model(test_list)
            units_for_list = UNITS_PER_LIST.get(list_slug, [1, 2, 3, 4, 5, 7, 8])
            for unit_num in units_for_list:
                unit = Unit.objects.filter(number=unit_num).first()
                if unit is None:
                    self.stdout.write(
                        self.style.WARNING(f"  Unit number {unit_num} not found — skipping UTC/UTIs for it")
                    )
                    continue

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

                for test in created_tests:
                    _, uti_created = UnitTestInfo.objects.get_or_create(
                        unit=unit,
                        test=test,
                        defaults={
                            "created_by": internal_user,
                            "modified_by": internal_user,
                        },
                    )
                    if uti_created:
                        counts["utis"] += 1

        return counts
