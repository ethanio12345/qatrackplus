# myQA Import System — Architecture

Visual reference for how the myQA import system fits together: data flow,
configuration files, scheduling, and observation layers.

## System overview

```
   ┌─────────────────────────────────────────────────────────────────────┐
   │                     IBA myQA SQL Server                              │
   │                                                                     │
   │   MQA_TestExecutions (base table — TaskName, DeviceName, State)    │
   │       │                                                             │
   │       ├── MQA_Numeric_TestConditionExecutions                      │
   │       ├── MQA_PassFail_TestExecutions                              │
   │       ├── MQA_Dosimetry_{Profile,Wedge,Output,Energy}_*            │
   │       ├── MQA_MDL_{MlcQA,Cbct,Planar,VmatDmlc}_*                   │
   │       └── MQA_IsoCheck_WinstonLutz_TestExecutions                  │
   │                                                                     │
   │   Standard vendor schema (MQA_* tables). Read-only SELECT access.   │
   └──────────────────────────────────┬──────────────────────────────────┘
                                      │ pymssql
                                      ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │                  qatrack/myqa_import.py (~2000 lines)               │
   │                      The Import Engine                              │
   │                                                                     │
   │   ┌─────────────┐   ┌──────────────┐   ┌────────────────────────┐   │
   │   │  Discovery   │   │ Extraction   │   │    Import Session      │   │
   │   │             │   │              │   │                        │   │
   │   │ discover_   │   │ extract_     │   │  query_sessions()      │   │
   │   │  tasknames() │   │  all_types() │   │        ↓               │   │
   │   │       ↓     │   │       ↓      │   │  duplicate_check()     │   │
   │   │ discover_   │   │ 11 type-     │   │        ↓               │   │
   │   │  conditions()│   │  specific   │   │  import_session()      │   │
   │   │       ↓     │   │  extractors │   │   → TestListInstance   │   │
   │   │ discover_   │   │  merged →   │   │   → TestInstance[]     │   │
   │   │  units()    │   │  one dict   │   │   → auto_approve()     │   │
   │   └─────────────┘   └──────────────┘   └────────────────────────┘   │
   │                                                                     │
   │   Centre config loaded lazily: _load_centre_config()                │
   │   Device map loaded lazily: _load_device_map()                      │
   └──────────────────────────────────┬──────────────────────────────────┘
                                      │ Django ORM
                                      ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │                  QATrack+ PostgreSQL Database                       │
   │                                                                     │
   │   TestList (one per TaskName)                                       │
   │       └── TestListMembership                                        │
   │           └── Test (shared by condition-name slug)                  │
   │   UnitTestCollection (one per unit × TestList × frequency)          │
   │       └── UnitTestInfo (one per unit × Test; holds tolerance+ref)   │
   │   TestListInstance (one per imported session)                       │
   │       └── TestInstance (one per condition reading)                  │
   │                                                                     │
   │   Tolerance, Reference, TestInstanceStatus, Frequency               │
   └─────────────────────────────────────────────────────────────────────┘
```

## Configuration files

```
   qatrack/qa/management/commands/
   │
   ├── myqa_device_map.yaml          unit_number → myQA RadiationDeviceName
   │                                 Edit when: myQA adds/renames devices
   │
   ├── myqa_centre_config.yaml       sites, device-class rules, linac types,
   │                                 frequency overrides
   │                                 Edit when: centre reorganises, adds unit type
   │
   └── myqa_name_overrides.yaml      myQA condition-name → display name
                                     Edit when: physicist wants clearer names
```

All three are loaded lazily and cached at module level. If absent, the
engine falls back to in-code BCHC defaults (with `DeprecationWarning` for
the centre config).

## Two-phase setup + import

```
   Phase 1: SETUP (setup_myqa_tests)
   ──────────────────────────────────
   For each myQA TaskName:
     1. discover_conditions() → list of condition names
     2. Create TestList (slug = slugify(TaskName))
     3. Create/reuse Tests (slug = slugify(condition_name), shared)
     4. discover_units_for_taskname() → which units have data
     5. Create UTC + UTIs for each unit
     6. No tolerances set (D3 — per-unit, configured later)

   Phase 2: IMPORT (import_myqa)
   ─────────────────────────────
   For each TaskName:
     1. query_sessions(days) → sessions in window
     2. For each session:
        a. duplicate_check() → skip if already imported
        b. extract_all_types() → merge all 11 extractors
        c. Skip if all values NULL (valueless-session guard)
        d. Create TestListInstance + TestInstances
        e. Set tolerances/references from myQA values
        f. auto_approve() if all tests pass

   Re-run safely: both phases are idempotent (get_or_create + dedup).
```

## Scheduling layer

```
   ┌───────────────────────────────────────────────────────────┐
   │                    django-q2 Schedules                     │
   │                                                           │
   │   Schedule #7  "myQA Daily Import"                       │
   │   func: qatrack.myqa_import.import_myqa_results           │
   │   cadence: DAILY                                          │
   │   purpose: bulk data ingestion (sessions from last 2d)    │
   │                                                           │
   │   Schedule "myQA Weekly Setup"                            │
   │   func: qatrack.qa.tasks.run_setup_myqa_tests             │
   │   cadence: CRON 0 2 * * 0 (Sun 02:00 local)              │
   │   purpose: detect new unit↔TaskName combinations          │
   │   (spawns manage.py setup_myqa_tests detached — setup     │
   │    takes minutes, exceeds qcluster's 60s timeout)         │
   │                                                           │
   │   Schedule "Linac QA Archive Monthly"                     │
   │   Schedule "Daily Constancy PDF Bundle (Monthly)"         │
   │   cadence: CRON 0 7 1 * * (1st of month 07:00 local)     │
   │   purpose: render monthly PDF reports                     │
   │   (also spawn detached — render takes ~40 min)            │
   └───────────────────────────────────────────────────────────┘
```

## Observation + onboarding layer

```
   ┌───────────────────────────────────────────────────────────┐
   │  bootstrap_myqa_centre          myqa_doctor               │
   │  ───────────────────            ──────────                │
   │  --scan: introspect myQA,       12-check precondition     │
   │    write draft device map       validator (settings,      │
   │  --apply: create Units,          connection, fixtures,    │
   │    write prod YAML, run setup    statuses, frequencies,   │
   │                                   user, categories,       │
   │                                   device-map, croniter)   │
   └───────────────────────────────────────────────────────────┘
   ┌───────────────────────────────────────────────────────────┐
   │  myqa_validate (read-only diff)                           │
   │  ─────────────────────────────────                        │
   │  Compares QATrack+ state to myQA for a given window.      │
   │  Surfaces: session mismatches, value drift, tolerance     │
   │  drift, valueless_skip vs genuine_drop.                   │
   │  Reuses engine extractors — stays in sync automatically.  │
   └───────────────────────────────────────────────────────────┘
```

## Data flow for a single session

```
   myQA session (TaskExecutionId = "abc123")
       │
       ▼
   query_sessions("Daily Constancy Check", days=30)
       │  (filters by TaskName + date window + device→unit map)
       ▼
   duplicate_check("abc123") ──── already imported? ──── skip
       │ no
       ▼
   extract_all_types("abc123")
       │  (runs 11 extractors, merges into one dict)
       │
       │  {"Output 6x": {"value": 1.002, "warn": 0.02, ...},
       │   "Flatness 6x": {"value": 1.45, ...},
       │   ...}
       ▼
   All values NULL? ──── yes ──── skipped_empty
       │ no
       ▼
   import_session()
       │
       ├── Create TestListInstance (work_started/completed = session dates)
       ├── For each condition:
       │     ├── Resolve Test by slug → UTI
       │     ├── Create tolerance from myQA warn/fail (if present)
       │     ├── Create reference from myQA Expected (if present)
       │     ├── Compute pass_fail
       │     └── Create TestInstance(value, tolerance, reference, pass_fail)
       ├── Create _taskid TestInstance (stores "abc123" for dedup)
       └── tli.auto_approve() (if all tests pass → Approved)
```
