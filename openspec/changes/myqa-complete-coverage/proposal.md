## Why

The myQA import engine (built in `full-myqa-sync`, fixed in `fix-myqa-importers`)
successfully imports LINAC QA data for 8 treatment units. However, production
myQA database exploration revealed that **~60% of available data is not being
imported** due to three categories of gaps:

1. **Broken patterns**: Wedge (1,052 executions), Energy (16), and PassFail
   (29,908) importers use task-name patterns that match **zero** sessions in
   production. The real task names differ from what was assumed. Additionally,
   the daily constancy importer misses 34K+ legacy sessions using older task
   names (`"Daily Constancy Check"`, `"Daily Constancy Check[1-4]"`).
2. **Missing tolerances**: Profile importer (38,732 TestInstances) has no
   `discover_setup_tests` method, so no tolerances exist — all data shows as
   `no_tol` with no pass/fail evaluation. Wedge and Energy importers have the
   same gap. The `matrix-dosimetry-import` test list is also missing from
   `UNITS_PER_LIST`, so setup creates no UTCs/UTIs for these types.
3. **Unmapped devices**: ~85 devices beyond LINACs (ion chambers, well chambers,
   thermometers, barometers, electrometers, HDR afterloader, MRI, survey meters,
   detectors) are entirely unimported. myQA holds years of calibration and QA
   data for each.

This change makes QATrack+ a complete backup of all myQA data — every device,
every test type, every session — and enables adding supplementary tests on top.

This supersedes the non-goals in the original `myqa-sync` spec which excluded
"Well Chamber, or other non-linac QA tasks" — those are now explicitly in scope.

## What Changes

### Pattern Fixes (existing importers)

- **Wedge**: Change patterns from `["5.Tmt.Linac.M%Wedge%"]` (matches 0) to
  the same monthly dosimetry patterns used by Output/Profile. Add
  `discover_setup_tests` for tolerances from Wedge QueueItemExecutions.
- **Energy**: Same pattern fix. Minimal data (16 executions on DUMMY LINAC).
- **PassFail**: Change patterns from `["5.Tmt.Linac.P%"]` (matches 0) to broad
  patterns covering all device categories: `["5.Tmt.%", "3.Sim.%", "2.Phys.%",
  "1.FM.%"]`. The skip-empty guard filters sessions without PassFail data.
- **Profile**: Add `discover_setup_tests` that queries
  `MQA_Dosimetry_Profile_Results` JOINed through the full execution chain to
  `DVC_RadiationDeviceEnergy` for distinct DisplayName × ProfileDirection ×
  Energy combinations. The energy dimension is **critical** — slugs include
  energy tags (e.g., `mtx_flat_il_6x`, not `mtx_flat_il`), so discovery without
  energy would generate Test objects that don't match the import output.
- **Daily Constancy**: Add legacy task name patterns (`"Daily Constancy Check"`,
  `"Daily Constancy Check[1]"`–`"[4]"`) capturing 34K+ historical sessions.
- **matrix-dosimetry-import**: Add to `UNITS_PER_LIST` so setup creates UTCs/UTIs
  for Profile/Wedge/Energy (currently missing entirely).

### Device Expansion (~85 new units)

Expand `LINAC_MAP` from 10 entries to ~95 entries covering every real device
in myQA. Each device gets its own QATrack+ Unit number for individual tracking.
Legacy device names (renamed over time) are aliased to current units.

| Unit Range | Category | Example Devices | Count |
|---|---|---|---|
| 1–9 | Treatment LINACs (existing) | CST15, OBK15, LA317, LA414, etc. | 8 |
| 50 | DXR (existing) | GM0191, GM191 | 1 |
| 100–101 | Imaging | CT22, MRI23 Magnetom Vida 3T | 2 |
| 200 | Brachytherapy | Flexitron19 (HDR) | 1 |
| 300–319 | CPMCC field ion chambers | NE 2571, FC65-P, PTW 30013, Roos | ~17 |
| 320–329 | Secondary standard chambers | FC65-G, Dose 1 | ~5 |
| 330–349 | Reference/scanning chambers | CC13, CC04 | ~8 |
| 350–359 | Well chambers | A990695, A060254 | ~4 |
| 360–389 | Thermometers (CPMCC + BCHC) | Digital, Checktemp | ~13 |
| 390–399 | Barometers | GE PACE1000, DPI 800 | 2 |
| 400–409 | Electrometers | D4, D4+ | ~4 |
| 410–429 | Survey meters / OSLDs / neutron | Austral Rad, Mirion DMC, Ranger | ~8 |
| 430–449 | Detectors / phantoms | MatrixX, SRS Device, WP1D, myQA Daily | ~5 |
| 450–479 | BCHC chambers / electrometers | PTW 30013, PTW Roos, PCElec, Fluke | ~12 |
| 480–499 | Audits / safety / security | IAEA Audit, Source Security, Rad Safety | ~6 |

### New Numeric Importers (~11 new subclasses)

New `MyqaNumericImportBase` subclasses for task namespaces not yet covered.
All read from `MQA_Numeric_TestConditionExecutions` — just different task patterns:

| Importer | Patterns | List Slug | Est. Sessions |
|---|---|---|---|
| CT Daily | `3.Sim.CT.D%` | `myqa_ct_daily` | ~1,016 |
| CT Monthly | `3.Sim.CT.M%` | `myqa_ct_monthly` | ~120 |
| MRI Daily | `3.Sim.MRI.D%` | `myqa_mri_daily` | ~833 |
| Exactrac | `5.Tmt.ET.D%`, `.W%`, `.M%` | `myqa_exactrac` | ~1,902 |
| HDR | `5.Tmt.HDR.%` | `myqa_hdr` | ~851 |
| Physics Equipment | `2.Phys.%` | `myqa_physics` | ~1,500+ |
| Facility Mgmt | `1.FM.%` | `myqa_facility` | ~880 |
| LINAC Safety | `5.Tmt.Linac.M.Safety%`, `.F%` | `myqa_linac_safety` | ~3,500+ |
| LINAC IGRT | `5.Tmt.Linac.M.IGRT%` | `myqa_monthly_igrt` | ~1,500+ |
| LINAC Annual | `5.Tmt.Linac.Y%`, `.6M%`, `.Yearly%` | `myqa_annual` | ~2,000+ |
| LINAC Quarterly | `5.Tmt.Linac.Q%` | `myqa_quarterly` | ~500+ |

### Already-Completed Work (from prior session)

These fixes were implemented during the `fix-myqa-importers` session and are
marked `[x]` in tasks.md:

- `get_or_create_tolerance`: try/except with name-based fallback for Tolerance
  name collision edge cases.
- UTI tolerance assignment: setup now passes tolerance FK in `get_or_create`
  defaults, with retroactive update for existing UTIs.
- `import_myqa_all`: tracks `skipped_empty` status separately from errors.
- References assigned for CBCT/Planar/WL (reference=0) and VMAT
  (per-session Expected, mean=1.0, std=0.0).

## Capabilities

### New Capabilities

- `myqa-device-expansion`: LINAC_MAP expansion, QATrack+ Unit creation, and
  UNITS_PER_LIST updates for ~85 new devices across all equipment categories.
- `myqa-numeric-importers`: New MyqaNumericImportBase subclasses covering CT,
  MRI, Exactrac, HDR, physics equipment, facility management, and additional
  LINAC QA categories (safety, IGRT, annual, quarterly).
- `myqa-dosimetry-tolerances`: discover_setup_tests methods for Profile, Wedge,
  and Energy importers — queries myQA for per-metric tolerances and creates
  Tolerance/Reference objects enabling pass/fail evaluation. Also adds
  `matrix-dosimetry-import` to UNITS_PER_LIST.

### Modified Capabilities

- `myqa-sync`: Wedge, Energy, and PassFail task_name_patterns corrected to
  match production task names. PassFail scope expanded to all device categories.
  Legacy daily constancy patterns added.

## Impact

### Files Modified

| File | Changes |
|---|---|
| `qatrack/myqa_import.py` | Expand LINAC_MAP (~85 entries), fix Wedge/Energy/PassFail patterns, add legacy constancy patterns, add ~11 new Numeric importer subclasses, add Profile/Wedge/Energy discover_setup_tests, add `matrix-dosimetry-import` to UNITS_PER_LIST, register new types in TASK_TYPE_REGISTRY |
| `qatrack/qa/management/commands/setup_myqa_tests.py` | *(already fixed)* get_or_create_tolerance error handling, UTI tolerance assignment |
| `qatrack/qa/tasks.py` | *(already fixed)* Track skipped_empty status |

### Data Volume

- ~85 new QATrack+ Unit records
- ~25 new TestList objects
- ~2,000+ new Test objects (discovered dynamically from myQA)
- ~80,000+ new TestInstance records (estimated across all new importers)
- ~100,000+ TestInstances re-evaluated for pass/fail (existing Profile data
  gaining tolerances + new Numeric/PassFail data)

### Risks

- **--force data loss for matrix-dosimetry-import**: Profile, Wedge, and Energy
  all share the `mtx_` slug prefix. Running `setup --force` for any of them
  would delete ALL 232 `mtx_` Tests and 38K+ TestInstances. **Mitigation**:
  never use `--force` for matrix-dosimetry-import; use retroactive
  `get_or_create` instead.
- **Profile slug mismatch**: Discovery must include energy dimension or Test
  slugs won't match import output. **Mitigated**: design D4 specifies full JOIN
  chain through DVC_RadiationDeviceEnergy.
- **High volume import**: ~80K+ new TIs may take 30–60 minutes; PassFail alone
  has ~22K sessions. **Mitigation**: import per-type with `--task` flag;
  `duplicate_check` short-circuits before slow myQA queries.
- **Dynamic test discovery**: Physics equipment and facility tasks have
  variable test names across devices; discover_setup_tests must handle
  device-specific test name variations.
- **Unit creation**: Creating 85+ units requires careful naming and numbering
  to avoid collisions with existing units.
- **Tolerance deduplication**: Creating tolerances for ~2,000 tests may hit
  `Tolerance.name` unique constraint collisions. **Mitigated**: `get_or_create_tolerance`
  has name-based fallback (already implemented).

### Test Strategy

- Dry-run imports (`--dry-run`) to count sessions per type before full import
- Sample 3 sessions per type per unit, check pass_fail counts and chart visibility
- Re-run existing importers (CBCT, VMAT, WL, MLC, Output) to confirm no duplicates
- Verify `matrix-dosimetry-import` setup creates UTCs/UTIs without deleting existing data
- Verify Python module compiles cleanly after all changes
