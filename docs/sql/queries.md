myQA Query Patterns Reference
=============================

This document explains the SQL query patterns used throughout
``qatrack/myqa_import.py`` and why they are structured the way they are.
Other sites can adapt these queries for their own myQA databases.


Table of Contents
-----------------

1. `Discover vs Extract: Two Query Modes`_
2. `The multi Flag: TaskName-Level vs Session-Level`_
3. `Pattern A Queries (Numeric, PassFail, Profile, Wedge, Output, Energy)`_
4. `Pattern B Queries (MLC, CBCT, Planar)`_
5. `Pattern C Queries (VMAT)`_
6. `Pattern D Queries (Winston-Lutz)`_
7. `Shared FROM/JOIN Constants`_
8. `Session Discovery (query_sessions)`_
9. `Condition Metadata (discover_condition_metadata)`_
10. `Pattern B Dynamic Column Generation`_
11. `Tolerance & Reference Processing`_
12. `FK-Safe Deletion (clear_myqa_data)`_


Discover vs Extract: Two Query Modes
-------------------------------------

Every execution type has two query variants:

- **Discover** (``WHERE te.TaskName = %s``): Runs during ``setup_myqa_tests``
  to discover what conditions exist for a TaskName across **all sessions**.
  Used to create Test objects and TestListMemberships.

- **Extract** (``WHERE te.TaskExecutionId = %s``): Runs during ``import_myqa``
  to fetch actual measurement values for **one specific session**.

Both use the same FROM/JOIN block (defined as ``_*_FROM`` constants), differing
only in the WHERE clause and SELECT columns. This ensures that condition names
produced during discovery match exactly those produced during extraction.


The multi Flag: TaskName-Level vs Session-Level
------------------------------------------------

Some execution types prefix condition names with the test step name when
multiple test steps exist (e.g. ``"6MV Flatness"`` vs ``"10MV Flatness"``).

**The problem**: If a TaskName has sessions with different test steps across
its history (e.g. some sessions measured 6MV only, others measured 6MV+10MV),
the ``multi`` flag computed at session level differs from the TaskName level.
This caused ~5% of conditions to silently drop during import.

**The solution**: ``compute_multi_flags(conn, taskname)`` queries the DISTINCT
test steps across **all sessions** for a TaskName. The result is passed to
extractors via ``multi_override``, ensuring prefixing is consistent between
discovery and extraction.

.. code-block:: sql

   -- Example: does the "Dosimetry - Monthly QA" TaskName have multiple
   -- Numeric test steps across ALL sessions?
   SELECT DISTINCT te.Name AS test_step
   FROM MQA_Numeric_TestConditionExecutions tcne
   JOIN MQA_TestImplementationExecutions tie
       ON tcne.NumericTestExecution_Id = tie.Id
   JOIN MQA_TestExecutions te ON tie.Id = te.Id
   WHERE te.TaskName = '5.Tmt.Linac.M.Dosimetry - Monthly QA'
     AND te.State != 10


Pattern A Queries
-----------------

Numeric
~~~~~~~

**Discover**: Returns ``DISTINCT (Name, test_step)`` so conditions can be
energy-prefixed when ``multi=True``. Excludes ``State=10`` (not started).

.. code-block:: sql

   SELECT DISTINCT tcne.Name, te.Name AS test_step
   FROM MQA_Numeric_TestConditionExecutions tcne
   JOIN MQA_TestImplementationExecutions tie
       ON tcne.NumericTestExecution_Id = tie.Id
   JOIN MQA_TestExecutions te ON tie.Id = te.Id
   WHERE te.TaskName = %s AND tcne.Name IS NOT NULL AND te.State != 10
   ORDER BY tcne.Name

**Extract**: Same JOIN, but selects ``Actual``, ``State``, tolerance columns.
Filters by ``TaskExecutionId`` for one session.

PassFail
~~~~~~~~

PassFail tests have no separate condition names — the ``MQA_TestExecutions.Name``
(test step name) IS the condition name. The ``AcceptanceCriteria`` column holds
the free-text result.

Profile
~~~~~~~

Profile results have a ``DisplayName`` and ``ProfileDirection`` (1=crossline,
2=inline). The condition name is built by ``_profile_condition_name()`` which
appends ``(crossline)`` or ``(inline)`` when not already in the display name.

The 3-table JOIN chain is::

    MQA_Dosimetry_Profile_Results dpr
    → MQA_Dosimetry_Profile_QueueItemExecutions dpqie (via ProfileQueueItemExecution_Id)
    → MQA_Dosimetry_Profile_TestExecutions dpte (via ProfileQueueItem_Id)
    → MQA_TestImplementationExecutions tie
    → MQA_TestExecutions te

Wedge / Output / Energy
~~~~~~~~~~~~~~~~~~~~~~~~

These dosimetry types don't have a ``DisplayName`` column. Instead, condition
names are derived from the ``BeamQuality_EnergyValue`` (an integer like ``6``
for 6MV). The naming convention is:

- Wedge: ``"Wedge Constancy {energy}x"``
- Output: ``"Output {energy}x"``
- Energy: ``"Energy {energy}{fff?} ch{chamber}"`` (includes FFF flag and chamber number)

Output and Energy both join ``MQA_Dosimetry_Common_QueueItemExecutions`` for
energy metadata.


Pattern B Queries (MLC, CBCT, Planar)
--------------------------------------

Pattern B tables are denormalised: all metrics for a session are in a single
wide row with prefixed column names. The naming convention is::

    <MetricName>_Result_Value_Value                        — measured value
    <MetricName>_AcceptanceCriterion_ExpectedValue_Value   — expected value
    <MetricName>_AcceptanceCriterion_Tolerances_Warn_Value  — warn tolerance
    <MetricName>_AcceptanceCriterion_Tolerances_Fail_Value  — fail tolerance

The ``_discover_pattern_b_conditions`` and ``_extract_pattern_b`` functions
are generic — they accept ``metrics``, ``results_table``, ``exec_table``, etc.
as parameters. The per-type wrappers just pass the appropriate column maps:

.. code-block:: python

   _MLC_METRICS = {
       "Failing Peaks": "FailingPeaks_Result_Value_Value",
       "Maximum Deviation": "MaximumDeviation_Result_Value_Value",
       ...
   }

When ``multi=True``, each metric is prefixed with the test step descriptor
(e.g. ``"Gantry Speed/Dose Rate Control (Ling T2) Failing Peaks"``).

**Important**: Discover returns ``[]`` when there are zero test steps for that
TaskName, preventing spurious conditions from appearing in unrelated TestLists.


Pattern C Queries (VMAT)
------------------------

VMAT has a parent-child structure: one ``NormalizationValueResult`` per test
step, plus multiple ROI child rows (``Mean``, ``StandardDeviation``) joined via
``MQA_MDL_VmatDmlc_RoiResults``.

The parent name (``"Normalization Value"``) is **never prefixed**, even when
``multi=True``, because it's a single shared Test. ROI names ARE prefixed.


Pattern D Queries (Winston-Lutz)
--------------------------------

Winston-Lutz is the simplest type: it directly inherits
``MQA_TestImplementationExecutions`` with no separate results table. The two
metrics (``MaximumDeviation2D``, ``Deviation3D``) are direct columns on the
execution table.


Shared FROM/JOIN Constants
--------------------------

To prevent SQL drift between discover and extract, each Pattern A type's
FROM/JOIN block is defined once as a module-level constant:

.. code-block:: python

   _NUMERIC_FROM = """
       FROM MQA_Numeric_TestConditionExecutions tcne
       JOIN MQA_TestImplementationExecutions tie
           ON tcne.NumericTestExecution_Id = tie.Id
       JOIN MQA_TestExecutions te ON tie.Id = te.Id"""

Both ``discover_numeric_conditions`` and ``extract_numeric`` reference this
constant via f-string::

   rows = _fetchall(conn, f"""
       SELECT DISTINCT tcne.Name, te.Name AS test_step
       {_NUMERIC_FROM}
       WHERE te.TaskName = %s
   """, (taskname,))

This ensures that if a schema change requires modifying a JOIN, only one
constant needs updating — not three copies (discover, extract, multi-flag).


Session Discovery (query_sessions)
-----------------------------------

During import, ``query_sessions`` finds all sessions for a TaskName within a
date range. It uses ``DISTINCT`` because ``MQA_TestExecutions`` has one row
per test implementation within a session — the same ``TaskExecutionId``
appears in multiple rows (one per execution type).

.. code-block:: sql

   SELECT DISTINCT te.TaskExecutionId, te.ReferenceDate, te.FinishingDate,
          te.TaskName, te.RadiationDeviceName
   FROM MQA_TestExecutions te
   WHERE te.TaskName = %s
     AND te.ReferenceDate IS NOT NULL
     AND te.ReferenceDate >= %s    -- cutoff date (now - days)
     AND te.ReferenceDate <= %s    -- now
   ORDER BY te.ReferenceDate, te.FinishingDate

After fetching, each row's ``RadiationDeviceName`` is resolved to a QATrack+
unit number via ``LINAC_MAP``. Sessions with unknown devices (not in the
map) are silently skipped.

**Why DISTINCT**: Session-level fields (TaskName, RadiationDeviceName,
ReferenceDate) are denormalised — identical across all test implementation
rows for the same session. DISTINCT collapses them to one row per session.


Condition Metadata (discover_condition_metadata)
-------------------------------------------------

During setup, this query fetches descriptive metadata for Numeric conditions.
The result populates ``Test.description`` with provenance info.

.. code-block:: sql

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

**Deduplication**: When the same condition name appears in multiple test
steps (e.g. different energies), the query prefers rows with non-empty
descriptions over empty ones.


Pattern B Dynamic Column Generation
------------------------------------

The ``_extract_pattern_b`` function builds its SELECT clause dynamically
from the metric column map. For each metric, it checks if the column name
ends with ``_Result_Value_Value`` or ``_Value``, then derives the
tolerance column names by replacing the suffix:

.. code-block:: text

   Metric column:     FailingPeaks_Result_Value_Value
                        ^^^^^^^^^^^^^^^^ ^^^^^^^^^^^^^
                        prefix            suffix

   Derived tolerance columns:
     {prefix}_AcceptanceCriterion_ExpectedValue_Value   → expected
     {prefix}_AcceptanceCriterion_Tolerances_Warn_Value  → warn tolerance
     {prefix}_AcceptanceCriterion_Tolerances_Fail_Value  → fail tolerance

The final SELECT is built as::

   SELECT te.Name AS test_step,
          r.FailingPeaks_Result_Value_Value,
          r.FailingPeaks_AcceptanceCriterion_ExpectedValue_Value,
          r.FailingPeaks_AcceptanceCriterion_Tolerances_Warn_Value,
          r.FailingPeaks_AcceptanceCriterion_Tolerances_Fail_Value,
          r.MaximumDeviation_Result_Value_Value,
          ...
   FROM MQA_MDL_MlcQA_Results r
   JOIN MQA_MDL_MlcQA_TestExecutions mte ON r.MlcQATestExecutionBase_Id = mte.Id
   JOIN MQA_TestImplementationExecutions tie ON mte.Id = tie.Id
   JOIN MQA_TestExecutions te ON tie.Id = te.Id
   WHERE te.TaskExecutionId = %s

Value-only columns (``_MLC_VALUE_ONLY``, ``_CBCT_VALUE_ONLY``) and string
columns (``_MLC_STRING``) are included in the SELECT but don't get tolerance
columns derived.


Tolerance & Reference Processing
---------------------------------

### Tolerance creation (_get_or_create_tolerance)

myQA stores tolerances as symmetric absolute or relative (fractional) values.
QATrack+ uses a 4-value symmetric Tolerance model (act_low, tol_low,
tol_high, act_high).

.. code-block:: python

   # myQA: WarnOn=0.3, FailOn=0.5, IsRelative=True
   # → QATrack+ Percent tolerance:
   #   act_low=-0.5, tol_low=-0.3, tol_high=0.3, act_high=0.5

   # myQA: WarnOn=0.3, FailOn=0.5, IsRelative=False
   # → QATrack+ Absolute tolerance:
   #   act_low=-0.5, tol_low=-0.3, tol_high=0.3, act_high=0.5

**Relative conversion**: myQA stores relative tolerances as fractions
(0.015 = 1.5%). QATrack+ stores them as percentages (1.5 = 1.5%). The
conversion multiplies by 100.

Tolerances are ``get_or_create``'d — shared across all units/tests with the
same values.

### Reference creation (_get_or_create_reference)

The myQA ``Expected`` value becomes a QATrack+ ``Reference`` of type
``absolute``. References are also ``get_or_create``'d by value.

### Pass/fail computation (_compute_pass_fail)

.. code-block:: python

   if relative:
       deviation = abs(value - expected) / abs(expected) * 100
       warn_limit = warn * 100
       fail_limit = fail * 100
   else:
       deviation = abs(value - expected)
       warn_limit = warn
       fail_limit = fail

   if deviation <= warn_limit:   → "ok"
   elif deviation <= fail_limit: → "tolerance"
   else:                          → "action"

**Edge case**: When ``expected == 0`` and tolerances are relative, division
by zero would occur. This returns ``"no_tol"`` (no tolerance applied).

**Missing tolerances**: If any of (expected, warn, fail) is None, returns
``"no_tol"`` — the TestInstance is created without pass/fail status.


FK-Safe Deletion (clear_myqa_data)
-----------------------------------

The ``clear_myqa_data`` command deletes all myQA-sourced data in a specific
order to avoid FK constraint violations. The 11-step sequence:

1. Null out ``UnitTestCollection.last_instance`` for affected UTCs
2. Delete ``TestInstance`` rows under affected TestListInstances
3. Delete ``TestListInstance`` rows for affected TestLists
4. Delete ``UnitTestInfoChanges`` referencing affected UTIs
5. Delete ``UnitTestInfo`` rows for affected Tests
6. Clear ``UnitTestCollection.visible_to`` M2M for affected UTCs
7. Delete ``UnitTestCollection`` rows pointing at affected TestLists
8. Delete ``TestListMembership`` rows for affected TestLists
9. Delete ``Attachments`` attached to affected objects
10. Delete ``Test`` rows by membership / slug prefix
11. Delete ``TestList`` rows by description pattern

**Identification**: myQA TestLists are identified by the description prefix
``"Auto-created TestList for myQA TaskName"`` (set by ``setup_myqa_tests``).
Tests are identified by membership in those TestLists or slug prefixes
``myqa_`` / ``mtx_``.


Adapting These Queries for Other Sites
---------------------------------------

To use these queries against your own myQA database:

1. **Verify table names**: Check that your myQA version uses the same
   ``MQA_*`` table naming convention. Older versions may use different names.

2. **Verify column names**: The Pattern B column prefixes
   (``_Result_Value_Value``, ``_AcceptanceCriterion_*``) may differ between
   myQA template versions. Compare against your database.

3. **Update the device map**: Edit ``myqa_device_map.yaml`` with your
   institution's device names and QATrack+ unit numbers.

4. **Test with --dry-run**: Always run ``setup_myqa_tests --dry-run`` first
   to verify condition discovery before creating any database objects.
