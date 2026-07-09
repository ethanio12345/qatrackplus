# PassFail Import

> Implements Pattern D (degenerate) per `design.md`. Single text field, no
> numeric value, no tolerance. Per D3: `MQA_PassFail_TestExecutions` has only
> `Id` and `AcceptanceCriteria` — there is no `PassStatus` column.

## Requirements

### R1: Read AcceptanceCriteria text

The system SHALL read only `AcceptanceCriteria` (nvarchar) from
`MQA_PassFail_TestExecutions`. There is no `PassStatus` column (verified
schema, Key Finding #3). The existing broken code at `myqa_import.py:282-291`
reads `pfte.PassStatus` and `tc.Name` via `MQA_TestConditions` — both
non-existent; both removed.

### R2: JOIN path (standard, filter te.TaskExecutionId)

```sql
SELECT pfte.AcceptanceCriteria
FROM MQA_PassFail_TestExecutions pfte
JOIN MQA_TestImplementationExecutions tie ON pfte.Id = tie.Id
JOIN MQA_TestExecutions te ON tie.Id = te.Id
WHERE te.TaskExecutionId = %s
```

### R3: Single test, string_value, no tolerance

The system SHALL emit ONE test instance per execution:
- slug = `myqa_passfail_acceptance_criteria`
- value stored as `string_value` (via `myqa_import.py:220` isinstance(str) branch)
- no Tolerance (PassFail is non-numeric)
- pass_fail = `no_tol` (engine default; D4 deferred)

### R4: Setup hardcoded

Setup SHALL create a single Test (`myqa_passfail_acceptance_criteria`, type
`string`) and the `myqa_passfail` TestList. No discovery query, no Tolerance.

## Scenarios

**Scenario: PassFail import (happy path)**

- GIVEN a PassFail execution with AcceptanceCriteria=`Visual check OK, no deviations`
- WHEN imported
- THEN a TestInstance SHALL be created with slug
  `myqa_passfail_acceptance_criteria` and string_value=`Visual check OK, no deviations`

**Scenario: NULL AcceptanceCriteria**

- GIVEN a PassFail execution where AcceptanceCriteria IS NULL
- WHEN imported
- THEN a TestInstance SHALL be created with string_value=None
- AND no exception SHALL be raised

**Scenario: Long AcceptanceCriteria text**

- GIVEN a PassFail execution with AcceptanceCriteria containing 500+ characters
- WHEN imported
- THEN the full text SHALL be stored as string_value
- AND the Test.type SHALL be `string` (not numerical) so no float cast is attempted

**Scenario: Empty result set**

- GIVEN an execution_id with no row in `MQA_PassFail_TestExecutions`
- WHEN `extract_results` runs
- THEN the result dict SHALL contain only the `{list_slug}_taskid` dedup key
- AND `import_session` SHALL create a TestListInstance with no child TestInstances
