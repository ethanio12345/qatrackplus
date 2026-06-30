## ADDED Requirements

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
