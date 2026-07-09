# Archived: superseded

This change was **superseded before completion** by the dynamic-TaskName import
redesign (`myqa-dynamic-taskname-import`, archived separately).

It was written against the earlier **hardcoded importer-class architecture**
(`Myqa*Import` subclasses such as `MyqaMlcImport` / `MyqaVmatImport` /
`MyqaNumericImportBase`, `task_name_patterns`, `TASK_TYPE_REGISTRY`,
`UNITS_PER_LIST`, per-importer `discover_setup_tests()`). That architecture was
replaced wholesale by the dynamic engine in `qatrack/myqa_import.py`, which
discovers all TaskNames from myQA at runtime (no hardcoded classes/patterns).

As a result:
- Code tasks (Phase 0-8.2, marked `[x]`) reference classes/functions that no
  longer exist — their *intent* (corrected JOIN chains, slug rules, dedup via
  taskid, per-type tolerances/pass-fail) was folded into the dynamic engine
  (`extract_numeric`, `extract_profile`, `_compute_pass_fail`, etc.) and later
  hardening (`myqa-state-aware-import`, valueless-session skip, auto-approve).
- The 8 deferred tasks (1.3, 2.2, 3.3, 4.3, 5.2, 6.2, 7.2, 8.3) are operational
  backfills that use commands which don't exist in the dynamic model:
  `import_myqa_results --task <key>` (current command is `import_myqa` with
  `--task-name <TaskName>`) and `setup_myqa_tests --force --task-type <key>`
  (current `setup_myqa_tests` discovers TaskNames dynamically).

**Delta specs (cbct, mlc, numeric, passfail, planar, vmat, winston-lutz) were
NOT synced** — they describe the superseded per-importer architecture and none
of those capabilities have main specs; syncing would create stale specs.

The change's *goal* (correct extraction for every myQA execution type) is met
by the current dynamic pipeline: `setup_myqa_tests` + `import_myqa --days 3650`.
