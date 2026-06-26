## MODIFIED Requirements

### Requirement: Shared Tests by condition name
Tests SHALL be named by the **enriched** form of their myQA condition name (per the `descriptive-test-names` capability), NOT the raw myQA name verbatim. The slug SHALL be `slugify_name(raw_condition_name)` (using the RAW name, before enrichment) without any list prefix. The same condition name across different tasks SHALL map to the same Test object (same slug), shared via TestListMembership.

#### Scenario: Condition shared across tasks
- **WHEN** task A and task B both have a condition named "Flatness"
- **THEN** one Test object with slug "flatness" is created, with TestListMemberships linking it to both TestLists

#### Scenario: Numbered condition enriched before display
- **WHEN** myQA condition name is `"01. Flatness"`
- **THEN** the Test is created with `name = "Flatness"` (enriched) and `slug = "01_flatness"` (from the raw name)

#### Scenario: Condition unique to one task
- **WHEN** a condition named "00. Barometer SN" appears in only one task
- **THEN** one Test object is created with `name = "Barometer Serial Number"` (number stripped + SN expanded) and `slug = "00_barometer_sn"`, linked to that task's TestList only
