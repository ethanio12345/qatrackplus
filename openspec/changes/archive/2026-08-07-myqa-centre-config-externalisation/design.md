# Design: myqa-centre-config-externalisation

## Context

Audit (read-only) confirmed the import engine core (`myqa_import.py`) is already portable: every SQL query is parameterised against the standard IBA myQA product schema, with zero BCHC literals embedded. The centre-specific surface area is concentrated in 6 places enumerated in `proposal.md`. This change externalises all of them to a single YAML config without changing BCHC's runtime behaviour.

## Goals

1. Every centre-specific value lives in YAML or robust lookups — no Python code change required to deploy to a new centre.
2. BCHC continues to work identically (default config = today's BCHC values).
3. Multi-site-per-deploy is the native schema shape (BCHC + CPMCC pattern, not an edge case).
4. The latent UnitType reconciliation bug is fixed for everyone.

## Non-goals

- New management commands (deferred to `myqa-centre-onboarding`).
- Validating centre config (deferred to `myqa_doctor` in onboarding change).
- Tolerance review tooling (out of scope for the portability programme).

## Design decisions

### D1: One config file, not many

The system already has two YAML files: `myqa_device_map.yaml` (device → unit number) and `myqa_name_overrides.yaml` (display name overrides). Adding a third (`myqa_centre_config.yaml`) for site/device-class/linac-types/frequency keeps each file's purpose crisp:

```
   qatrack/qa/management/commands/
   ├── myqa_device_map.yaml          ← device names → unit numbers (per-centre contents)
   ├── myqa_name_overrides.yaml      ← condition-name display overrides (per-centre)
   └── myqa_centre_config.yaml       ← NEW: sites, device classes, linac types, frequencies
```

Alternative considered: rolling all three into one mega-YAML. Rejected — the device map is large (129 lines today) and changes when myQA adds devices; the centre config is small (~50 lines) and changes when the centre reorganises. Different change cadences ⇒ different files.

### D2: Multi-site as the default schema shape

The schema models multi-site networks (BCHC + CPMCC, or a 5-hospital trust) as the natural case. A single-site centre is just `sites: [{slug: main, name: Main Site, device_prefixes: [""]}]`.

```yaml
network_name: "WSLHD Physics Network"   # human-readable, for logs/reports

sites:
  - slug: westmead          # maps to QATrack+ Site.slug
    name: Westmead
    device_prefixes: ["CPMCC", "WSLHD", "RFT"]
  - slug: blacktown
    name: Blacktown
    device_prefixes: ["BCHC"]

device_classes:                         # first matching pattern wins
  - pattern: '^(BCHC|CPMCC) \(Sec\.? Std.*\)'
    unit_type: "Ion Chamber"
    category: "Reference Chambers"
  - pattern: '^(BCHC|CPMCC) \(F\)'
    unit_type: "Ion Chamber"
    category: "Field Instruments"
  - pattern: 'Linac|TrueBeam|Synergy|Agility|Clinac|RFT|LA[0-9]|CST|OBK|DXR'
    unit_type: "Treatment LINAC"
    category: "Linacs"
  - pattern: '.*'                       # fallback
    unit_type: "Other"
    category: "Other"

linac_unit_type_names:                  # fixes audit issue #6
  - "Treatment LINAC"                   # what create_myqa_units emits
  - "TrueBeam"
  - "Synergy"
  - "Agility"
  - "Clinac"
  - "Edge"
  - "Halcyon"

frequency_inference:                    # optional override; defaults to current regexes
  daily: ['\\.d(?:[^a-z]|$)', 'daily']
  weekly: ['\\.w(?:[^a-z]|$)', 'weekly']
  monthly: ['\\.m(?:[^a-z]|$)', 'monthly']
  quarterly: ['\\.q(?:[^a-z]|$)', 'quarterly']
  annual: ['\\.y(?:[^a-z]|$)', 'annual']
  semi_annual: ['\\.6m(?:[^a-z]|$)', '6 monthly', '6-monthly', 'biannual']
  once_off: ['\\.c(?:[^a-z]|$)', 'commissioning']
```

### D3: Loader pattern mirrors `_load_device_map()`

A new `_load_centre_config()` helper in `myqa_import.py` follows the exact pattern of the existing `_load_device_map()` (lines 67-76): module-level cache, lazy read on first access, returns a dict. This keeps the import engine clean of `os.path` boilerplate and lets the test suite mock the loader.

If the YAML is missing, the loader returns a hardcoded `_BCHC_DEFAULT_CENTRE_CONFIG` dict whose values reproduce today's `create_myqa_units.py` constants exactly. A `DeprecationWarning` is emitted once per process pointing at the new file. This makes the refactor strictly backwards-compatible.

### D4: Robust category lookup (no more `category_id=1`)

The new `_default_category()` helper in `setup_myqa_tests.py` tries three strategies in order:

1. `Category.objects.get(slug="uncategorised")` — the QATrack+ default catch-all slug.
2. `Category.objects.order_by("id").first()` — first-created category (typically "Dosimetry" in default fixtures).
3. `Category.objects.get(pk=1)` — last-resort fallback preserving today's behaviour.

Each step is wrapped in try/except. This is robust against centres that have re-seeded, renamed, or reorganised their categories.

### D5: `get_internal_user()` everywhere

The existing `qatrack/qa/utils.py:188-203` helper does `User.objects.get_or_create(username="QATrack+ Internal", defaults={...})`. The two call sites that bypass it (`setup_myqa_tests.py:153`, `tasks.py:73`) are switched over. If the user doesn't exist, it's created. No more `DoesNotExist` crashes on first run.

### D6: UnitType reconciliation fix

`reports/qa_selection.py:18-32` is changed from:
```python
LINAC_UNIT_TYPE_NAMES = ("TrueBeam", "Synergy", "Agility", "Clinac", ...)
```
to:
```python
def get_linac_unit_type_names() -> tuple[str, ...]:
    return tuple(_load_centre_config().get("linac_unit_type_names", _DEFAULT_LINAC_TYPES))
```

The default value of `_DEFAULT_LINAC_TYPES` includes `"Treatment LINAC"` (what `create_myqa_units` emits). This fixes the latent bug where RFT26, LA317, etc. — created via `create_myqa_units` — were invisible to `clear_stale_due_dates --linacs-only` and the linac QA archive selection.

A unit test verifies RFT26 (unit 437, type `"Treatment LINAC"`) is now selected by `select_archive_utcs`.

### D7: `local_settings.example.py`

The committed dev `local_settings.py` contains live myQA credentials and a BCHC-specific `sys.path` entry. We add `local_settings.example.py` with redacted credentials:

```python
MYQA_DB_SERVER = "<your-myQA-server-host>"
MYQA_DB_NAME = "<your-myQA-database-name>"
MYQA_DB_USERNAME = "<read-only-myQA-user>"
MYQA_DB_PASSWORD = "<your-password>"

# Remove this if your centre doesn't share scripts via this path:
# PHYS_REPO_SCRIPTS_PATH = "/path/to/your/scripts"
```

The existing `local_settings.py` gets a header comment: `# BCHC dev environment — do NOT copy verbatim to another centre. See local_settings.example.py.` The file is already gitignored on production; this is a hygiene improvement for the dev repo only.

### D8: `infer_frequency` override path

The four module-level regex constants (`_FREQ_DAILY`, `_FREQ_WEEKLY`, `_FREQ_MONTHLY`, `_FREQ_QUARTERLY`, `_FREQ_ANNUAL`, `_FREQ_6MONTHLY`, `_FREQ_COMMISSIONING`) move into `infer_frequency()` itself, compiled lazily on first call from `centre_config["frequency_inference"]`. Default values are the current constants. A centre with non-IBA TaskName conventions (e.g. `"Monthly QA"` without the dotted path) can override without code edits.

This is a small change but it closes the last centre-coupling in the engine.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| BCHC's YAML default doesn't perfectly reproduce today's behaviour | Medium | Medium (some Unit miscategorisation) | Regression test: re-run `create_myqa_units --dry-run` against today's device map, diff output. |
| Centre's `Category` table lacks slug `"uncategorised"` AND PK 1 | Low | Low (uses `first()`) | `_default_category()` triple-fallback; tests cover all three branches. |
| Existing call sites of `LINAC_UNIT_TYPE_NAMES` (tuple constant) break | Medium | Medium | The new `get_linac_unit_type_names()` returns a tuple; existing call sites work unchanged. |
| `infer_frequency` perf regression from lazy regex compilation | Low | Low | Compiled regexes cached at module level after first call (memoize). |
| Centre deletes `myqa_centre_config.yaml` and silently gets BCHC defaults | Low | Low | `DeprecationWarning` logged on every import; `myqa_doctor` (next change) flags it. |

## Test strategy

- Unit tests for every new helper (`_load_centre_config`, `_default_category`, `get_linac_unit_type_names`).
- Regression test: `create_myqa_units --dry-run` output unchanged pre/post refactor for the existing BCHC device map.
- Regression test: `infer_frequency("5.Tmt.Linac.D")` still returns `"daily"`; override case verified too.
- Regression test: `select_archive_utcs` now includes RFT26 (unit 437, type "Treatment LINAC").
- CI: `uv run pytest -x -m "not selenium"` continues to pass (currently 403 tests in `qatrack/qa/tests/`).

## Open questions

None — all design decisions above are settled. Deferred questions (validation UX, deployment guide tone, etc.) belong to the follow-on changes.
