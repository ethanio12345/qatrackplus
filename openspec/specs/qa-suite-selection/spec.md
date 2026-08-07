# Qa Suite Selection Specification

## Purpose

Capability promoted from the `linac-qa-report-archive` OpenSpec change (see
`openspec/changes/archive/...` for design context).
## Requirements
### Requirement: Select canonical linac QA suites by structural rule
The system SHALL provide a selection function that returns UnitTestCollections for archiving. A UTC SHALL be included if and only if: `active=True`, the unit's type is a linac/treatment unit, the UTC's `frequency__name` is in the configurable allow-set (default {Daily, Weekly, Monthly, Quarterly, Semi Annual, Annual}), AND the UTC has at least one TestListInstance with `work_completed` inside the report window.

#### Scenario: Empty UTC excluded
- **WHEN** a UTC has frequency "Daily" but zero TestListInstances in the window
- **THEN** the UTC is NOT included in the selection

#### Scenario: Once-Off / Other frequency excluded
- **WHEN** a UTC has frequency "Other" or "Once Off" (e.g. "Testing", "zIsocenters_Test")
- **THEN** the UTC is NOT included, even if it ran in the window

#### Scenario: Stale UTC excluded
- **WHEN** a UTC has frequency "Monthly" but its last TestListInstance is older than the window start
- **THEN** the UTC is NOT included

#### Scenario: Canonical suite included
- **WHEN** a UTC has frequency "Daily", `active=True`, on a linac, and has TestListInstances within the window
- **THEN** the UTC IS included

#### Scenario: Non-linac unit excluded
- **WHEN** a UTC's unit type is a chamber, thermometer, or other non-treatment device
- **THEN** the UTC is NOT included, regardless of frequency or data

### Requirement: Configurable window and frequency set
The selection function SHALL accept a `window` (start/end datetimes) and an optional `freqs` override (iterable of frequency names). The defaults SHALL cover the previous calendar month and the six canonical QA frequencies.

#### Scenario: Default window is previous calendar month
- **WHEN** selection runs on 2026-07-05 with no window override
- **THEN** the window is 2026-06-01 00:00 to 2026-06-30 23:59 (local time)

#### Scenario: Frequency override
- **WHEN** selection is called with `freqs=["Daily"]`
- **THEN** only Daily-frequency UTCs with data in the window are returned

### Requirement: Dry-run preview of selection
The management command SHALL support a `--dry-run` flag that prints the selected UTC list (unit, name, frequency, TLI count in window) WITHOUT rendering any PDF.

#### Scenario: Dry-run output
- **WHEN** `archive_linac_qa --dry-run --window month` runs
- **THEN** the command prints each selected UTC's unit, name, frequency, and TLI count, and writes no files

### Requirement: Linac unit-type allowlist is config-driven
The set of `UnitType.name` strings treated as "linacs" by `select_archive_utcs` (and `clear_stale_due_dates --linacs-only`) SHALL be read from `centre_config["linac_unit_type_names"]` via a `get_linac_unit_type_names()` function, rather than being hardcoded at module level.

The default value SHALL include `"Treatment LINAC"` (the UnitType emitted by `create_myqa_units`) alongside the existing entries (`"TrueBeam"`, `"Synergy"`, `"Agility"`, `"Clinac"`, `"Edge"`, `"Halcyon"`). This fixes a latent bug where myQA-created linacs (including RFT26 / unit 437) were silently invisible to linac-scoped operations.

#### Scenario: RFT26 included in archive selection
- **WHEN** `select_archive_utcs` is called for a `lastmonth` window
- **AND** unit 437 (RFT26) has TLIs in that window
- **AND** unit 437's `UnitType.name == "Treatment LINAC"`
- **THEN** unit 437 is included in the selected UTCs

#### Scenario: RFT26 processed by stale-due-date cleanup
- **WHEN** `clear_stale_due_dates --linacs-only` is invoked
- **THEN** unit 437's UTCs are evaluated for stale due dates (previously skipped)

#### Scenario: Centre overrides linac types
- **WHEN** a centre's `centre_config["linac_unit_type_names"]` is `["Linac", "Treatment LINAC"]`
- **THEN** `get_linac_unit_type_names()` returns `("Linac", "Treatment LINAC")`
- **AND** `select_archive_utcs` honours the centre's allowlist

