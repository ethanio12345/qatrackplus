# myQA Operational Scripts Reference

Reference for every Layer 4 maintenance command in the myQA import system. Covers what each does, when to run it, expected output, and idempotency notes. Applies to both new-centre deployments and ongoing BCHC operation.

## Commands at a glance

| Command | Purpose | Cadence | Idempotent |
|---|---|---|---|
| [`clear_myqa_data`](#clear_myqa_data) | Delete all myQA-sourced data (destructive reset) | Manual only | Yes (deletes everything; safe to re-run) |
| [`clear_stale_due_dates`](#clear_stale_due_dates) | Clear due_dates on UTCs that haven't run in `max(180d, 3× nominal_interval)` | Monthly | Yes |
| [`set_angular_wraparound`](#set_angular_wraparound) | Convert angular tests to `type=wraparound` and re-evaluate pass_fail | Quarterly or after new angular tests | Yes |
| [`auto_approve_tlis`](#auto_approve_tlis) | Bulk auto-approve TLIs where all tests pass | After import with new AutoReviewRuleSet | Yes |
| [`approve_myqa_taskids`](#approve_myqa_taskids) | Set all `*_taskid` TestInstances to Approved (dedup metadata) | After setup/import | Yes |
| [`delete_empty_tlis`](#delete_empty_tlis) | Delete valueless TLIs (real tests but all values NULL) | Manual cleanup; rare now (engine prevents new ones) | Yes (carefully) |
| [`myqa_validate`](#myqa_validate) | Read-only diff against myQA — surface silent drops | Monthly or after big imports | Yes (read-only) |

---

## `clear_myqa_data`

**Purpose:** Delete all myQA-sourced data (TestLists, Tests, TestInstances, UTCs, UTIs, Tolerances, References) in FK-safe order. Use when you want a clean slate.

**When to run:** Effectively never in production. Useful in dev for testing setup/import from scratch.

**Algorithm:** Identifies myQA data by stable patterns — slug prefixes `myqa_` / `mtx_` and description prefix `"Auto-created TestList for myQA TaskName"`. Deletes in FK-safe order: TestInstance → TestListInstance → UnitTestInfo → UnitTestCollection → TestListMembership → Test → TestList → Tolerance → Reference.

**Sample output:**
```
$ uv run python manage.py clear_myqa_data --yes
Deleting 242 TestLists, 1950 Tests, ...
Done in 12.4s
```

**Idempotency:** Yes — re-running finds nothing to delete.

**⚠️ Destructive.** Confirm with `--dry-run` first (default). The `--yes` flag is required for actual deletion.

---

## `clear_stale_due_dates`

**Purpose:** Clear `due_date` (set to `None`) and `auto_schedule` (set to `False`) on UTCs that haven't run in a frequency-aware stale window: `max(180 days, 3 × nominal_interval)`.

**When to run:** Monthly. Prevents stale UTCs (e.g. for decommissioned units or discontinued TaskNames) from cluttering the scheduling view.

**Algorithm:** For each UTC, compute its stale threshold from its Frequency's `nominal_interval` (or fall back to 180 days). If `last_instance.work_completed` is older than the threshold (or `last_instance` is NULL and the UTC is older than the threshold), null out `due_date` and disable `auto_schedule`.

**Flags:**
- `--linacs-only` — limit to UTCs whose unit type is in `get_linac_unit_type_names()` (config-driven; includes `"Treatment LINAC"`).
- `--apply` — actually modify (default is dry-run preview).
- `--floor N` — override the 180-day floor.
- `--multiplier N` — override the 3× multiplier.

**Sample output:**
```
$ uv run python manage.py clear_stale_due_dates --linacs-only
DRY RUN — 12 UTCs would be cleared. Re-run with --apply to proceed.
  unit 7 / list daily_constancy_check (last 2024-03-15, threshold 180d)
  ...
```

**Idempotency:** Yes — already-cleared UTCs are no-ops.

---

## `set_angular_wraparound`

**Purpose:** Convert angular/rotational Tests (gantry/collimator/couch angle indicators, rotation accuracy, etc.) from `type=simple` to `type=wraparound` with bounds `[0, 360]`. Re-evaluates `pass_fail` on all their TestInstances so the stored status reflects the wrapped difference.

**When to run:** After `setup_myqa_tests` creates new angular tests, or quarterly as a safety net. Critical for correctness — without wraparound, 0.1° vs 359.9° shows as 359.8° apart instead of 0.2°.

**Algorithm:** Matches Test names against curated regex patterns (`INCLUDE`: `angle (indicator|sensor|accuracy)|rotation accuracy|table angle|couch angle|gantry angle|collimator angle|gantry =|true zero`). Excludes non-angle measurements (`EXCLUDE`: `wedge|symmetry|flatness|output|constancy|...`). For each match, updates `type=wraparound`, `wrap_low=0`, `wrap_high=360`, then iterates TestInstances calling `ti.calculate_pass_fail()`.

**Flags:**
- `--apply` — actually convert (default is dry-run preview).

**Sample output:**
```
$ uv run python manage.py set_angular_wraparound --apply
Angular tests to convert: 12  |  TestInstances to re-evaluate: 348  |  TIs crossing 0/360 boundary: 17
Converted 12 Test(s) to wraparound [0, 360].
Re-evaluated pass_fail on 348 TestInstance(s).
```

**Idempotency:** Yes — already-`wraparound` tests are skipped (the `filter(type="simple")` in `select_angular_tests()` excludes them).

**BCHC note:** All historical angular tests converted in the original run. New ones from weekly setup auto-match the same patterns. Centre-specific: if your myQA uses condition names that don't match the curated patterns, edit `INCLUDE` / `EXCLUDE` in the command source.

---

## `auto_approve_tlis`

**Purpose:** Bulk auto-approve `TestListInstance`s where every TestInstance passes under the Default `AutoReviewRuleSet`. Marks the TLI as reviewed so it doesn't sit in the unreviewed queue.

**When to run:** After import, especially after changing the `AutoReviewRuleSet` configuration. The import itself calls `tli.auto_approve()` per-TLI, but this command catches any TLIs that were imported before the rule set was configured.

**Algorithm:** Iterates unreviewed TLIs, applies each Test's `AutoReviewRuleSet`, marks reviewed if all tests end up Approved.

**Sample output:**
```
$ uv run python manage.py auto_approve_tlis
Reviewed 234 of 567 unreviewed TLIs.
```

**Idempotency:** Yes — already-reviewed TLIs are skipped.

---

## `approve_myqa_taskids`

**Purpose:** Set all `*_taskid` TestInstances to `Approved` status. These are dedup metadata (storing the myQA `TaskExecutionId` for duplicate detection), not clinical data, so they should always be Approved.

**When to run:** After initial setup or any bulk import. The engine creates them with Approved status automatically (since the `myqa-state-aware-import` change), but this command backfills any that predate the fix.

**Algorithm:** Finds all TestInstances whose `unit_test_info.test.slug` ends in `_taskid`, updates `status=Approved`, `requires_review=False`.

**Sample output:**
```
$ uv run python manage.py approve_myqa_taskids
Approved 1234 *_taskid TestInstances (0 already approved).
```

**Idempotency:** Yes — already-Approved TIs are no-ops.

---

## `delete_empty_tlis`

**Purpose:** Delete TLIs that have real Tests but every TestInstance value is NULL. These were created by a bug that's since been fixed (the valueless-session guard now prevents new ones), but historical bad TLIs may linger.

**When to run:** Once after deploying the valueless-skip fix. Rare afterwards — the engine prevents new valueless TLIs from being created.

**Algorithm:** For each TLI, check if any TestInstance has a non-null `value` (or `string_value` for non-numeric types). If all are NULL, delete the TLI (cascades to its TIs) and recompute the parent UTC's `last_instance` pointer.

**Sample output:**
```
$ uv run python manage.py delete_empty_tlis
Deleting 17 empty TLIs (cascading 412 TestInstances)...
Recomputing last_instance on 12 UTCs.
```

**Idempotency:** Yes — re-running finds nothing (or only newly-broken TLIs, which the engine should prevent).

**⚠️ Destructive** — confirm with `--dry-run` first.

---

## `myqa_validate`

**Purpose:** Read-only diff of QATrack+ state against myQA source-of-truth. Surfaces silent drops, value mismatches, and tolerance drift. The system's main observation layer.

**When to run:** Monthly as routine hygiene, after every big import, or whenever you suspect data isn't flowing correctly.

**Algorithm:** For each (TaskName, unit) in scope over the given window:
- Queries myQA for sessions via `query_sessions`
- Dedupes by `task_execution_id` (myQA sometimes returns duplicate rows)
- For each unimported session, runs `extract_all_types` and classifies as `valueless_skip` (no values — OK) or `genuine_drop` (has values — investigate)
- For each imported session (has matching TLI), compares condition count, values (within 4-decimal rounding), and tolerances

**Flags:**
- `--days N` — lookback window (default 30).
- `--task-name NAME` — limit to one TaskName.
- `--unit N` — limit to one unit number.
- `--summary-only` — skip per-condition value/tolerance comparison for speed.
- `--json` — machine-readable output for CI.

**Sample output:**
```
$ uv run python manage.py myqa_validate --days 30
Validating last 30 days against myQA...
────────────────────────────────────────────────────────────────────────────────
  ✓ Daily Constancy Check                              (unit 437, RFT26 - H197686)
      Sessions in window: myQA  14  ↔  QATrack+  14  (imported total: 14)
  ⚠ 5.Tmt.Linac.Monthly - MLC                          (unit 3, LA317: 2972)
      Sessions in window: myQA   5  ↔  QATrack+   3  (imported total: 3)
      Unimported: 2 valueless-skip (OK), 0 genuine-drop (investigate)
────────────────────────────────────────────────────────────────────────────────
Summary: 47 pass, 1 needs review, 0 fail
```

**Idempotency:** Yes — read-only.

**BCHC note:** Run after every big import. The "needs review" status correctly fires when sessions are missing — investigate before relying on the data.
