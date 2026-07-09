## ADDED Requirements

### Requirement: Restore old TestLists from backup
The system SHALL provide a management command `import_old_qatrack` that reads a PostgreSQL custom-format backup file and restores TestLists, Tests, TestListInstances, and TestInstances into the current database.

#### Scenario: Restore from backup file
- **WHEN** `import_old_qatrack --file /path/to/qatrackplus.custom` runs
- **THEN** all TestLists from the backup are created in the current database (with ID remapping to avoid conflicts)

### Requirement: Preserve old TestList names and test structure
The old TestLists (Solid Water, MPC, CatPhan, etc.) SHALL be imported with their original names and test definitions. Tests SHALL retain their original names, slugs, and types.

#### Scenario: Solid Water list preserved
- **WHEN** the backup contains "Solid Water: Photon 6X" (slug: solid-water-photon-6x)
- **THEN** a TestList with name "Solid Water: Photon 6X" and slug "solid-water-photon-6x" is created in the current database

### Requirement: Remap IDs to avoid conflicts
The import SHALL remap all primary keys (TestList.id, Test.id, TestListInstance.id, TestInstance.id) to new values that don't conflict with existing data. Foreign key relationships SHALL be preserved through the remapping.

#### Scenario: ID conflict avoided
- **WHEN** the backup has a Test with id=5 and the current DB also has a Test with id=5
- **THEN** the imported Test gets a new auto-generated id; all TestInstances referencing it are updated to the new id

### Requirement: Remap unit references
The import SHALL map old unit numbers to current unit numbers. If the old and new unit numbering schemes differ, a mapping table SHALL be applied.

#### Scenario: Same unit numbering
- **WHEN** old DB unit 3 = LA317 and current DB unit 3 = LA317
- **THEN** TestInstances and UTCs reference unit 3 directly

### Requirement: Bulk import for performance
The import SHALL use bulk_create with batch_size=5000 for TestInstances to handle the 3.3M rows efficiently. Total import time SHALL be under 30 minutes.

#### Scenario: Large backup imported efficiently
- **WHEN** the backup contains 3.3M TestInstances
- **THEN** the import completes using bulk inserts and finishes within 30 minutes
