## ADDED Requirements

### Requirement: LINAC_MAP covers all production devices

The `LINAC_MAP` dictionary in `myqa_import.py` SHALL include every real device
in the myQA production database (~95 entries), organized by unit number. Each
entry maps a QATrack+ unit number to one or more myQA `RadiationDeviceName`
strings. Devices renamed over time SHALL have both current and legacy names
mapped to the same unit number.

#### Scenario: Legacy device name alias

- GIVEN the device `CPMCC MRI23_Magnetom Vida 3T` was renamed to
  `CPMCC MRI23 Magnetom Vida 3T` in myQA
- WHEN the LINAC_MAP is configured
- THEN unit 101 SHALL map to `["CPMCC MRI23 Magnetom Vida 3T",
  "CPMCC MRI23_Magnetom Vida 3T"]`
- AND sessions from both device names SHALL import to the same QATrack+ unit

#### Scenario: Physics equipment individual unit

- GIVEN the ion chamber `CPMCC (F) NE 2571 - 3708` has 17 tasks in myQA
- WHEN the LINAC_MAP is configured
- THEN unit 300 SHALL map to `"CPMCC (F) NE 2571 - 3708"`
- AND `query_new_sessions` SHALL find sessions for this device

### Requirement: QATrack+ Unit records created for all devices

The system SHALL create QATrack+ `Unit` records for every unit number in
`LINAC_MAP` that does not already exist. Each Unit SHALL have:

- `number`: the unit number from LINAC_MAP
- `name`: the primary device name (first entry if list, otherwise the string)
- `site`: the appropriate Site record (CPMCC or BCHC based on device name prefix)
- `type`: the appropriate UnitType for the device category
- `active`: True

#### Scenario: Unit creation for new ion chamber

- GIVEN unit 300 does not exist in QATrack+ and maps to
  `CPMCC (F) NE 2571 - 3708`
- WHEN the unit creation script runs
- THEN a Unit SHALL be created with number=300, name=`CPMCC (F) NE 2571 - 3708`
- AND the Unit SHALL be associated with the CPMCC site
- AND the Unit type SHALL reflect "ion chamber" or equivalent

#### Scenario: Existing unit not modified

- GIVEN unit 3 already exists as "LA317"
- WHEN the unit creation script runs
- THEN unit 3 SHALL NOT be modified
- AND its existing name, site, and type SHALL be preserved

### Requirement: UNITS_PER_LIST covers all new test lists

The `UNITS_PER_LIST` dictionary SHALL include an entry for every test list
slug, specifying which unit numbers are applicable. Physics equipment lists
SHALL include all relevant equipment unit numbers.

#### Scenario: Physics equipment list units

- GIVEN the test list `myqa_physics` covers chambers, thermometers,
  barometers, electrometers, and well chambers
- WHEN UNITS_PER_LIST is configured
- THEN `myqa_physics` SHALL include all unit numbers in ranges 300–499
- AND each unit SHALL have its UTIs created during setup

#### Scenario: CT daily list scoped to CT unit

- GIVEN the test list `myqa_ct_daily` targets CT simulator daily QA
- WHEN UNITS_PER_LIST is configured
- THEN `myqa_ct_daily` SHALL list only unit 100

### Requirement: Unit numbering scheme

Unit numbers SHALL follow a categorized scheme to keep related devices grouped:

| Range | Category |
|---|---|
| 1–9 | Treatment LINACs |
| 50 | DXR orthovoltage |
| 100–109 | Imaging (CT, MRI) |
| 200–209 | Brachytherapy (HDR) |
| 300–319 | CPMCC field ion chambers |
| 320–329 | Secondary standard chambers |
| 330–349 | Reference/scanning chambers |
| 350–359 | Well chambers |
| 360–389 | Thermometers |
| 390–399 | Barometers |
| 400–409 | Electrometers |
| 410–429 | Survey meters / OSLDs / neutron detectors |
| 430–449 | Detectors / phantoms (MatrixX, SRS, etc.) |
| 450–479 | BCHC chambers / electrometers |
| 480–499 | Audits / safety / security |

#### Scenario: Numbering collision avoidance

- GIVEN an existing unit at number 5 (LA512)
- WHEN physics equipment units are assigned numbers
- THEN no physics equipment SHALL use numbers 1–9
- AND the numbering scheme SHALL maintain gaps for future additions
