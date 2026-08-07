## ADDED Requirements

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
