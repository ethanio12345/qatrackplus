myQA → QATrack+ Data Mapping
=============================

This document explains how myQA data maps to QATrack+ models.


Overview
--------

.. code-block:: text

   myQA SQL Server                     QATrack+ PostgreSQL
   ───────────────                     ────────────────────
   TaskName (protocol name)    ──→     TestList (name = TaskName verbatim)
                                            ↓
   Condition (per execution       ──→  Test (shared by slug across TestLists)
   type result column)                  ↓
                                        TestListMembership (links Test to TestList)
                                            ↓
   RadiationDeviceName          ──→     Unit (mapped via device_map.yaml)
                                        ↓
                                        UnitTestCollection (UTC = Unit × TestList × frequency)
                                        ↓
                                        UnitTestInfo (UTI = Unit × Test)
                                            ↓
   One session (TaskExecutionId) ──→    TestListInstance (one per session)
                                        ↓
   Individual measurements       ──→    TestInstance (one per condition × session)


Mapping Rules
-------------


1. One TestList per TaskName (D1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each myQA ``TaskName`` becomes exactly one QATrack+ ``TestList``. The
TestList name is the TaskName verbatim. The slug is ``slugify(TaskName)``.

Example::

    TaskName: "5.Tmt.Linac.M.Dosimetry - Monthly QA"
    TestList.name: "5.Tmt.Linac.M.Dosimetry - Monthly QA"
    TestList.slug: "5_tmt_linac_m_dosimetry_monthly_qa"


2. Tests shared by condition name (D2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests are created by ``slugify(raw_condition_name)`` — no TestList prefix.
The same condition name across different TaskNames maps to the **same** Test,
shared via ``TestListMembership``.

Example::

    TaskName A: "Monthly QA" has condition "Flatness" → slug "flatness"
    TaskName B: "Annual QA" has condition "Flatness" → same slug "flatness"
    → One Test object, linked to both TestLists

Duplicate condition names within a single TaskName are disambiguated with
``_2``, ``_3`` suffixes on the slug.


3. Display name enrichment (D3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``Test.name`` (display name) is enriched for readability:

1. Strip leading number prefix (``"01. Temperature"`` → ``"Temperature"``)
2. Expand abbreviations (``Vrt`` → ``Vertical``, ``SN`` → ``Serial Number``)
3. Apply YAML override from ``myqa_name_overrides.yaml`` if matching

The **slug** is always derived from the **raw** condition name (before
enrichment) so that FK references don't break when enrichment rules change.


4. One TestListInstance per session (D4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each myQA session (identified by ``TaskExecutionId``) produces exactly one
``TestListInstance`` that aggregates results from **all** execution types
present in the session (Numeric, PassFail, Profile, etc.).

A dedup ``TestInstance`` stores the ``TaskExecutionId`` UUID as a string
value, keyed by the Test with slug ``{list_slug}_taskid``.


5. Tolerances imported per-unit (not per-Test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since Tests are shared across TaskLists, tolerances cannot be set on the Test
itself (different tasks may have different tolerances for the same condition).
Instead, tolerances are set on ``UnitTestInfo`` (per-unit, per-Test):

- ``Tolerance`` objects are created from myQA's ``WarnOn``/``FailOn`` values
- ``Reference`` objects are created from myQA's ``Expected`` value
- Both are ``get_or_create``'d (shared across units with same values)
- Applied to the UTI during import (latest import wins)


6. State mapping
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - myQA State
     - QATrack+ Action
     - Description
   * - ``10``
     - ``skip``
     - Not started — TestInstance not created
   * - ``30``
     - ``unreviewed``
     - Incomplete — imported with default (unreviewed) status
   * - ``40``
     - ``approved``
     - Completed — imported with Approved status
   * - ``50``
     - ``approved``
     - Approved — same as completed
   * - ``60``
     - ``skipped``
     - Skipped — TestInstance created with Skipped status

Only Numeric and PassFail types carry per-test ``State`` values. All other
execution types (Profile, Wedge, etc.) are treated as State=40 (completed).


7. Pass/fail computation
~~~~~~~~~~~~~~~~~~~~~~~~

For conditions with tolerances, QATrack+ computes a pass_fail status:

- ``ok``: value within warn tolerance
- ``tolerance``: value exceeds warn but within fail tolerance
- ``action``: value exceeds fail tolerance
- ``no_tol``: no tolerances configured

Relative tolerances (``IsRelative=True``) are stored as fractions in myQA
(0.03 = 3%) but as percentages in QATrack+ (3.0 = 3%).


8. Frequency inference
~~~~~~~~~~~~~~~~~~~~~~

Frequency is inferred from the TaskName's dotted path notation:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Pattern
     - Frequency
     - Example
   * - ``.D`` or ``.d``
     - daily
     - ``5.Tmt.Linac.D - Daily QA``
   * - ``.W`` or ``.w``
     - weekly
     - ``5.Tmt.ET.W - Weekly QA``
   * - ``.M`` or ``.m``
     - monthly
     - ``5.Tmt.Linac.M - Monthly``
   * - ``.Q`` or ``.q``
     - quarterly
     - ``5.Tmt.Linac.Q - Quarterly``
   * - ``.Y`` or ``.y``
     - annual
     - ``5.Tmt.Linac.Y - Annual QA``
   * - ``.6M``
     - semi-annual
     - ``5.Tmt.Linac.6M - 6 Monthly``
   * - *(no match)*
     - once_off
     - Audit/test TaskNames


Device Name Resolution
----------------------

The ``RadiationDeviceName`` in myQA identifies the physical device. The
mapping to QATrack+ ``Unit.number`` is defined in
``myqa_device_map.yaml``::

    1: "CST15 - H192361"
    3:
      - "LA317 - H192972"
      - "Exactrac_LA317"
      - "LA317"

A list value means the device was renamed over time — all aliases map to
the same unit number. Devices not in the map are silently skipped during
import.

Sessions with no recognizable device are skipped entirely (they won't
appear in ``query_sessions`` results).
