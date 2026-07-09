## ADDED Requirements

### Requirement: One PDF per selected UTC
The archive SHALL render exactly one PDF per UnitTestCollection returned by the selection function, using the existing `TestListInstanceDetailsReport` render engine scoped to that UTC and the report window.

#### Scenario: Each selected UTC yields one PDF
- **WHEN** the archive runs over a selection of N UTCs
- **THEN** exactly N PDFs are rendered, one per UTC, each containing only that UTC's TestListInstances within the window

#### Scenario: UTC with no data in window skipped
- **WHEN** a UTC appears in the selection but, at render time, has no TLIs in the window
- **THEN** no PDF is rendered for it and the UTC is listed in the summary as skipped

### Requirement: PDF naming and packaging
Rendered PDFs SHALL be named `{list_slug}_{YYYY-MM}.pdf` and organized inside the archive zip under a per-unit subdirectory `{unit_slug}/`. The zip SHALL be named `linac_qa_archive_{YYYY-MM}.zip`.

#### Scenario: Naming within zip
- **WHEN** unit "LA317: 2972" has UTC "Daily Constancy Check" archived for June 2026
- **THEN** the zip contains an entry at `la317-2972/daily-constancy-check_2026-06.pdf` (slugs per Django's `slugify`)

### Requirement: Archive delivery via email or filesystem
The archive SHALL support delivery as an emailed zip attachment (or link) to a configured Group/User list AND/OR write the zip to a configurable filesystem path.

#### Scenario: Email delivery
- **WHEN** `archive_linac_qa --window month --email physicists` runs
- **THEN** a single zip is produced and emailed to the specified group

#### Scenario: Filesystem delivery
- **WHEN** `archive_linac_qa --window month --out-dir /var/qa_archives` runs
- **THEN** the zip is written to `/var/qa_archives/linac_qa_archive_2026-06.zip` and no email is sent

### Requirement: Size guard for email attachment
The system SHALL enforce a maximum zip size for email delivery (configurable, default 24 MB). If the zip exceeds it, the email SHALL include a link/path to the rendered archive instead of attaching it, and SHALL warn in the command output.

#### Scenario: Oversize zip not attached
- **WHEN** the rendered zip is 40 MB and the email limit is 24 MB
- **THEN** the email body states the archive is too large to attach and provides the on-site path/URL, and the zip is NOT attached

### Requirement: Scheduled monthly generation
The archive SHALL be invocable as a django-q scheduled task covering the previous calendar month, runnable on the 1st of each month.

#### Scenario: Monthly schedule
- **WHEN** the django-q schedule fires on 2026-07-01
- **THEN** the archive renders for window 2026-06-01 to 2026-06-30 and emails the configured recipients
