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

Configuration Files
-------------------

myqa_device_map.yaml
~~~~~~~~~~~~~~~~~~~~

YAML file mapping QATrack+ unit numbers to myQA ``RadiationDeviceName``
strings. Edit this file (not the Python code) to add or rename devices.

myqa_name_overrides.yaml
~~~~~~~~~~~~~~~~~~~~~~~~

YAML file for per-TaskName or wildcard test display name overrides. Keys
are raw myQA condition names; values replace the enriched display name.

See :doc:`/sql/mapping` for how these files are consumed.
