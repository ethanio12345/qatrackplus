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
