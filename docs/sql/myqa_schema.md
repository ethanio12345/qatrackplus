myQA Database Schema Reference
==============================

This document describes the SQL Server database schema used by the myQA
QA management system (version 2020+). QATrack+ imports session data from
this database via ``pymssql`` (TDS protocol).

All table names are prefixed with ``MQA_``. The schema is normalised with
a base execution table and specialised sub-tables per measurement type.

Core Tables
-----------

MQA_TestExecutions
~~~~~~~~~~~~~~~~~~

The central table. Every QA session execution has one or more rows here.

==============================  ==================================================
Column                          Description
==============================  ==================================================
``Id``                          UUID primary key
``TaskName``                    The QA protocol name (e.g. ``"5.Tmt.Linac.M.Dosimetry - Monthly QA"``)
``TaskExecutionId``             UUID identifying a specific session run (shared across all execution types in the session)
``Name``                        Test step name (e.g. ``"6MV_6 MV_200x200 mm_100 MU"`` or ``"5.Tmt.Linac.M.M6 - Gantry angle indicators"``)
``RadiationDeviceName``         Device identifier (maps to QATrack+ Unit via ``myqa_device_map.yaml``)
``State``                       Execution state: ``10``=not started, ``30``=incomplete, ``40``=completed, ``50``=approved, ``60``=skipped
``ProtocolName``                Template/protocol version string
``ReferenceDate``               Date the QA was performed
``FinishingDate``               Date the QA was completed
``Description``                 Free-text description (used for Test.description)
``Category``                    Category label
==============================  ==================================================

**Key relationships**: ``TaskName`` identifies which TestList a session belongs
to. ``TaskExecutionId`` groups all execution types within a single session
(Numeric, PassFail, Profile, etc.). ``Name`` (test step) is used for
energy/parameter prefixing when multiple test steps exist.

MQA_TestImplementationExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Join table linking specialised execution tables (Numeric, PassFail, etc.) to
the base ``MQA_TestExecutions``. Each specialised table has an ``Id`` column
that is a foreign key to ``MQA_TestImplementationExecutions.Id``, which in turn
joins to ``MQA_TestExecutions`` via ``MQA_TestImplementationExecutions.Id``.

This two-level join means every specialised query follows the pattern::

    FROM MQA_<Type>_<Table> t
    JOIN MQA_TestImplementationExecutions tie ON t.<fk> = tie.Id
    JOIN MQA_TestExecutions te ON tie.Id = te.Id
    WHERE te.TaskExecutionId = %s   -- or te.TaskName = %s


Pattern A: Per-Condition Tables
-------------------------------

These execution types store one row per measured condition (normalised).

MQA_Numeric_TestConditionExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Numeric measurements (the most common type). One row per condition per session.

==============================  ==================================================
Column                          Description
==============================  ==================================================
``Id``                          UUID PK
``NumericTestExecution_Id``     FK to ``MQA_TestImplementationExecutions.Id``
``Name``                        Condition name (e.g. ``"Flatness"``, ``"01. Temperature"``)
``Actual``                      Measured value (float, may be NULL)
``Expected``                    Expected/reference value
``WarnOn``                      Warning tolerance (absolute or fractional)
``FailOn``                      Failure tolerance
``IsRelative``                  Boolean: if true, WarnOn/FailOn are fractions (0.03 = 3%)
==============================  ==================================================

MQA_PassFail_TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pass/fail qualitative tests. The entire execution is one condition.

==============================  ==================================================
Column                          Description
==============================  ==================================================
``Id``                          UUID PK (= ``MQA_TestImplementationExecutions.Id``)
``AcceptanceCriteria``          Free-text pass/fail result (e.g. ``"Functional"``, ``"Pass"``)
==============================  ==================================================

The ``Name`` column comes from ``MQA_TestExecutions.Name`` (the test step name).


Pattern B: Denormalised Wide-Row Tables
---------------------------------------

These execution types store ALL metrics for a session in a single wide row
with prefixed column names. Each metric has a value column and optionally
tolerance columns with a predictable naming convention::

    <MetricName>_Result_Value_Value       — the measured value
    <MetricName>_AcceptanceCriterion_ExpectedValue_Value  — expected
    <MetricName>_AcceptanceCriterion_Tolerances_Warn_Value — warn tolerance
    <MetricName>_AcceptanceCriterion_Tolerances_Fail_Value — fail tolerance

MQA_MDL_MlcQA_Results / MQA_MDL_MlcQA_TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MLC (Multi-Leaf Collimator) QA. Joined via ``MlcQATestExecutionBase_Id``.

Metrics: ``FailingPeaks``, ``MaximumDeviation``, ``InterstripRatio``,
``StandardDeviation``, ``IsocenterToStripDistance``, ``TotalPeaks``,
``LeavesThatFailed``.

MQA_MDL_Cbct_Results / MQA_MDL_Cbct_TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CBCT (Cone Beam CT) image quality QA. Joined via ``Id``.

Metrics: ``ScalingDiscrepancy``, ``GeometricDistortion``, ``SpatialResolution``,
``OverallUniformity``, ``MinimumUniformity``, ``Contrast``, ``CNR``,
``MaxHuDeviation``, ``MeasuredSliceWidth``, ``SliceWidthDifference``.

MQA_MDL_Planar_Results / MQA_MDL_Planar_TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Planar imaging QA. Joined via ``Id``.

Metrics: ``ScalingDiscrepancy``, ``SpatialResolution``, ``MinimumUniformity``,
``Contrast``, ``CNR``, ``XOffset``, ``YOffset``.


Pattern C: Dosimetry Tables
---------------------------

These have their own table structures with energy-keyed results.

MQA_Dosimetry_Profile_Results
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Beam profile measurements (flatness, symmetry, penumbra, etc.).

==============================  ==================================================
Column                          Description
==============================  ==================================================
``DisplayName``                  Profile name (e.g. ``"Flatness"``, ``"Penumbra Left"``)
``Actual``                       Measured value
``ProfileDirection``             1=crossline, 2=inline
``Expected``, ``Warn``, ``Fail`` Tolerance values
==============================  ==================================================

Joined through ``MQA_Dosimetry_Profile_QueueItemExecutions`` and
``MQA_Dosimetry_Profile_TestExecutions`` (3-table join chain).

MQA_Dosimetry_Wedge_QueueItemExecutions / _TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Wedge constancy measurements, keyed by ``BeamQuality_EnergyValue``.

MQA_Dosimetry_Output_QueueItemExecutions / _TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Output constancy measurements, keyed by ``BeamQuality_EnergyValue``.
Shares ``MQA_Dosimetry_Common_QueueItemExecutions`` for energy metadata.

MQA_Dosimetry_Energy_ChamberExecutions / _QueueItemExecutions / _TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Energy constancy per chamber, keyed by ``(energy, IsFlatteningFilterFree, ChamberNumber)``.


Pattern D: IsoCheck / VMAT Tables
---------------------------------

MQA_MDL_VmatDmlc_Results / _TestExecutions / _RoiResults
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

VMAT/DMLC QA with parent ``NormalizationValueResult`` and child ROI results
(``Mean``, ``StandardDeviation``) joined via ``VmatDmlcResult_Id``.

MQA_IsoCheck_WinstonLutz_TestExecutions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Winston-Lutz isocentre accuracy. Directly inherits ``MQA_TestImplementationExecutions``
(no separate results table). Metrics: ``MaximumDeviation2D``, ``Deviation3D``.


Device Name Mapping
-------------------

The ``RadiationDeviceName`` column in ``MQA_TestExecutions`` identifies the
physical device. QATrack+ maps these to ``Unit`` numbers via
``myqa_device_map.yaml``. A single device may have multiple names over its
lifetime (e.g. ``"LA317 - H192972"`` → ``"LA317"`` → ``"Exactrac_LA317"``),
so the YAML maps a list of aliases to each unit number.
