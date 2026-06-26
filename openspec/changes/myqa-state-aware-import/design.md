## Context

The myQA import pipeline currently treats all test executions identically
regardless of their state, and collapses all PassFail tests in a session into
a single "Acceptance Criteria" result. This causes three problems:

1. **Empty results imported**: State=10 (not started) tests have NULL `Actual`
   values but are still imported as TestInstances with `value=None`, cluttering
   the review queue.
2. **Skipped tests indistinguishable**: State=60 (skipped) tests look the same
   as State=40 (completed) tests in QATrack+.
3. **PassFail data loss**: Sessions with N PassFail tests (e.g., 10 safety
   checks in an annual QA session) import only 1 — the first row returned by
   `extract_passfail`'s `fetchone()`.

## Goals / Non-Goals

**Goals:**
- State=10 tests are not imported (no TestInstance created for not-started tests)
- State=60 tests are imported with a `Skipped` status
- All PassFail tests in a session are imported, each as a separate Test
- The existing import for State=30/40/50 tests is unchanged (values imported
  normally, status = Unreviewed)

**Non-Goals:**
- Automatic pass/fail determination from myQA states (QATrack+ tolerances
  handle this)
- Importing myQA's internal tolerance evaluation (we import the measured value;
  QATrack+ applies its own tolerances)
- Changing how Numeric/Profile/Wedge/etc. conditions are keyed or shared

## Decisions

### D1: State filtering at extraction time

**Decision**: Filter State=10 conditions out during extraction, not during
import. `extract_numeric` and `extract_passfail` only return results for
tests with State >= 30. State metadata is returned alongside values so
`import_session` can apply the correct QATrack+ status.

**Rationale**: Keeps `import_session` simple — it receives a dict of
`{condition_name: {value, state}}` and maps states to statuses. Extraction
functions handle the myQA-specific state semantics.

### D2: Skipped TestInstanceStatus

**Decision**: Create a `Skipped` status with `valid=False`,
`requires_review=False`, `export_by_default=False`. Created by
`ensure_frequencies_exist()` analog (`ensure_statuses_exist()`) during setup,
idempotently.

**Rationale**: `valid=False` means skipped tests don't count towards
completion metrics. `requires_review=False` means they don't appear in the
unreviewed queue. `export_by_default=False` means they're excluded from
reports by default.

### D3: PassFail extraction returns per-test results

**Decision**: Rewrite `extract_passfail` to return all PassFail tests in a
session, keyed by a cleaned version of the myQA TestExecution Name. Each
entry includes the AcceptanceCriteria value and the test state.

Key format: the test execution Name (e.g., `"5.Tmt.Linac.Y.M03 - Jaw Position
Indicators"`) is used as the condition name. This means each PassFail test
becomes a separate shared Test in QATrack+, just like Numeric conditions.

**Rationale**: The current single-"Acceptance Criteria" approach loses data.
Using the test execution Name as the condition name preserves the one-Test-
per-condition model and makes each PassFail test individually reviewable.

**Consequence**: Setup discovery must also enumerate per-test PassFail
conditions (via `discover_passfail_conditions`) so that Tests/UTIs are
created for them. The old single "Acceptance Criteria" condition is replaced
by N per-test conditions.

### D4: State mapping table

**Decision**: A single mapping constant:

```python
MYQA_STATE_IMPORT = {
    10: "skip",       # Not started — don't create TestInstance
    30: "unreviewed",  # In progress — import if value present
    40: "unreviewed",  # Completed
    50: "unreviewed",  # Failed — import value, let QATrack+ tolerances flag it
    60: "skipped",     # Skipped / N/A
}
```

`import_session` uses this to decide whether to create a TestInstance and
what status to assign.

### D5: Backward-compatible condition discovery

**Decision**: `discover_conditions` still returns `{"name", "type", "source"}`
dicts. For PassFail, the names are now the per-test execution Names instead
of a single "Acceptance Criteria". The enrichment and slugification pipeline
is unchanged — PassFail test names go through the same `enrich_test_name` +
`slugify_name` path as Numeric conditions.

## Risks / Trade-offs

- **[Risk: PassFail test names are long/verbose]** → Mitigation: enrichment
  strips number prefixes; YAML overrides can shorten any specific name.
- **[Risk: State=30 with partial data imported]** → Mitigation: import the
  value if present; QATrack+ shows it as Unreviewed for the physicist to
  confirm.
- **[Risk: Existing "Acceptance Criteria" Tests orphaned after rebuild]**
  → Mitigation: `clear_myqa_data` deletes everything; rebuild creates the
  new per-test PassFail Tests from scratch.
