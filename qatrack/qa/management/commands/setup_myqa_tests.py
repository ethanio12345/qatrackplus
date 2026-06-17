import json
import re
from typing import Dict, List, Optional

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import pymssql

from qatrack.qa.models import (
    Frequency, Test, TestList, TestListMembership,
    Tolerance, UnitTestCollection, UnitTestInfo,
)
from qatrack.myqa_import import (
    LINAC_MAP, MYQA_DB_SETTINGS, TASK_TYPE_REGISTRY,
    slugify_name,
)

FREQUENCY_MAP = {
    'daily': 'daily',
    'weekly': 'weekly',
    'monthly': 'monthly',
    'quarterly': 'quarterly',
    'annual': 'annual',
}


def get_or_create_tolerance(
    warn_on: Optional[float],
    fail_on: Optional[float],
    is_relative: bool = False,
    limit_tendency: int = 0,
    created_by=None,
) -> Optional[Tolerance]:
    if warn_on is None and fail_on is None:
        return None

    tol_type = 'percent' if is_relative else 'absolute'

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
        return None

    tol, _ = Tolerance.objects.get_or_create(
        type=tol_type,
        tol_low=tol_lower,
        tol_high=tol_upper,
        act_low=act_lower,
        act_high=act_upper,
        defaults={
            'created_by': created_by,
            'modified_by': created_by,
        },
    )
    return tol


def query_myqa_test_names(conn, task_name_patterns: List[str]) -> List[Dict]:
    names = []
    cursor = conn.cursor(as_dict=True)
    for pattern in task_name_patterns:
        cursor.execute("""
            SELECT DISTINCT tc.Name, tcne.WarningTolerance, tcne.ErrorTolerance,
                            tcne.BoundingType, tcne.IsRelative, tcne.LimitTendency
            FROM MQA_TestConditions tc
            JOIN MQA_Numeric_TestConditionExecutions tcne
                ON tc.Id = tcne.TestCondition_Id
            JOIN MQA_TestImplementationExecutions tie
                ON tcne.TestImplementationExecution_Id = tie.Id
            JOIN MQA_TestExecutions te ON tie.Id = te.Id
            WHERE te.TaskName LIKE %s
        """, (pattern,))
        for row in cursor.fetchall():
            names.append({
                'name': row['Name'],
                'warn': row['WarningTolerance'],
                'fail': row['ErrorTolerance'],
                'bounding': row['BoundingType'],
                'is_relative': row['IsRelative'],
                'limit_tendency': row['LimitTendency'],
            })
    return names


class Command(BaseCommand):
    help = 'One-time setup of myQA test lists, tests, tolerances, and unit collections'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview only, no database writes',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='Re-create existing test lists and tests if they already exist',
        )

    def handle(self, *args, **kwargs):
        dry_run = kwargs.get('dry_run', False)
        force = kwargs.get('force', False)

        internal_user = User.objects.get(username='QATrack+ Internal')

        conn = pymssql.connect(
            server=MYQA_DB_SETTINGS['server'],
            database=MYQA_DB_SETTINGS['database'],
            user=MYQA_DB_SETTINGS['username'],
            password=MYQA_DB_SETTINGS['password'],
        )

        results = {
            'test_lists': 0,
            'tests': 0,
            'tolerances': 0,
            'memberships': 0,
            'utcs': 0,
        }

        try:
            for task_key, importer_cls in TASK_TYPE_REGISTRY.items():
                importer = importer_cls()
                list_slug = importer.list_slug
                list_name = f'myQA {importer.execution_type} Import'
                frequency_slug = importer.frequency
                freq = Frequency.objects.get(slug=frequency_slug)

                self.stdout.write(f'\n--- Processing {list_slug} (freq={frequency_slug}) ---')

                if not importer.execution_type == 'Numeric':
                    self.stdout.write(f'  SKIP {list_slug}: non-numeric types need manual setup')
                    continue

                test_names = query_myqa_test_names(conn, importer.task_name_patterns)

                if not test_names:
                    self.stdout.write(f'  No test names found for {list_slug}')
                    continue

                self.stdout.write(f'  Found {len(test_names)} distinct test conditions')

                if dry_run:
                    self.stdout.write(f'  DRY RUN: would create test_list={list_slug}, {len(test_names)} tests')
                    continue

                test_list, tl_created = TestList.objects.get_or_create(
                    slug=list_slug,
                    defaults={
                        'name': list_name,
                        'description': f'Auto-created test list for myQA {importer.execution_type} imports',
                    },
                )
                if not tl_created and force:
                    TestListMembership.objects.filter(test_list=test_list).delete()
                    Test.objects.filter(slug__startswith=f'{list_slug}_').delete()
                    test_list.name = list_name
                    test_list.save()
                elif not tl_created:
                    self.stdout.write(f'  TestList {list_slug} already exists (use --force to re-create)')
                    continue

                results['test_lists'] += 1

                taskid_test, _ = Test.objects.get_or_create(
                    slug=f'{list_slug}_taskid',
                    defaults={
                        'name': f'{list_slug} Task ID',
                        'type': 'string',
                        'category_id': 1,
                        'created_by': internal_user,
                        'modified_by': internal_user,
                    },
                )
                TestListMembership.objects.get_or_create(
                    test_list=test_list,
                    test=taskid_test,
                    defaults={'order': 0},
                )
                results['tests'] += 1
                results['memberships'] += 1

                for i, tn in enumerate(test_names):
                    slug = slugify_name(list_slug, tn['name'])
                    test, t_created = Test.objects.get_or_create(
                        slug=slug,
                        defaults={
                            'name': tn['name'],
                            'type': 'numerical',
                            'category_id': 1,
                            'created_by': internal_user,
                            'modified_by': internal_user,
                        },
                    )
                    if t_created:
                        results['tests'] += 1

                    tol = get_or_create_tolerance(
                        warn_on=tn['warn'],
                        fail_on=tn['fail'],
                        is_relative=bool(tn['is_relative']),
                        limit_tendency=tn['limit_tendency'],
                        created_by=internal_user,
                    )
                    if tol is not None:
                        results['tolerances'] += 1

                    TestListMembership.objects.get_or_create(
                        test_list=test_list,
                        test=test,
                        defaults={'order': i + 1},
                    )
                    results['memberships'] += 1

                for unit_num in LINAC_MAP:
                    utc, utc_created = UnitTestCollection.objects.get_or_create(
                        unit__number=unit_num,
                        frequency=freq,
                        content_type__app_label='qa',
                        content_type__model='testlist',
                        object_id=test_list.pk,
                        defaults={
                            'active': True,
                            'auto_schedule': True,
                        },
                    )
                    if utc_created:
                        results['utcs'] += 1

                importer.close()

        finally:
            conn.close()

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {results["test_lists"]} test lists, {results["tests"]} tests, '
            f'{results["tolerances"]} tolerances, {results["memberships"]} memberships, '
            f'{results["utcs"]} UTCs created'
        ))
