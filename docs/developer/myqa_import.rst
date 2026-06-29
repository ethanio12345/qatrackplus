myQA Import System
==================

.. module:: qatrack.myqa_import

The myQA import system dynamically discovers QA protocols, conditions, and
devices from a myQA SQL Server database and imports session data into
QATrack+.

Connection & Helpers
--------------------

.. autofunction:: get_connection
.. autofunction:: _fetchall
.. autofunction:: _result
.. autofunction:: build_device_to_unit_map

Name Handling
-------------

.. autofunction:: slugify_name
.. autofunction:: clean_roi_name
.. autofunction:: enrich_test_name
.. autofunction:: load_name_overrides

Discovery Functions
-------------------

These functions query the myQA database to discover what TestLists, Tests,
and UTCs should exist. Called during ``setup_myqa_tests``.

.. autofunction:: discover_tasknames
.. autofunction:: discover_task_protocol
.. autofunction:: discover_units_for_taskname
.. autofunction:: discover_conditions
.. autofunction:: discover_condition_metadata
.. autofunction:: discover_numeric_conditions
.. autofunction:: discover_passfail_conditions
.. autofunction:: discover_profile_conditions
.. autofunction:: discover_wedge_conditions
.. autofunction:: discover_output_conditions
.. autofunction:: discover_energy_conditions
.. autofunction:: discover_mlc_conditions
.. autofunction:: discover_cbct_conditions
.. autofunction:: discover_planar_conditions
.. autofunction:: discover_vmat_conditions
.. autofunction:: discover_winston_lutz_conditions

Name Derivation Helpers
-----------------------

.. autofunction:: _energy_prefixed
.. autofunction:: _test_step_prefix
.. autofunction:: _profile_condition_name

Extraction Functions
--------------------

These functions query the myQA database for actual measurement values for
a specific session. Called during ``import_myqa``.

.. autofunction:: extract_numeric
.. autofunction:: extract_passfail
.. autofunction:: extract_profile
.. autofunction:: extract_wedge
.. autofunction:: extract_output
.. autofunction:: extract_energy
.. autofunction:: extract_mlc
.. autofunction:: extract_cbct
.. autofunction:: extract_planar
.. autofunction:: extract_vmat
.. autofunction:: extract_winston_lutz
.. autofunction:: extract_all_types

Multi-Flag Computation
----------------------

.. autofunction:: compute_multi_flags

Tolerance & Reference Helpers
-----------------------------

.. autofunction:: _get_or_create_tolerance
.. autofunction:: _get_or_create_reference
.. autofunction:: _compute_pass_fail

Session Import
--------------

.. autofunction:: query_sessions
.. autofunction:: duplicate_check
.. autofunction:: import_session
.. autofunction:: import_myqa_results

Frequency & Status Setup
------------------------

.. autofunction:: infer_frequency
.. autofunction:: ensure_frequencies_exist
.. autofunction:: ensure_statuses_exist

Module-Level Constants
----------------------

.. autoattribute:: LINAC_MAP
.. autoattribute:: MYQA_STATE_MAP
.. data:: _EXTRACTORS

   List of ``(label, extract_fn)`` tuples defining the execution type pipeline.

.. data:: _DISCOVERERS

   List of ``(label, discover_fn, condition_type)`` tuples, parallel to
   ``_EXTRACTORS``.

.. data:: _MULTI_FLAG_SQL

   List of ``(label, sql)`` tuples for computing the ``multi`` flag per type.

See :doc:`/sql/myqa_schema` for the database schema reference and
:doc:`/sql/queries` for query pattern explanations.
