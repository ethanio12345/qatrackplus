# Design: myqa-centre-onboarding

## Context

After `myqa-centre-config-externalisation`, the engine has no centre-specific literals. But the centre onboarding story is still "read the source, write the YAML by hand, create Units via admin, hope you got it right." This change closes that gap with two commands: `bootstrap_myqa_centre` (do the work) and `myqa_doctor` (verify the preconditions).

## Goals

1. One command sequence takes a fresh fork from `git clone` to working import.
2. No Python or YAML knowledge required to onboard a new centre.
3. The centre's onboarding artefacts (device-map draft) are reviewable, shareable, version-controllable.
4. Precondition failures are caught loudly before they become silent runtime bugs.

## Non-goals

- Result validation (does the import produce correct data?) — deferred to `myqa_validate` in `myqa-centre-trust-and-ops`.
- Tolerance review tooling — explicitly out of scope (decision: document loudly).
- Multi-centre in one QATrack+ deploy — out of scope (deployment model is fork-and-config).

## Design decisions

### D1: Two-phase bootstrap, not interactive-per-device

Originally considered: pure interactive — prompt for each device, accept unit number, move to next. For ~70 devices this is exhausting, error-prone, and can't be resumed after interruption.

Settled design: two-phase with a reviewable draft.

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Phase 1: --scan                                            │
   │  ─────────────                                              │
   │  • Connect to myQA                                          │
   │  • SELECT DISTINCT RadiationDeviceName                      │
   │  • Filter DUMMY/test fixtures (configurable regex)          │
   │  • For each device:                                         │
   │    - Auto-suggest unit_number = max(existing) + offset      │
   │    - Auto-classify via centre_config["device_classes"]      │
   │    - Auto-route site via centre_config["sites"]             │
   │  • Write myqa_device_map.draft.yaml                         │
   │  • Print summary + path to draft                            │
   │                                                             │
   │  Phase 2: human review                                      │
   │  ───────────────────────                                    │
   │  • User opens draft in $EDITOR                              │
   │  • Adjusts unit numbers, removes unwanted devices           │
   │  • Saves                                                    │
   │                                                             │
   │  Phase 3: --apply                                           │
   │  ──────────────                                             │
   │  • Read draft                                               │
   │  • Validate (unit numbers unique, no conflicts w/ existing) │
   │  • Create Unit rows (idempotent on unit number)             │
   │  • Write production myqa_device_map.yaml atomically         │
   │    (temp file + os.rename — survives crashes mid-write)     │
   │  • Run setup_myqa_tests (unless --skip-setup)               │
   │  • Print next-steps + loud tolerance warning                │
   └─────────────────────────────────────────────────────────────┘
```

The draft file (`myqa_device_map.draft.yaml`) is the key artefact. It's:
- Reviewable in any editor.
- Shareable with colleagues for sign-off before commit.
- Version-controllable by the centre (under their own git, not ours).
- Re-runnable: `--scan` overwrites the draft; `--apply` is idempotent.

### D2: Auto-suggest heuristics

```
   For each candidate device:
   
   ┌─ Suggest unit_number ────────────────────────────────────┐
   │                                                          │
   │  1. If a Unit with this exact name already exists,       │
   │     reuse its number.                                    │
   │  2. Else if a Unit with similar name exists (Levenshtein │
   │     distance ≤ 3 against any existing Unit.name),        │
   │     suggest that number + warn "looks like a rename."    │
   │  3. Else suggest max(Unit.number) + 1.                   │
   │                                                          │
   └──────────────────────────────────────────────────────────┘
   
   ┌─ Suggest unit_type + category ──────────────────────────┐
   │                                                          │
   │  Iterate centre_config["device_classes"] in order.       │
   │  First matching `pattern` (Python re.search against the  │
   │  device name) provides unit_type + category.             │
   │  Fallback: ("Other", "Other").                           │
   │                                                          │
   └──────────────────────────────────────────────────────────┘
   
   ┌─ Suggest site ──────────────────────────────────────────┐
   │                                                          │
   │  Iterate centre_config["sites"] in order.                │
   │  First site whose `device_prefixes` matches             │
   │  (case-sensitive startswith against the device name)    │
   │  provides the site.                                      │
   │  Fallback: sites[0] (the first listed).                  │
   │                                                          │
   └──────────────────────────────────────────────────────────┘
```

### D3: Dummy-device filtering

The audit found 14 unmapped devices in BCHC's myQA: `DUMMY LINAC`, `zzDummy Linac`, `DUMMY MRI`, `zDUMMY LINAC`, etc. plus genuine but non-clinical entries (`DUMMY Machine for testing protocols`).

Default filter regex: `^(z*[Dd]ummy|test|tbd)\b`. Overridable via CLI flag `--dummy-regex '<pattern>'`. Can be disabled with `--no-filter-dummy` for centres whose real devices happen to match (unlikely but defensive).

Filter is applied during `--scan`. Filtered devices are summarised in the scan output (`"Filtered 14 test fixtures: DUMMY LINAC, DUMMY MRI, ..."`) so the centre can verify nothing real was excluded.

### D4: Atomic YAML write

`--apply` writes `myqa_device_map.yaml` atomically:
1. Write to `myqa_device_map.yaml.tmp`.
2. `os.fsync(tmp_fd)` (ensures durability).
3. `os.rename(tmp_path, final_path)` (atomic on POSIX).

A crash mid-write leaves the existing YAML untouched. This matters because the engine caches the device map at module level; a half-written file would cause silent data corruption until the next process restart.

### D5: Idempotent `--apply`

`--apply` can be safely re-run. Each run:
- Reads the (possibly-edited) draft.
- For each device entry:
  - If a Unit with that `number` exists, skip creation (log `"Unit 437 exists — skipping"`).
  - Else create with name/type/site from the draft.
- Updates `myqa_device_map.yaml` (atomic write — overwrites previous).
- Runs `setup_myqa_tests` (which is itself idempotent).

A centre can edit the draft and re-run `--apply` any number of times. Existing Units are never modified or deleted by `--apply`.

### D6: `myqa_doctor` — fail-fast vs warn

The 12 checks split into two severity levels:

| Severity | Behaviour | Checks |
|---|---|---|
| **FAIL** (exit 1) | Centre cannot proceed | 1 (settings), 2 (connection), 3 (device map exists), 5 (internal user), 6 (category), 7 (status "Approved"), 10 (default AutoReviewRuleSet), 12 (croniter) |
| **WARN** (exit 0, print warning) | Centre can proceed but should fix | 4 (centre config — fallback works), 8 (status "skipped" — auto-creatable), 9 (frequencies — auto-creatable), 11 (every device has a Unit — bootstrap can fix) |

Auto-creatable preconditions (8, 9) are auto-fixed on first `myqa_doctor` run unless `--no-autofix` is passed. This means a fresh `git clone` → `migrate` → `myqa_doctor` ends with all the soft preconditions fixed automatically and only hard failures (missing settings, no DB connection) require manual intervention.

### D7: `--non-interactive` alternative workflow

Some centres prefer pure manual editing. The `--non-interactive` flag for `bootstrap_myqa_centre --scan` writes a fully-commented skeleton:

```yaml
# myqa_device_map.draft.yaml — generated by bootstrap_myqa_centre --scan
# Uncomment and edit entries below, then run bootstrap_myqa_centre --apply.

# 438: CST15 - H192361                  # suggested: Linac, Westmead
# 439: OBK15 - H192362                  # suggested: Linac, Westmead
# ?: DUMMY LINAC                        # filtered as test fixture
# 440: LA317 - H192972                  # suggested: Linac, Westmead
...
```

Centres edit this directly, delete the `?` placeholders they don't want, fill in unit numbers, then `--apply`. No interactive prompts required. Useful for scripting / reproducible setups.

### D8: Post-migrate auto-register the weekly setup schedule

`qatrack/qa/apps.py:do_scheduling` currently registers two schedules (`QATrack+ Autosave Cleaner`, `myQA Full Import`) on `post_migrate`. Add a third: `myQA Weekly Setup` (cron `0 2 * * 0`, the same Schedule that `setup_myqa_setup_schedule` creates). The standalone command remains for explicit re-registration or cron-time changes; the auto-registration just ensures a fresh DB deploy gets the schedule without manual command invocation.

Idempotent via the existing `_schedule_periodic_task` helper which uses `Schedule.objects.get(name=...)` + update-or-create.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Auto-suggested unit numbers conflict with manually-managed existing units | Medium | Medium (Unit.number UNIQUE constraint) | `--apply` validates uniqueness before creating; conflicts abort with a clear error message listing the conflicting numbers. |
| Auto-classification (`device_classes`) mis-routes a real device to "Other" | Medium | Low (cosmetic — admin-editable later) | `setup_myqa_tests` reports classification misses to stderr (modified in this change); centre can adjust `centre_config["device_classes"]` and re-run `--scan`. |
| `--apply` partially succeeds then crashes (e.g. mid-setup) | Low | Low (idempotent operations) | All operations are idempotent: re-running `--apply` skips already-created Units and `setup_myqa_tests` is `get_or_create` everywhere. |
| `myqa_doctor` false-positive on connection check (transient myQA outage) | Low | Low (re-run) | Connection check has 5-second timeout; failure message says "is myQA online?" |
| `myqa_doctor` auto-creates statuses the centre didn't want | Low | Low (auto-creatable items use sensible defaults from existing helpers) | `--no-autofix` flag lets centre preview before applying. |
| Auto-registering the weekly schedule surprises an existing centre that deliberately removed it | Low | Low (idempotent update_or_create preserves next_run if Schedule exists) | Schedule name is unique; if a centre deleted it intentionally, they need to filter `do_scheduling` (rare). |

## Test strategy

- Unit tests with mocked myQA connection for both commands.
- Integration test for `bootstrap_myqa_centre` end-to-end: `--scan` writes draft, manually edit draft, `--apply` creates Units + writes production YAML + runs setup. Verify against a test fixture with 5 fake devices.
- Idempotency test: run `--apply` twice on same draft, verify second run is a no-op.
- `myqa_doctor` parametrised test: one scenario per check (pass + fail).
- CI: `uv run pytest -x -m "not selenium"` continues to pass.

## Open questions

None — design is settled. The "what does a centre do with the validation report" question is explicitly deferred to `myqa-centre-trust-and-ops` (the centre decides; we provide data).
