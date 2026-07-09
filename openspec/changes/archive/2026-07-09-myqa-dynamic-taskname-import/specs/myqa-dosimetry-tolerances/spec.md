## MODIFIED Requirements

### Requirement: Tolerances not set during setup
The setup command SHALL NOT create or assign Tolerance records. All UnitTestInfo.tolerance_id values SHALL remain NULL after setup. Users configure tolerances manually through QATrack+ admin per unit/test after setup is complete.

This replaces the previous behavior where `get_or_create_tolerance` was called for each test spec, creating Tolerance records from myQA WarnOn/FailOn values. Shared tests cannot have conflicting tolerances across tasks, so automatic assignment is removed.

#### Scenario: Setup creates no tolerances
- **WHEN** setup_myqa_tests completes for any TaskName
- **THEN** no Tolerance records are created and all UnitTestInfo.tolerance_id = NULL

#### Scenario: Retroactive tolerance assignment removed
- **WHEN** a TestList already exists and setup runs again without --force
- **THEN** tolerances are still NOT set (no retroactive assignment)
