myQA Management Commands
========================

.. module:: qatrack.qa.management.commands

These Django management commands provide the operational interface to the
myQA import system. Run them from the project root via ``manage.py``.

setup_myqa_tests
----------------

.. automodule:: qatrack.qa.management.commands.setup_myqa_tests
   :members:
   :undoc-members:

Usage::

    python manage.py setup_myqa_tests [--dry-run] [--task-name NAME]

import_myqa
-----------

.. automodule:: qatrack.qa.management.commands.import_myqa
   :members:

Usage::

    python manage.py import_myqa [--days N] [--task-name NAME] [--unit N] [--dry-run]

clear_myqa_data
---------------

.. automodule:: qatrack.qa.management.commands.clear_myqa_data
   :members:
   :undoc-members:

Usage::

    python manage.py clear_myqa_data --yes

create_myqa_units
-----------------

.. automodule:: qatrack.qa.management.commands.create_myqa_units
   :members:
   :undoc-members:

Usage::

    python manage.py create_myqa_units

import_old_qatrack
------------------

.. automodule:: qatrack.qa.management.commands.import_old_qatrack
   :members:
   :undoc-members:

Usage::

    python manage.py import_old_qatrack --file /path/to/qatrackplus.custom

bootstrap_myqa_centre
---------------------

.. automodule:: qatrack.qa.management.commands.bootstrap_myqa_centre
   :members:

Usage::

    python manage.py bootstrap_myqa_centre --scan      # introspect myQA, write draft
    python manage.py bootstrap_myqa_centre --apply     # create Units, write prod YAML, run setup

myqa_doctor
-----------

.. automodule:: qatrack.qa.management.commands.myqa_doctor
   :members:

Usage::

    python manage.py myqa_doctor [--no-autofix] [--json]

myqa_validate
-------------

.. automodule:: qatrack.qa.management.commands.myqa_validate
   :members:

Usage::

    python manage.py myqa_validate [--days N] [--task-name NAME] [--unit N] [--json] [--summary-only]

setup_myqa_setup_schedule
--------------------------

.. automodule:: qatrack.qa.management.commands.setup_myqa_setup_schedule
   :members:

Usage::

    python manage.py setup_myqa_setup_schedule

Operational Maintenance Commands
--------------------------------

These commands handle ongoing data hygiene. See
:doc:`/myqa_operational_scripts` for the full reference with cadence,
algorithms, and sample output.

clear_stale_due_dates
~~~~~~~~~~~~~~~~~~~~~

.. automodule:: qatrack.qa.management.commands.clear_stale_due_dates
   :members:

Usage::

    python manage.py clear_stale_due_dates [--linacs-only] [--apply] [--floor N] [--multiplier N]

set_angular_wraparound
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: qatrack.qa.management.commands.set_angular_wraparound
   :members:

Usage::

    python manage.py set_angular_wraparound [--apply]

auto_approve_tlis
~~~~~~~~~~~~~~~~~

.. automodule:: qatrack.qa.management.commands.auto_approve_tlis
   :members:

Usage::

    python manage.py auto_approve_tlis

approve_myqa_taskids
~~~~~~~~~~~~~~~~~~~~

.. automodule:: qatrack.qa.management.commands.approve_myqa_taskids
   :members:

Usage::

    python manage.py approve_myqa_taskids

delete_empty_tlis
~~~~~~~~~~~~~~~~~

.. automodule:: qatrack.qa.management.commands.delete_empty_tlis
   :members:

Usage::

    python manage.py delete_empty_tlis

Configuration Files
-------------------

myqa_device_map.yaml
~~~~~~~~~~~~~~~~~~~~

YAML file mapping QATrack+ unit numbers to myQA ``RadiationDeviceName``
strings. Edit this file (not the Python code) to add or rename devices.
``bootstrap_myqa_centre --scan`` can auto-generate a draft.

myqa_centre_config.yaml
~~~~~~~~~~~~~~~~~~~~~~~

YAML file holding centre-specific configuration: network name, multi-site
list (slug/name/device-prefixes), device-class rules (regex → unit_type +
category), linac unit-type allowlist, and optional frequency-inference
overrides. See the file header for the full schema.

myqa_name_overrides.yaml
~~~~~~~~~~~~~~~~~~~~~~~~

YAML file for per-TaskName or wildcard test display name overrides. Keys
are raw myQA condition names; values replace the enriched display name.

See :doc:`/sql/mapping` for how these files are consumed.
