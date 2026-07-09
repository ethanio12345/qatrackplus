## Context

The myQA import engine (`qatrack/myqa_import.py`) was built in `full-myqa-sync`
and fixed in `fix-myqa-importers`. It successfully imports data for 8 LINACs,
1 DXR, and 1 CT simulator across these test types: Numeric (daily), Output,
Profile, MLC, CBCT, Planar, VMAT, WinstonLutz.

Production database exploration revealed that **~60% of available myQA data is
not imported** due to three categories of gaps:

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT COVERAGE MAP                     │
├──────────────────┬──────────┬───────────────────────────────┤
│ Category         │ Status   │ Gap                           │
├──────────────────┼──────────┼───────────────────────────────┤
│ LINAC Daily QA   │ ✅ Done  │                               │
│ LINAC MLC/VMAT   │ ✅ Done  │                               │
│ LINAC CBCT/Planar│ ✅ Done  │                               │
│ LINAC WL         │ ✅ Done  │                               │
│ LINAC Output     │ ✅ Done  │                               │
│ LINAC Profile    │ ⚠️ No tol│ 38,732 TIs without pass/fail  │
│ LINAC Wedge      │ ❌ Broken│ 1,052 sessions not imported   │
│ LINAC Energy     │ ❌ Broken│ 16 sessions not imported      │
│ PassFail (all)   │ ❌ Broken│ 29,908 sessions not imported  │
│ LINAC Safety/IGRT│ ❌ Missing│ ~5,000+ sessions             │
│ LINAC Annual/Quar│ ❌ Missing│ ~2,500+ sessions             │
│ CT Daily/Monthly │ ❌ Missing│ ~1,136 sessions              │
│ MRI Daily        │ ❌ Missing│ ~833 sessions                │
│ Exactrac W/M     │ ❌ Missing│ ~1,902 sessions              │
│ HDR (Flexitron)  │ ❌ Missing│ ~851 sessions                │
│ Physics Equipment│ ❌ Missing│ ~1,500+ sessions / ~60 dev   │
│ Facility Mgmt    │ ❌ Missing│ ~880 sessions                │
│ ~85 Devices      │ ❌ Missing│ Not in LINAC_MAP             │
└──────────────────┴──────────┴───────────────────────────────┘
```

### Key Architecture Facts

- **Import engine** (`myqa_import.py:135-317`): `MyqaImportBase` with
  `query_new_sessions()` → `duplicate_check()` → `extract_results()` →
  `import_session()` pipeline. Subclasses override `task_name_patterns`,
  `list_slug`, `extract_results()`, and optionally `discover_setup_tests()`.
- **Setup command** (`setup_myqa_tests.py`): Creates TestList, Test,
  Tolerance, TestListMembership, UnitTestCollection, UnitTestInfo records
  from each importer's `discover_setup_tests()` output.
- **Registration**: `TASK_TYPE_REGISTRY` dict maps task keys to importer classes.
  `import_myqa_all()` iterates all registered types.
- **Deduplication**: `duplicate_check()` queries for existing TestInstance with
  the same `{prefix}taskid` string_value — safe to re-run.
- **Skip-empty guard** (`myqa_import.py:249-251`): Sessions where
  `extract_results` returns only the taskid key are skipped, preventing empty
  TLIs when multiple importers share task patterns.

## Goals / Non-Goals

**Goals:**

- Import ALL available myQA data into QATrack+ — every device, every test type,
  every session — as a complete backup.
- Enable pass/fail evaluation for all imported data via proper tolerance and
  reference assignment.
- Create individual QATrack+ Unit records for each physical device (~85 new
  units) so equipment-level QA tracking works.
- Allow supplementary tests to be added in QATrack+ on top of imported myQA data.
- Maintain backward compatibility — existing imported data must not be
  duplicated or lost.

**Non-Goals:**

- Writing to myQA database (always read-only).
- Real-time or sub-daily import (daily batch via django-q is sufficient).
- Proton therapy image tests (`MQA_PT_ImageTests_*`) — no proton beams at this
  site.
- StarShot tests — 0 test executions in production.
- MLC detailed strip/leaf-pair data — 0 rows in production.
- Restructuring existing test lists or renaming existing slugs.

## Decisions

### D1: LINAC_MAP structure — `dict[int, str | list[str]]`

The existing `LINAC_MAP` already supports `list[str]` values for multi-device
units (unit 3 = `["LA317 - H192972", "Exactrac_LA317"]`). This change expands
the dict to ~95 entries. Legacy device names are added as additional list
entries mapped to the same unit number.

```
LINAC_MAP = {
    # Treatment LINACs
    1: "CST15 - H192361",
    2: "OBK15 - H192362",
    3: ["LA317 - H192972", "Exactrac_LA317", "LA317"],  # LA317 = legacy
    4: "LA414 - H191733",
    5: "LA512 - H191182",
    7: "LA524 - H196713",
    8: "LA224 - H196406",

    # Imaging
    50: ["DXR - GM0191", "DXR - GM191"],          # GM191 = legacy
    100: "CPMCC CT22",
    101: ["CPMCC MRI23 Magnetom Vida 3T",          # underscore = legacy
          "CPMCC MRI23_Magnetom Vida 3T"],

    # Brachytherapy
    200: ["Flexitron19", "HDR"],                   # HDR = legacy

    # CPMCC Field Ion Chambers (300–319)
    300: "CPMCC (F) NE 2571 - 3708",
    301: "CPMCC (F) NE 2571 - 3708 (18)",
    # ... etc
}
```

**Alternative considered**: A separate `LEGACY_DEVICE_MAP` for old names.
Rejected because `query_new_sessions` already iterates list values per unit —
adding legacy names as list entries is simpler and uses existing logic.

### D2: New Numeric importers subclass MyqaNumericImportBase

All Numeric data (regardless of device type) is stored in
`MQA_Numeric_TestConditionExecutions` with the same column structure. The
existing `MyqaNumericImportBase.extract_results()` and
`discover_setup_tests()` methods work unchanged — only `task_name_patterns`
and `list_slug` differ per subclass.

```python
class MyqaCtDailyImport(MyqaNumericImportBase):
    list_slug = "myqa_ct_daily"
    task_name_patterns = ["3.Sim.CT.D%"]

class MyqaMriDailyImport(MyqaNumericImportBase):
    list_slug = "myqa_mri_daily"
    task_name_patterns = ["3.Sim.MRI.D%"]

class MyqaHdrImport(MyqaNumericImportBase):
    list_slug = "myqa_hdr"
    task_name_patterns = ["5.Tmt.HDR.%"]

class MyqaPhysicsImport(MyqaNumericImportBase):
    list_slug = "myqa_physics"
    task_name_patterns = ["2.Phys.%"]
    # ... etc
```

**Alternative considered**: A single "catch-all" Numeric importer with `%`
pattern. Rejected because:
- Different task types need different test lists (for chart organization).
- discover_setup_tests queries are scoped by patterns — a catch-all would
  discover thousands of unrelated test names, creating a chaotic test list.
- The skip-empty guard would still work, but the setup would be unwieldy.

### D3: PassFail patterns — broad with skip-empty guard

PassFail tests coexist with Numeric, Profile, Output, etc. in the same myQA
sessions. For example, `5.Tmt.Linac.M.Dosimetry - Monthly QA` has Profile +
Output + PassFail tests. The PassFail importer needs patterns that span all
device categories:

```python
task_name_patterns = ["5.Tmt.%", "3.Sim.%", "2.Phys.%", "1.FM.%"]
```

The skip-empty guard (`myqa_import.py:249-251`) prevents creating empty TLIs
for sessions that have no PassFail data. The `duplicate_check` prevents
duplicate imports for sessions that have already been imported.

**Risk**: `5.Tmt.%` matches thousands of sessions. Performance impact is
mitigated by `duplicate_check` being a simple `TestInstance.objects.filter()`
query that short-circuits before `extract_results` is called.

### D4: Profile discover_setup_tests — energy-aware discovery

**CRITICAL**: Profile slugs include an energy tag: `mtx_{mtype}_{direction}_{energy_tag}`
(e.g., `mtx_flat_il_6x`, `mtx_sym_cl_10fff`). The discovery query MUST include
the energy dimension, otherwise generated Test slugs won't match the slugs
emitted by `extract_results`.

The discovery uses the same JOIN chain as `extract_results`:

```sql
SELECT dpr.DisplayName, dpr.ProfileDirection,
       dvc.EnergyValue, dvc.IsFlatteningFilterFree, et.Description,
       MAX(dpr.Warn) as Warn, MAX(dpr.Fail) as Fail
FROM MQA_Dosimetry_Profile_Results dpr
JOIN MQA_Dosimetry_Profile_QueueItemExecutions dpqie
    ON dpr.ProfileQueueItemExecution_Id = dpqie.Id
JOIN MQA_Dosimetry_Profile_TestExecutions dpte
    ON dpqie.Id = dpte.ProfileQueueItem_Id
LEFT JOIN DVC_RadiationDeviceEnergy dvc
    ON dpte.BeamQuality_RadiationDeviceEnergyId = dvc.Id
LEFT JOIN DVC_EnergyType et ON dvc.EnergyTypeId = et.Id
WHERE dpr.DisplayName IS NOT NULL
GROUP BY dpr.DisplayName, dpr.ProfileDirection,
         dvc.EnergyValue, dvc.IsFlatteningFilterFree, et.Description
```

For each row, generate the slug using the same logic as `extract_results`:
```python
energy = str(round(row["EnergyValue"]))
desc = (row["Description"] or "photons").lower()
energy_tag = f"{energy}e" if desc == "electrons" else f"{energy}{'fff' if row['IsFlatteningFilterFree'] else 'x'}"
direction = "il" if row["ProfileDirection"] == 1 else "cl"
mtype = name_map.get(row["DisplayName"], row["DisplayName"])
slug = f"mtx_{mtype}_{direction}_{energy_tag}"
```

**Note**: 232 `mtx_` tests already exist from the old matrix importer. The
setup MUST use `get_or_create` (not delete-and-recreate) to avoid destroying
38K+ existing TestInstances. Do NOT use `--force` for `matrix-dosimetry-import`.

### D5: Wedge discover_setup_tests

Wedge data in `MQA_Dosimetry_Wedge_QueueItemExecutions` has per-energy
ExpectedValue, Tolerance_Warn, Tolerance_Fail, WedgeAngle, and WedgeDirection.
Discovery:

```sql
SELECT wte.BeamQuality_EnergyValue,
       MAX(wqie.Tolerance_Warn) as Warn,
       MAX(wqie.Tolerance_Fail) as Fail,
       AVG(wqie.ExpectedValue) as Expected
FROM MQA_Dosimetry_Wedge_QueueItemExecutions wqie
JOIN MQA_Dosimetry_Wedge_TestExecutions wte
    ON wqie.WedgeConstancyExecution_Id = wte.Id
GROUP BY wte.BeamQuality_EnergyValue
```

Each energy gets a test spec: `mtx_wedge_cont_{energy}x`. The Expected value
becomes the reference baseline.

### D6: Tolerance assignment to UTIs — fix in setup_myqa_tests.py

The current `setup_myqa_tests.py` creates Tolerance objects but never assigns
them to UnitTestInfo records (the `tolerance` FK is left NULL). The fix
changes the UTI creation loop to pass the tolerance as a default:

```python
# Before (broken):
for test in created_tests:
    UnitTestInfo.objects.get_or_create(
        unit=unit, test=test,
        defaults={"created_by": ..., "modified_by": ...},
    )

# After (fixed):
for test, tol in created_tests:  # now list of (test, tolerance) tuples
    uti, created = UnitTestInfo.objects.get_or_create(
        unit=unit, test=test,
        defaults={"tolerance": tol, "created_by": ..., "modified_by": ...},
    )
    if not created and tol and not uti.tolerance_id:
        uti.tolerance = tol
        uti.save(update_fields=["tolerance"])
```

### D7: Reference strategy per test type

| Test Type | Reference Source | Strategy |
|---|---|---|
| WL, CBCT, Planar | Expected = 0 (deviation metrics) | Single `Reference(value=0)` assigned to all TIs |
| VMAT normalization | Per-session Expected from myQA | Per-TI Reference from `NormalizationValueAcceptanceCriterion_ExpectedValue_Value` |
| VMAT mean/std | Fixed (mean=1.0, std=0.0) | Constant references |
| Output | Per-session Expected from myQA | Per-TI Reference from `MQA_Dosimetry_Output_QueueItemExecutions.Expected` |
| Profile | Per-row Expected from myQA | Per-TI Reference from `MQA_Dosimetry_Profile_Results.Expected` |
| Wedge | Per-energy Expected (averaged) | Per-UTI Reference from discovery query AVG(Expected) |
| Numeric (all) | Per-row Expected from myQA | Per-TI Reference from `MQA_Numeric_TestConditionExecutions.Expected` |

For Numeric importers, the existing `extract_results` does not capture Expected
values. This change adds Expected capture to the Numeric extract_results method
and stores it per-TI during import.

**Alternative considered**: Use UTI-level references (one reference per
unit-test pair). Rejected because many test types have per-session expected
values that vary (e.g., Output dose varies by session due to decay).

### D8: Unit creation — management command

A new method in `setup_myqa_tests.py` (or a separate command) creates
QATrack+ Unit records for all devices in LINAC_MAP that don't already have
a Unit. The command:

1. Reads LINAC_MAP entries
2. For each unit number not already in `Unit.objects`, creates a new Unit with:
   - `number`: the unit number
   - `name`: the primary device name (first list entry or string value)
   - `site`: derived from device name prefix (CPMCC vs BCHC)
   - `type`: derived from device category (LINAC, DXR, CT, MRI, HDR, Chamber, etc.)
3. Existing units are left unchanged

### D9: UNITS_PER_LIST expansion

Each test list specifies which units are applicable. The current dict covers
~9 lists. This change expands it to cover all new lists:

```python
UNITS_PER_LIST = {
    "myqa_daily_constancy": [1, 2, 3, 4, 5, 7, 8],
    "myqa_daily_physics": [1, 2, 3, 4, 5, 7, 8],
    "myqa_dxr_daily": [50],
    "myqa_ct_daily": [100],
    "myqa_ct_monthly": [100],
    "myqa_mri_daily": [101],
    "myqa_exactrac": [3],                    # Exactrac is on unit 3
    "myqa_hdr": [200],
    "myqa_physics": [300, 301, ..., 480],    # all physics equipment
    "myqa_facility": [482, 483],             # safety/security
    "myqa_linac_safety": [1, 2, 3, 4, 5, 7, 8],
    "myqa_monthly_igrt": [1, 2, 3, 4, 5, 7, 8],
    "myqa_annual": [1, 2, 3, 4, 5, 7, 8],
    "myqa_quarterly": [1, 2, 3, 4, 5, 7, 8],
    "myqa_passfail": "auto",                 # special: all units
    # ... existing entries unchanged
}
```

For `myqa_passfail` and `myqa_physics`, which span many units, a special
`"auto"` value or explicit list of all applicable unit numbers is used.

### D10: Import sequencing

```
Phase 1: Code changes
  ├── Fix Wedge/Energy/PassFail patterns
  ├── Add Profile/Wedge/Energy discover_setup_tests
  ├── Add ~12 new Numeric importer subclasses
  ├── Expand LINAC_MAP, UNITS_PER_LIST, TASK_TYPE_REGISTRY
  └── Fix setup_myqa_tests UTI tolerance assignment

Phase 2: Unit creation
  └── Create ~85 new Unit records

Phase 3: Setup (discover tests + tolerances + UTCs + UTIs)
  ├── setup_myqa_tests for all new types
  └── setup_myqa_tests --force for fixed types (Wedge/Energy/PassFail/Profile)

Phase 4: Import (--days 3650)
  ├── Existing types (dedup handles already-imported sessions)
  ├── Fixed types (Wedge/Energy/PassFail — first real import)
  └── New types (CT/MRI/HDR/Exactrac/Physics/Facility/LINAC-Safety/etc.)

Phase 5: Post-process
  ├── Assign tolerances to UTIs + TestInstances (retroactive)
  ├── Set references (per-session Expected from myQA)
  ├── Re-evaluate pass_fail for all TIs with tolerance + reference
  └── Clean up empty TLIs
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| **Import volume** (~80K+ new TIs) | 30–60 min import time | Batch processing with progress output; can run per-type with `--task` flag |
| **Tolerance name collisions** | `IntegrityError` on `Tolerance.name` unique constraint | `get_or_create_tolerance` has try/except with name-based fallback (already implemented) |
| **Profile slug mismatch** | discover_setup_tests generates wrong slugs → Tests don't match import output | Discovery MUST include energy dimension via JOIN to DVC_RadiationDeviceEnergy (fixed in D4) |
| **matrix-dosimetry-import missing from UNITS_PER_LIST** | Setup creates no UTCs/UTIs for Profile/Wedge/Energy | Add entry to UNITS_PER_LIST (task 3.4) |
| **--force data loss for matrix-dosimetry-import** | Running `setup --force` deletes by `mtx_` prefix, destroying 38K+ existing TIs across Profile/Wedge/Energy | NEVER use --force for matrix-dosimetry-import; use get_or_create retroactive tolerance assignment instead |
| **PassFail session explosion** | `5.Tmt.%` matches ~20K sessions across all types | `duplicate_check` runs first (fast DB query); skip-empty guard prevents empty TLIs; first import may take 1-2 hours |
| **Physics equipment test discovery** | Variable test names across 60+ devices | `discover_setup_tests` queries `MQA_Numeric_TestConditionExecutions` per task pattern — dynamically discovers all test names |
| **Legacy device name mapping** | Historical data under old names missed | Legacy names added as list entries in LINAC_MAP (same pattern as existing DXR mapping) |
| **Unit number collisions** | Existing units at unknown numbers | Query `Unit.objects.all()` before creation; skip existing units |
| **Profile per-energy tolerances** | DisplayName-level tolerance may not match per-energy variations | Acceptable approximation; per-energy refinement deferred to future change |
| **Numeric Expected capture** | Modifying extract_results changes import behavior | Backward compatible — existing imports deduplicated; new field added to results dict |

## Open Questions

1. **Unit `type` field**: QATrack+ Unit model has a `type` field. Should physics
   equipment units use existing types or do new UnitType records need to be
   created? → Check `UnitType` table during implementation; create as needed.

2. **Site assignment**: BCHC devices vs CPMCC devices — do Site records exist
   for both locations? → Verify during unit creation; create if missing.

3. **Chart organization**: With ~25 test lists, the chart selection UI will be
   crowded. Consider grouping test lists by category in a future UI change.

4. **Automated scheduling**: Should the new importers be added to the django-q
   daily schedule? → Yes, but verify import time doesn't exceed the schedule
   window.
