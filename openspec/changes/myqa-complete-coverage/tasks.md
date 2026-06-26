## 1. Fix Existing Importer Patterns

- [x] 1.1 Fix `import_myqa_all` in `qatrack/qa/tasks.py` — track `skipped_empty` status separately from `skipped_err` *(completed in prior session)*
- [x] 1.2 Fix `import_myqa.py` management command output — include `skipped_empty` in summary *(completed in prior session)*
- [x] 1.3 Fix `MyqaWedgeImport.task_name_patterns` — change from `["5.Tmt.Linac.M%Wedge%", "5.Tmt.DXR.M%Wedge%"]` to `["5.Tmt.Linac.M.Dosimetry%", "5.Tmt.Linac.Monthly - Dosimetry", "5.Tmt.Linac.Y.Dosimetry%", "5.Tmt.Linac.Yearly - Relative%", "Commissioning.Dos%"]`
- [x] 1.4 Fix `MyqaEnergyImport.task_name_patterns` — same monthly dosimetry patterns as Wedge
- [x] 1.5 Fix `MyqaPassFailImport.task_name_patterns` — change from `["5.Tmt.Linac.P%", "5.Tmt.DXR.P%"]` to `["5.Tmt.%", "3.Sim.%", "2.Phys.%", "1.FM.%"]`
- [x] 1.6 Add legacy Numeric constancy patterns to `MyqaNumericConstancyImport` — add `"Daily Constancy Check"`, `"Daily Constancy Check[1]"`, `"[2]"`, `"[3]"`, `"[4]"` (31K+ historical sessions currently not captured)

## 2. Fix setup_myqa_tests Bugs

- [x] 2.1 Fix `get_or_create_tolerance` — try/except with name-based fallback for IntegrityError *(completed in prior session)*
- [x] 2.2 Fix UTI tolerance assignment — pass tolerance in UTI `get_or_create` defaults *(completed in prior session)*
- [x] 2.3 Add retroactive tolerance assignment for existing UTIs *(completed in prior session)*

## 3. Add discover_setup_tests for Dosimetry Importers

- [x] 3.1 Add `MyqaProfileImport.discover_setup_tests()` — **CRITICAL**: query MUST include energy dimension. JOIN through `MQA_Dosimetry_Profile_Results` → `QueueItemExecutions` → `TestExecutions` → `DVC_RadiationDeviceEnergy` to get EnergyValue, IsFlatteningFilterFree, and EnergyType.Description. Generate slugs matching extract_results format: `mtx_{mtype}_{direction}_{energy_tag}` (e.g. `mtx_flat_il_6x`, `mtx_sym_cl_10fff`). Extract MAX(Warn), MAX(Fail) per DisplayName × Direction × Energy combination.
- [x] 3.2 Add `MyqaWedgeImport.discover_setup_tests()` — query `MQA_Dosimetry_Wedge_QueueItemExecutions` joined with `MQA_Dosimetry_Wedge_TestExecutions`, grouped by BeamQuality_EnergyValue; generate specs for `mtx_wedge_cont_{energy}x`. Include AVG(ExpectedValue) for reference baseline.
- [x] 3.3 Add `MyqaEnergyImport.discover_setup_tests()` — query `MQA_Dosimetry_Energy_ChamberExecutions` joined with `MQA_Dosimetry_Common_QueueItemExecutions` for distinct energy/chamber/FFF combinations; generate slugs matching `mtx_energy_{energy}{fff}_{mode}_ch{chamber}` (mode = MeV if EnergyDimension=6, MV otherwise)
- [x] 3.4 Add `"matrix-dosimetry-import": [1, 2, 3, 4, 5, 7, 8, 50]` to `UNITS_PER_LIST` — **CRITICAL**: Profile, Wedge, and Energy all write to this list but it's missing from UNITS_PER_LIST, so setup creates no UTCs/UTIs for these units. Note: 232 mtx_ tests and their UTIs already exist from old matrix importer — setup must use get_or_create, not delete-and-recreate

## 4. Expand LINAC_MAP with All Devices

- [x] 4.1 Add imaging devices: unit 101 = `["CPMCC MRI23 Magnetom Vida 3T", "CPMCC MRI23_Magnetom Vida 3T"]`
- [x] 4.2 Add brachytherapy: unit 200 = `["Flexitron19", "HDR"]`
- [x] 4.3 Add CPMCC field ion chambers (units 300–317): NE 2571 (3708, 3708(18), 3762, 3762(20), 3762(20)-TBI), FC65-P (5485, 5485(22)), PTW 30013 (2417, 2417(16)), Roos (198, 2326, 2326(22), 2327, 2327(22)), Inovision 99313, Dose 1 (03-8692, 20592), Fluke 0000005509
- [x] 4.4 Add secondary standard chambers (units 320–324): FC65-G (5413, 5413(22)), FC65-P (5485), Dose 1 (33699, 33699(22))
- [x] 4.5 Add reference/scanning chambers (units 330–337): CC13 (5463, 5464, 5464(06), 20792(23)), CC04 (13593, 5430, 5430(06), 13593(14))
- [x] 4.6 Add well chambers (units 350–353): Well Chamber A990695 (current + legacy), A060254 (current + legacy)
- [x] 4.7 Add thermometers (units 360–384): CPMCC Digital Thermometers (210381212, 210479123, 210381234, Digi1), CPMCC Checktemp (3CC1D4, 416467, 41672E, Digi1), BCHC thermometers (1B630A, 210479122, 210479123, Checktemp 1B630A, Checktemp 41828B)
- [x] 4.8 Add barometers (units 390–391): CPMCC GE PACE1000 10488160, BCHC DPI 800 4415686
- [x] 4.9 Add electrometers (units 400–403): CPMCC D4, D4+, D4+ (21), D4+ (legacy)
- [x] 4.10 Add survey meters/OSLDs (units 410–417): Austral Rad 2373, Ranger R316845, Mirion DMC 3000 (×4), Neutron Detector, Neutron Detector 289
- [x] 4.11 Add detectors/phantoms (units 430–434): IBA IMRT MatrixX 12236, MatrixX Resolution (24), myQA Daily 33059, SRS Device (23), WP1D
- [x] 4.12 Add BCHC chambers/electrometers (units 450–461): PTW 30013 (8451, 8451(15), 10004(15)), PTW 30012 0381(15), PTW Roos 34001 (2649(15), 3680(23)), PCElec 1014 (×2), Fluke 35040, Juliet TW10053, Romeo TW10053, PTW Romeo TW10053
- [x] 4.13 Add audit/safety/security (units 480–485): IAEA Audit, Dosimetry Audits, Source Security, Radiation Safety, WSLHD Bunker Dosimetry Cables, WSLHD/Staff, RFT26 H197686
- [x] 4.14 Add legacy LINAC name aliases: unit 3 += `"LA317"`

## 5. Create QATrack+ Unit Records

- [x] 5.1 Write a unit creation script/method that reads LINAC_MAP entries and creates `Unit` records for any unit number not already in the database
- [x] 5.2 For each new unit: set `number`, `name` (primary device name), `site` (CPMCC/BCHC based on prefix), `type` (appropriate UnitType), `active=True`
- [x] 5.3 Create any missing `Site` or `UnitType` records needed for the new units
- [x] 5.4 Run the unit creation script and verify all ~85 units are created

## 6. Add New Numeric Importer Subclasses

- [x] 6.1 Add `MyqaCtDailyImport` — patterns: `["3.Sim.CT.D%"]`, list_slug: `myqa_ct_daily`, frequency: daily
- [x] 6.2 Add `MyqaCtMonthlyImport` — patterns: `["3.Sim.CT.M%"]`, list_slug: `myqa_ct_monthly`, frequency: monthly
- [x] 6.3 Add `MyqaMriDailyImport` — patterns: `["3.Sim.MRI.D%"]`, list_slug: `myqa_mri_daily`, frequency: daily
- [x] 6.4 Add `MyqaExactracImport` — patterns: `["5.Tmt.ET.D%", "5.Tmt.ET.W%", "5.Tmt.ET.M%"]`, list_slug: `myqa_exactrac`, frequency: monthly
- [x] 6.5 Add `MyqaHdrImport` — patterns: `["5.Tmt.HDR.%"]`, list_slug: `myqa_hdr`, frequency: daily
- [x] 6.6 Add `MyqaPhysicsImport` — patterns: `["2.Phys.%"]`, list_slug: `myqa_physics`, frequency: monthly
- [x] 6.7 Add `MyqaFacilityImport` — patterns: `["1.FM.%"]`, list_slug: `myqa_facility`, frequency: weekly
- [x] 6.8 Add `MyqaLinacSafetyImport` — patterns: `["5.Tmt.Linac.M.Safety%", "5.Tmt.Linac.F%"]`, list_slug: `myqa_linac_safety`, frequency: monthly
- [x] 6.9 Add `MyqaMonthlyIgrtImport` — patterns: `["5.Tmt.Linac.M.IGRT%"]`, list_slug: `myqa_monthly_igrt`, frequency: monthly
- [x] 6.10 Add `MyqaAnnualImport` — patterns: `["5.Tmt.Linac.Y%", "5.Tmt.Linac.6M%", "5.Tmt.Linac.Yearly%"]`, list_slug: `myqa_annual`, frequency: annual
- [x] 6.11 Add `MyqaQuarterlyImport` — patterns: `["5.Tmt.Linac.Q%"]`, list_slug: `myqa_quarterly`, frequency: quarterly
- [x] 6.12 **Remove** — Numeric Expected value capture is handled in post-processing (task 10.3), not by modifying extract_results. The import engine stores only Actual values; references are assigned retroactively by querying myQA Expected per taskid.

## 7. Update UNITS_PER_LIST and TASK_TYPE_REGISTRY

- [x] 7.1 Add UNITS_PER_LIST entries for all new test lists: `myqa_ct_daily` [100], `myqa_ct_monthly` [100], `myqa_mri_daily` [101], `myqa_exactrac` [3], `myqa_hdr` [200], `myqa_physics` [300-499], `myqa_facility` [480-485], `myqa_linac_safety` [1-8], `myqa_monthly_igrt` [1-8], `myqa_annual` [1-8], `myqa_quarterly` [1-8]
- [x] 7.2 Update `myqa_passfail` UNITS_PER_LIST to include all units (1-9, 50, 100-101, 200, 300-499)
- [x] 7.3 Register all new importer classes in `TASK_TYPE_REGISTRY`

## 8. Run Setup for All Types

- [ ] 8.1 Run `setup_myqa_tests` for all new types (CT daily/monthly, MRI, Exactrac, HDR, Physics, Facility, LINAC Safety, IGRT, Annual, Quarterly) — discovers tests, tolerances, UTCs, UTIs
- [ ] 8.2 Run `setup_myqa_tests` (WITHOUT --force) for Profile/Wedge/Energy — adds discover_setup_tests tolerances to existing 232 mtx_ tests retroactively. **DO NOT use --force**: it deletes by slug prefix `mtx_` which would destroy all 38K+ existing Profile TestInstances across all three importers
- [ ] 8.3 Run `setup_myqa_tests --force` for PassFail only (list slug `myqa_passfail`, no existing data to lose)
- [ ] 8.4 Verify all UTIs have tolerances assigned (no NULLs where tolerance specs exist)

## 9. Run Import for All Types

- [ ] 9.1 Run `import_myqa --days 3650` for all existing types (CBCT, Planar, VMAT, WL, MLC, Output) — dedup handles existing sessions
- [ ] 9.2 Run `import_myqa --task myqa_wedge --days 3650` — first real import (~1,052 sessions)
- [ ] 9.3 Run `import_myqa --task myqa_energy --days 3650` — first real import (~16 sessions)
- [ ] 9.4 Run `import_myqa --task myqa_passfail --days 3650` — first real import (~29,908 sessions across all devices)
- [ ] 9.5 Run `import_myqa` for all new Numeric types (CT, MRI, Exactrac, HDR, Physics, Facility, LINAC Safety, IGRT, Annual, Quarterly)
- [ ] 9.6 Clean up any empty TestListInstances created during import

## 10. Post-Process: Tolerances, References, Pass/Fail

- [ ] 10.1 Retroactively assign tolerances to UTIs and TestInstances using each importer's `discover_setup_tests` specs (covers Profile/Wedge/Energy/new Numeric types that gained tolerances in this change)
- [x] 10.2 Assign reference=0 to CBCT/Planar/WL TestInstances *(completed in prior session)*
- [ ] 10.3 Assign per-session references from myQA Expected values for new Numeric TestInstances (CT/MRI/HDR/Exactrac/Physics/etc.) — post-processing script queries `MQA_Numeric_TestConditionExecutions.Expected` per taskid, creates Reference objects, assigns to TIs
- [x] 10.4 Assign per-session references for VMAT normalization from myQA ExpectedValue *(completed in prior session)*
- [x] 10.5 Assign reference=1.0 for VMAT mean, reference=0.0 for VMAT std dev *(completed in prior session)*
- [ ] 10.6 Assign per-session references for Profile TestInstances — query `MQA_Dosimetry_Profile_Results.Expected` per taskid+DisplayName+Direction
- [ ] 10.7 Assign per-energy references for Wedge TestInstances — query `MQA_Dosimetry_Wedge_QueueItemExecutions.ExpectedValue` per taskid+energy
- [ ] 10.8 Re-evaluate `pass_fail` via `calculate_pass_fail()` for all TestInstances with tolerance + reference (including existing 38K Profile TIs that gain tolerances)
- [ ] 10.9 Verify pass_fail distribution per test list (no unexpected all-no_tol or all-action)

## 11. Verification

- [ ] 11.1 Verify data summary: session count, TI count, date range, and unit coverage per test list
- [ ] 11.2 Sample 3 sessions per type per unit — check pass_fail values are reasonable
- [ ] 11.3 Verify chart visibility: data visible in last 365 days for active types
- [ ] 11.4 Verify no duplicate TestListInstances (dedup working)
- [x] 11.5 Verify Python module compiles cleanly (`python -c "import qatrack.myqa_import"`)
- [x] 11.6 Run linting/type checks if available
