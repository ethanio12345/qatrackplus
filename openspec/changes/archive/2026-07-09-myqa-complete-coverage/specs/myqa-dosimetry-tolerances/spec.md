## ADDED Requirements

### Requirement: Profile tolerances via discover_setup_tests

The `MyqaProfileImport` class SHALL implement `discover_setup_tests()` that
queries `MQA_Dosimetry_Profile_Results` joined through the full execution chain
to `DVC_RadiationDeviceEnergy` and `DVC_EnergyType`, extracting distinct
DisplayName × ProfileDirection × EnergyValue × IsFlatteningFilterFree
combinations with MAX(Warn), MAX(Fail) tolerance values.

The generated Test slugs MUST include the energy tag to match the slugs emitted
by `extract_results` (e.g., `mtx_flat_il_6x`, not `mtx_flat_il`).

#### Scenario: Profile tolerance discovery with energy dimension

- GIVEN `MQA_Dosimetry_Profile_Results` contains rows with
  DisplayName='Flatness', ProfileDirection=1 (inline), and the session used
  6X beam (EnergyValue=6, IsFlatteningFilterFree=False)
- WHEN `MyqaProfileImport.discover_setup_tests()` runs
- THEN a spec SHALL be generated with slug `mtx_flat_il_6x`
- AND the spec SHALL include warn/fail from MAX aggregation
- AND a separate spec SHALL be generated for `mtx_flat_il_10x` if 10X data exists

#### Scenario: FFF energy variant discovered

- GIVEN profile data exists for 10X-FFF (EnergyValue=10, IsFlatteningFilterFree=True)
- WHEN discovery runs
- THEN a spec SHALL be generated with slug `mtx_flat_il_10fff`
- AND it SHALL be distinct from the `mtx_flat_il_10x` (non-FFF) spec

### Requirement: Profile per-session references

The Profile `extract_results` method SHALL capture the `Expected` column from
`MQA_Dosimetry_Profile_Results` for each result row, and the import engine
SHALL create per-TestInstance Reference objects from these Expected values.

#### Scenario: Profile reference from Expected

- GIVEN a profile result row with Actual=1.574, Expected=1.512 for Flatness
- WHEN the session is imported
- THEN the TestInstance SHALL have value=1.574
- AND a Reference with value=1.512 SHALL be assigned
- AND pass_fail SHALL evaluate diff = 1.574 - 1.512 = 0.062 against
  tolerance (warn=0.7, fail=1.0) → OK

### Requirement: Wedge tolerances via discover_setup_tests

The `MyqaWedgeImport` class SHALL implement `discover_setup_tests()` that
queries `MQA_Dosimetry_Wedge_QueueItemExecutions` joined with
`MQA_Dosimetry_Wedge_TestExecutions` for distinct energy values, extracting
Tolerance_Warn, Tolerance_Fail, and average ExpectedValue.

#### Scenario: Wedge tolerance discovery per energy

- GIVEN wedge data exists for energy 6X with Tolerance_Warn=0.01,
  Tolerance_Fail=0.02, ExpectedValue≈0.649
- WHEN discovery runs
- THEN a spec SHALL be generated for slug `mtx_wedge_cont_6x`
- AND warn=0.01, fail=0.02
- AND a Reference with value=0.649 SHALL be assigned as the baseline

### Requirement: Wedge pattern fix

The `MyqaWedgeImport.task_name_patterns` SHALL use the same monthly dosimetry
task patterns as Output and Profile, because wedge data lives in those same
sessions — not in tasks with "Wedge" in the name.

#### Scenario: Wedge sessions found

- GIVEN myQA has 1,052 wedge test executions under task name
  `5.Tmt.Linac.M.Dosimetry - Monthly QA`
- WHEN the Wedge importer runs with corrected patterns
- THEN sessions SHALL be found for all LINAC devices
- AND the skip-empty guard SHALL filter sessions without wedge data
- AND wedge TestInstances SHALL be created under `matrix-dosimetry-import`

### Requirement: Energy tolerances via discover_setup_tests

The `MyqaEnergyImport` class SHALL implement `discover_setup_tests()` that
queries `MQA_Dosimetry_Energy_ChamberExecutions` for distinct
energy/chamber combinations with WarningTolerance/ErrorTolerance.

#### Scenario: Energy chamber discovery

- GIVEN energy chamber data exists for 6X chamber 1 with
  WarningTolerance=0.02, ErrorTolerance=0.03
- WHEN discovery runs
- THEN a spec SHALL be generated for slug `mtx_energy_6x_ch1`
- AND warn=0.02, fail=0.03

### Requirement: Energy pattern fix

The `MyqaEnergyImport.task_name_patterns` SHALL use the same monthly
dosimetry patterns as Output/Profile/Wedge.

#### Scenario: Energy sessions found

- GIVEN myQA has 16 energy test executions
- WHEN the Energy importer runs with corrected patterns
- THEN sessions SHALL be found (primarily on DUMMY LINAC)
- AND the skip-empty guard SHALL filter sessions without energy data

### Requirement: Setup command assigns tolerances to UnitTestInfo

The `setup_myqa_tests.py` command SHALL assign the `tolerance` FK on each
`UnitTestInfo` record during creation, not just create orphan Tolerance
objects.

#### Scenario: UTI tolerance assignment during setup

- GIVEN a test spec has warn=0.7, fail=1.0
- WHEN setup creates the UnitTestInfo for unit 3
- THEN the UTI SHALL have tolerance set to the Tolerance(type='absolute',
  tol_low=-0.7, tol_high=0.7, act_low=-1.0, act_high=1.0)

#### Scenario: Retroactive UTI tolerance assignment

- GIVEN UTIs exist from a previous setup run without tolerances
- WHEN setup runs again (without --force)
- THEN existing UTIs SHALL have their tolerance FK updated if currently NULL
- AND no UTIs SHALL be deleted or recreated

### Requirement: Tolerance deduplication robustness

The `get_or_create_tolerance` function SHALL handle cases where the
auto-generated Tolerance name collides with an existing Tolerance that has
different field values, by falling back to a name-based lookup.

#### Scenario: Name collision fallback

- GIVEN a Tolerance named `Percent(-0.01%, -0.01%, 0.01%, 0.01%)` already
  exists
- AND a new spec generates fields that produce the same name via different
  field combinations
- WHEN `get_or_create_tolerance` is called
- THEN it SHALL catch the IntegrityError
- AND fall back to `Tolerance.objects.filter(name=<generated_name>).first()`
- AND return the existing Tolerance without raising

### Requirement: matrix-dosimetry-import in UNITS_PER_LIST

The `UNITS_PER_LIST` dictionary SHALL include `"matrix-dosimetry-import"` with
units `[1, 2, 3, 4, 5, 7, 8, 50]`, so that `setup_myqa_tests` creates
UnitTestCollections and UnitTestInfos for Profile, Wedge, and Energy tests
on all LINAC and DXR units.

#### Scenario: UTC creation for matrix-dosimetry-import

- GIVEN `matrix-dosimetry-import` is in UNITS_PER_LIST with units [1-8, 50]
- WHEN `setup_myqa_tests` runs for Profile/Wedge/Energy
- THEN UnitTestCollections SHALL be created for each unit
- AND UnitTestInfos SHALL be created for each unit × test combination

### Requirement: No --force for shared matrix-dosimetry-import

The `setup_myqa_tests` command SHALL NOT be run with `--force` for
Profile, Wedge, or Energy importers, because all three share the `mtx_` slug
prefix and `matrix-dosimetry-import` test list. Using `--force` would delete
ALL existing `mtx_` Tests and their TestInstances across all three importers.

#### Scenario: Retroactive tolerance assignment without data loss

- GIVEN 232 `mtx_` Tests and 38K+ TestInstances already exist from prior imports
- WHEN `setup_myqa_tests` runs WITHOUT `--force` for Profile
- THEN existing Tests SHALL be preserved (get_or_create by slug)
- AND existing TestInstances SHALL NOT be deleted
- AND new tolerances SHALL be assigned to UTIs that currently have NULL tolerance

### Requirement: Pass/fail evaluation for all tolerance-bearing TestInstances

After import, all TestInstances that have both `tolerance` and `reference` set
SHALL have their `pass_fail` field evaluated via `calculate_pass_fail()`.

#### Scenario: Profile pass/fail evaluation after tolerance assignment

- GIVEN 38,732 Profile TestInstances exist with tolerance but no reference
- WHEN references are assigned from Expected values
- AND pass_fail is re-evaluated
- THEN each TI SHALL have pass_fail set to 'ok', 'tolerance', or 'action'
  based on the tolerance comparison
- AND the 'no_tol' pass_fail SHALL only remain for TIs without tolerance
