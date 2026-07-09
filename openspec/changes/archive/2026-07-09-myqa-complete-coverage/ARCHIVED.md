# Archived: superseded

This change was **superseded before completion** by the dynamic-TaskName import
redesign (`myqa-dynamic-taskname-import`, archived separately).

It was written against the earlier **hardcoded importer-class architecture**
(`Myqa*Import` subclasses, `task_name_patterns`, `TASK_TYPE_REGISTRY`,
`UNITS_PER_LIST`). That architecture was replaced wholesale by the dynamic
engine in `qatrack/myqa_import.py`, which discovers all TaskNames from myQA at
runtime (no hardcoded patterns/classes).

As a result:
- Tasks 1-7 (marked `[x]`) reference code that no longer exists — their *intent*
  (device coverage via `myqa_device_map.yaml`, dynamic discovery, inline
  pass/fail via `_compute_pass_fail`) was folded into the redesign and later
  hardening (`myqa-state-aware-import`, plus valueless-session skip and
  auto-approve work).
- Tasks 8-11 were left incomplete because their literal commands
  (`import_myqa --task <type>`, `setup_myqa_tests --force` for a list slug,
  per-importer `discover_setup_tests`) do not exist in the dynamic model.

**Delta specs were NOT synced** — they describe the superseded architecture and
syncing would have overwritten the correct current `myqa-sync` main spec.

The change's *goal* (complete myQA backup) is met by the current pipeline:
`setup_myqa_tests` + `import_myqa --days 3650`.
