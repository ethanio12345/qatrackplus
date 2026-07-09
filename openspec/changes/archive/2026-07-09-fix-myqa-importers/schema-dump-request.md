# myQA Schema Dump Request

## Context
The `fix-myqa-importers` change corrects broken SQL importers in QATrack+ that
assumed wrong table/column names. Before the design can be finalized, we need the
**actual** schema of the myQA database plus a small sample of real data, to verify
every column name and resolve several contradictions. The previous attempt
(`full-myqa-sync`) failed precisely because of unverified schema assumptions —
please don't skip any query below.

## Environment
- myQA database (production or recent restore). Engine is **Microsoft SQL Server**
  (verified via `pymssql` against production). Uses `sp_columns`, plus the
  `syscolumns` / `systypes` / `OBJECT_ID()` catalog functions for Steps 5.3–5.5.
- Read-only access is fine. **Do not modify any data.**
- Note: Steps 1–4 below were written before the engine was confirmed and use
  Sybase-style `systable`; they ran successfully anyway. Step 5 uses proper
  SQL Server catalog syntax.

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

## Step 5 — Follow-up (resolve gaps from first dump)
The first dump (now transcribed into `explore-brief.md`) resolved the
column-name contradictions but left five gaps. Please run the queries below and
paste output.

### 5.1 — Numeric task-name patterns (critical)
We still don't know which task-name prefix selects daily-QA Numeric executions.
The source uses `.N%`, the main spec uses `.D2%`, and the proposed spec uses `.D%`.
Settle it:

```sql
SELECT TOP 30 DISTINCT te.TaskName
FROM MQA_TestExecutions te
JOIN MQA_TestImplementationExecutions tie ON te.Id = tie.Id
JOIN MQA_Numeric_TestConditionExecutions tcne ON tie.Id = tcne.NumericTestExecution_Id
WHERE te.TaskName LIKE '5.Tmt.Linac.%' OR te.TaskName LIKE '5.Tmt.DXR.%'
ORDER BY te.TaskName;
```

### 5.2 — One sample row from each results/condition table
Tolerance format (fraction vs percent), `Verdict` encoding (0/1 vs 1/2), and real
`Name` strings all need to be seen. For each table, run `SELECT TOP 1 *` and paste
the column=value list:

```sql
SELECT TOP 1 * FROM MQA_Numeric_TestConditionExecutions;
SELECT TOP 1 * FROM MQA_PassFail_TestExecutions;
SELECT TOP 1 * FROM MQA_MDL_Cbct_Results;
SELECT TOP 1 * FROM MQA_MDL_Planar_Results;
SELECT TOP 1 * FROM MQA_MDL_VmatDmlc_Results;
```

### 5.3 — Full VMAT column list (critical)
The first dump captured `RoiMean` / `RoiStandardDeviation` tolerance columns but
**no corresponding `_Result_Value_Value` or `_ExpectedValue_Value`**. Without the
measured-value column, VMAT can't be implemented. List every column so we can find
where the measured value lives:

```sql
SELECT c.name, t.name AS type, c.length, c.is_nullable
FROM syscolumns c
JOIN systypes t ON c.xtype = t.xtype
WHERE c.id = OBJECT_ID('MQA_MDL_VmatDmlc_Results')
ORDER BY c.colorder;
```

### 5.4 — CBCT / Planar non-conforming columns
Several columns don't fit the `{Metric}_Result_Value_Value` pattern
(`SliceWidthDifference_Value`, `MaxHuDeviationRoi`, `MinUniformityRoi`,
`EnergyType`, `EnergyValue`). To confirm what exists and which need their own
slugs, dump full columns for both tables:

```sql
SELECT 'CBCT' AS src, c.name, t.name AS type, c.length
FROM syscolumns c JOIN systypes t ON c.xtype = t.xtype
WHERE c.id = OBJECT_ID('MQA_MDL_Cbct_Results')
UNION ALL
SELECT 'Planar', c.name, t.name AS type, c.length
FROM syscolumns c JOIN systypes t ON c.xtype = t.xtype
WHERE c.id = OBJECT_ID('MQA_MDL_Planar_Results')
ORDER BY src, c.name;
```

### 5.5 — Wedge tolerance column (sanity check)
The first dump hedged between `Tolerance_Warn`, `WarningTolerance`, and `WarnOn`
on `MQA_Dosimetry_Wedge_TestExecutions`. Wedge is out of scope, but settle it so
the schema reference is internally consistent:

```sql
SELECT c.name
FROM syscolumns c
WHERE c.id = OBJECT_ID('MQA_Dosimetry_Wedge_TestExecutions')
  AND (c.name LIKE '%Tolerance%' OR c.name LIKE 'Warn%' OR c.name LIKE 'Fail%');
```

## Output format
Paste raw query output. No need to format — as long as table and column names are
unambiguous.

## Where it goes
Results get appended into
`openspec/changes/fix-myqa-importers/explore-brief.md` (schema reference section)
and feed the slug→column mapping tables in the design exploration, which unblocks
the proposal/design/specs revision.
