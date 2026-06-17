# myQA Schema Dump Request

## Context
The `fix-myqa-importers` change corrects broken SQL importers in QATrack+ that
assumed wrong table/column names. Before the design can be finalized, we need the
**actual** schema of the myQA database plus a small sample of real data, to verify
every column name and resolve several contradictions. The previous attempt
(`full-myqa-sync`) failed precisely because of unverified schema assumptions —
please don't skip any query below.

## Environment
- myQA database (production or recent restore). Engine is Sybase SQL Anywhere
  (uses the `sp_columns` procedure and `systable` catalog).
- Read-only access is fine. **Do not modify any data.**

## Step 1 — Discover all myQA tables
List every candidate table (we don't yet know the VMAT/CBCT/Planar result table
names):

```sql
SELECT t.table_name
FROM systable t
WHERE t.table_type = 'BASE'
  AND ( t.table_name LIKE 'MQA_%'
     OR t.table_name LIKE '%TestExecution%'
     OR t.table_name LIKE '%MlcQA%'
     OR t.table_name LIKE '%IsoCheck%'
     OR t.table_name LIKE '%Planar%'
     OR t.table_name LIKE '%CBCT%'
     OR t.table_name LIKE '%VMAT%' )
ORDER BY t.table_name;
```
Paste the full list back.

## Step 2 — Column dump for each known table
For **each** table below, run `sp_columns` and paste the result
(column_name, type_name, length, nullable):

1. `MQA_Numeric_TestConditionExecutions`
2. `MQA_Numeric_TestExecutions`
3. `MQA_TestConditions`  ← **critical**: confirm whether this table exists at all
4. `MQA_MDL_MlcQA_Results`
5. `MQA_MDL_MlcQA_QueueItemExecutions`
6. `MQA_IsoCheck_WinstonLutz_TestExecutions`
7. Whatever tables from Step 1 cover VMAT, CBCT, and Planar image results.

```sql
sp_columns 'MQA_Numeric_TestConditionExecutions';   -- repeat per table
```

## Step 3 — Resolve specific contradictions
Each question below must be answered definitively with the actual column names.

- **Q1 — Tolerance columns on `MQA_Numeric_TestConditionExecutions`.** Are the
  columns named `WarnOn` / `FailOn`, or `WarningTolerance` / `ErrorTolerance`, or
  both, or neither? (Working `setup_myqa_tests.py` reads
  `WarningTolerance`/`ErrorTolerance`; the proposed fix reads `WarnOn`/`FailOn`.
  They cannot both be right.)
- **Q2 — Does `MQA_TestConditions` exist?** If yes, dump its columns. If the
  query errors "table not found", say so explicitly.
- **Q3 — MLC foreign key.** On `MQA_MDL_MlcQA_Results`, which column links to the
  parent execution: `MlcQATestExecutionBase_Id`, `MlcQAQueueItemExecution_Id`, or
  something else? List every column whose name contains `Id`, `Execution`, or
  `Queue`.
- **Q4 — MLC metric columns.** On `MQA_MDL_MlcQA_Results`, list every column whose
  name contains `Peaks`, `Leaves`, `Value`, `Result`, `Tolerance`, `Warn`, `Fail`,
  or `Acceptance`.
- **Q5 — Winston-Lutz columns.** On `MQA_IsoCheck_WinstonLutz_TestExecutions`,
  confirm `MaximumDeviation2D`, `Deviation3D`, `Tolerance_Warn`, `Tolerance_Fail`.
  List every numeric/value column on the table.

## Step 4 — Sample data (2 rows each)
For each table in Step 2, return 2 representative rows so we can see real values
(especially actual task names, metric values, tolerance formats):

```sql
SELECT TOP 2 * FROM <table>;
```

For the numeric-executions table, additionally run:

```sql
SELECT TOP 20 DISTINCT te.TaskName
FROM <numeric-executions-table> te
WHERE te.TaskName LIKE '5.Tmt.Linac.%' OR te.TaskName LIKE '5.Tmt.DXR.%'
ORDER BY te.TaskName;
```
We need to settle whether Numeric executions live under `.N%`, `.D%`, or `.D2%`.

## Output format
Paste raw query output. No need to format — as long as table and column names are
unambiguous.

## Where it goes
Results get transcribed into
`openspec/changes/fix-myqa-importers/explore-brief.md` as the verified-schema
baseline, which unblocks the proposal/design/specs revision.
