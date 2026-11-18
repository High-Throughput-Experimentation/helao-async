# Output Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every server, analysis, processor and batch-script folder that writes or publishes data documents each output field (type, structure, unit, meaning, `file:line`) in its own `README.md` under `## Outputs`, guarded by a presence test, with the procedure saved as a re-runnable skill.

**Architecture:** One shared helper `helao/helpers/readme_outputs.py` finds "units" (`servers/<name>/`, `scripts/<name>/`, `processors/`) whose Python matches a writer pattern and reports those whose README lacks `## Outputs`. Each deployment gets a three-line guard test calling it. The README content is hand-written from code. The procedure lives as a user-level skill in the agent-KB vault.

**Tech Stack:** Python 3.14, pytest, Markdown. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-18-output-catalog-design.md`

## Global Constraints

- Docs and one guard test only. Never edit writer code. A defect found while documenting goes in that README's `## Notes` (append a bullet; do not rewrite existing bullets).
- Types come from code only. Never read production data, never ssh to note1, never touch `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i`. When code cannot settle a type, write `unknown (dynamic)` and the reason.
- Do not rewrite existing `## Params`, `## Vendor software`, `## Notes` sections. Insert `## Outputs` directly after `## Params` (or after the purpose paragraph when there is no `## Params`).
- Tracked parent-repo files never name a private deployment. This plan uses aliases; the legend is the memory file `cards-deployment-aliases.md` in `~/.claude/projects/-mnt-STORAGE-repos-helao-helao-async/memory/` (Deployment-A, B, C, E, F). Never copy the legend into a tracked file.
- Every git call uses `git -C <repo>`. Nested deployment repos are separate repos; commit there with their own git. Check `git -C <repo> branch --show-current` and `status --short` before each commit (all are on `main`, clean, at plan time).
- Subagents never run `git add`, `commit`, `push`, `stash`. The main session commits after each task's review passes. No push without user approval.
- `black` the new/changed `.py` files right before each commit (`/home/dan/miniforge3/envs/helao/bin/black <files>`).
- Python for tests: `/home/dan/miniforge3/envs/helao/bin/python` with `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async`, run from the parent repo root.

## Output section format (copy into every task)

````markdown
## Outputs

### `<action_or_entry_point>` (action | analysis | processor | script)

<One sentence: what triggers it, which files it writes, row granularity, writer `path:line`.>

Data file `<pattern>.jsonl` (+ `.meta.json`):

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `t_s` | float | scalar per row | s | time since technique start | `helao/deploy/hte/servers/gamry/driver.py:NNN` |

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `fom_ocv` | `action_params` | float | scalar | ... | `...:NNN` |
````

Rules:
- `type`: `int`, `float`, `str`, `bool`, `null`, `dict`, or a union (`float | null`). A `dict` row gets a nested table directly below the table.
- `structure`: `scalar`, `scalar per row`, `list[<type>]`, `array[<type>, <shape>]`, `dict`.
- Dynamic keys: write the pattern (`ch_<n>_V`) and a sentence naming the source of `<n>`.
- Non-tabular files (image, vendor raw, zip, `.prg`): one row each in a `| file | format | name pattern | meaning | written at |` table.
- Action results: keys an action writes into `action.action_params[...]` at run time (`in` = `action_params`) and any `action_output` keys (`in` = `action_output`). Params the caller passes and the action never rewrites are inputs, not results.
- Live data from a `DriverPoller.get_data` that is never written to a file: a `Live data (status/ws stream)` table with the same columns as the data-file table, `structure` = `scalar per poll`.
- Analyses: one table of the `outputs` model fields (the class assigned to `self.outputs`), one row per S3 artifact (`output_type`, `content_type`).
- Processors and batch scripts: also a short `Inputs parsed` list (format, name pattern, parser `path:line`).
- API writes (records, notes, rows posted to an HTTP API): a table `| endpoint | payload field | type | structure | meaning | sent at |`.
- An entry point that writes nothing: one line `No data files or action results.`
- Cite paths in full (`helao/deploy/<deployment>/...:<line>`), as the `## Params` tables do.
- New README for a folder without one: `# <folder>` heading, one purpose paragraph, then `## Outputs`.

## Per-unit procedure (every documentation task follows this)

1. List entry points in the unit: FastAPI action endpoints (`@app.post` / `make_*_endpoint` / `add_action`-style registrations in the server module), analysis classes, processor classes, script `main()`/CLI functions.
2. For each entry point, follow the data from source to sink: `enqueue_data*` dict keys, `json_data_keys`, `write_file*`, files written under `action_output_dir`, `to_parquet`/`write_to_dataset`/`write_table`, `json.dump`, `open(..., "w")`, `ZipFile`, `action_params[...] =`, `action_output[...]`, `DriverPoller.get_data` return dicts, API posts.
3. For each field, find the expression that produces its value and derive the type from it (literal, cast, numpy dtype, pydantic field type, driver return annotation). Cite that line.
4. Write the section in the format above.
5. Self-check: grep the unit for every writer pattern in the helper (Task 1 `WRITER`), and confirm each hit is covered by a row or by the "writes nothing" line.

## Review Focus

- Dynamic column names (per-channel, per-element, per-wavelength): expect a pattern row with its source, not a guessed literal list.
- Units documented under the server README but written by a shared module elsewhere (`helao/hexagon/...`, `scripts/common/`): expect the row to cite the shared writer and the unit's call site both.
- `action_params` keys that look like inputs but are rewritten at run time (e.g. `voltage` in `power_supply_server.py:511`): expect them listed as results.
- A unit the guard does not flag but that writes through an unrecognized idiom (API posts, delegated converters): expect it covered via the test's `extra` list.
- A README with a `## Outputs` heading but an empty section: the guard passes; the reviewer must reject it.

---

### Task 1: Guard helper and its unit tests (parent repo)

**Files:**
- Create: `helao/helpers/readme_outputs.py`
- Create: `helao/deploy/base/tests/test_readme_outputs.py`

**Interfaces:**
- Produces: `missing_outputs_sections(root: Path, extra: Iterable[str] = ()) -> list[str]` returning sorted POSIX unit paths relative to `root` (e.g. `"servers/gamry"`, `"processors"`) whose `README.md` is missing or has no `## Outputs` heading. `extra` adds unit paths that must be documented even when no writer pattern matches.
- Produces: `WRITER: re.Pattern[str]`, `unit_of(rel: Path) -> Path | None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Guard: every writer unit in the base deployment documents its outputs.

Also unit-tests the shared helper in helao/helpers/readme_outputs.py.
"""

from pathlib import Path

from helao.helpers.readme_outputs import missing_outputs_sections, unit_of


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_unit_of_groups_by_folder():
    assert unit_of(Path("servers/gamry/driver.py")) == Path("servers/gamry")
    assert unit_of(Path("servers/gamry/bokeh/vis.py")) == Path("servers/gamry")
    assert unit_of(Path("scripts/edax/converters.py")) == Path("scripts/edax")
    assert unit_of(Path("processors/libs/x.py")) == Path("processors")
    assert unit_of(Path("servers/__init__.py")) is None
    assert unit_of(Path("servers/gamry/tests/test_x.py")) is None
    assert unit_of(Path("experiments/x.py")) is None


def test_writer_without_readme_is_reported(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", "await active.enqueue_data_dflt(d)\n")
    assert missing_outputs_sections(tmp_path) == ["servers/a"]


def test_readme_without_outputs_heading_is_reported(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", "df.to_parquet(p)\n")
    _write(tmp_path, "servers/a/README.md", "# a\n\n## Params\n")
    assert missing_outputs_sections(tmp_path) == ["servers/a"]


def test_outputs_heading_satisfies(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", 'action.action_params["v"] = 1\n')
    _write(tmp_path, "servers/a/README.md", "# a\n\n## Outputs\n\nNo data files or action results.\n")
    assert missing_outputs_sections(tmp_path) == []


def test_non_writer_and_comparison_not_reported(tmp_path):
    _write(tmp_path, "servers/b/b_server.py", 'if action.action_params["v"] == 1:\n    pass\n')
    assert missing_outputs_sections(tmp_path) == []


def test_extra_units_required(tmp_path):
    _write(tmp_path, "scripts/notes/post.py", "client.post(url, json=n)\n")
    assert missing_outputs_sections(tmp_path, extra=["scripts/notes"]) == ["scripts/notes"]


def test_base_deployment_writer_units_documented():
    root = Path(__file__).resolve().parents[1]
    assert missing_outputs_sections(root) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/base/tests/test_readme_outputs.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'helao.helpers.readme_outputs'`.

- [ ] **Step 3: Write the helper**

```python
"""Find writer folders whose README lacks an ``## Outputs`` section.

A *unit* is ``servers/<name>/``, ``scripts/<name>/`` or ``processors/`` under a
deployment root. A unit whose Python matches :data:`WRITER` writes or publishes data,
so its ``README.md`` must catalog those outputs under ``## Outputs``. This is a
presence check only; review checks the content.
"""

import re
from collections.abc import Iterable
from pathlib import Path

# ponytail: static regex, misses writers that go through an unlisted helper;
# callers name those units in ``extra``.
WRITER = re.compile(
    r"enqueue_data|write_live_data|write_file(?:_nowait)?\(|json_data_keys"
    r"|action_output_dir|action_params\[[^\]]+\]\s*=(?!=)|action_output\["
    r"|\.to_parquet\(|write_to_dataset\(|write_table\(|\.to_csv\(|savefig\("
    r"|np\.save|AnalysisOutput\b|\boutputs\s*=|DriverPoller|json\.dump\("
    r"|\.write_text\(|\.write_bytes\(|open\([^)]*[\"']w|ZipFile\(|write_point_map\("
)
UNIT_DIRS = ("servers", "scripts", "processors")
SKIP_DIRS = {"tests", "__pycache__", ".pixi"}
OUTPUTS_HEADING = re.compile(r"^## Outputs\s*$", re.M)


def unit_of(rel: Path) -> Path | None:
    """Return the unit folder that owns ``rel`` (a path relative to a deployment)."""
    parts = rel.parts
    if not parts or parts[0] not in UNIT_DIRS or SKIP_DIRS & set(parts):
        return None
    if parts[0] == "processors":
        return Path("processors")
    return Path(*parts[:2]) if len(parts) > 2 else None


def missing_outputs_sections(root: Path, extra: Iterable[str] = ()) -> list[str]:
    """Return units under ``root`` that write data but document no outputs."""
    units = {Path(u) for u in extra}
    for py in root.rglob("*.py"):
        unit = unit_of(py.relative_to(root))
        if unit is None or unit in units:
            continue
        if WRITER.search(py.read_text(encoding="utf-8", errors="replace")):
            units.add(unit)
    missing = []
    for unit in sorted(units):
        readme = root / unit / "README.md"
        text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
        if not OUTPUTS_HEADING.search(text):
            missing.append(unit.as_posix())
    return missing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same command as Step 2.
Expected: `7 passed`. (`base` has no writer units at plan time, so the last test passes with an empty list.)

- [ ] **Step 5: Mutation check**

Two temporary edits, one at a time, each restored before the next:
1. Delete `(?!=)` from `WRITER`. Rerun: `test_non_writer_and_comparison_not_reported` must FAIL.
2. Replace `if not OUTPUTS_HEADING.search(text):` with `if True:`. Rerun: `test_outputs_heading_satisfies` must FAIL.

Restore both and rerun: `7 passed`.

- [ ] **Step 6: Commit (main session)**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/helpers/readme_outputs.py helao/deploy/base/tests/test_readme_outputs.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/helpers/readme_outputs.py helao/deploy/base/tests/test_readme_outputs.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "test: README ## Outputs presence guard helper"
```

---

### Task 2: `helao-output-catalog` skill in the agent-KB vault

**Files:**
- Create: `/home/dan/Sync/obsidian/agent-kb/projects/helao-async/skills/helao-output-catalog/SKILL.md`
- Create symlink: `/home/dan/.claude/skills/helao-output-catalog` -> the folder above

**Interfaces:**
- Consumes: `missing_outputs_sections` (Task 1), the format and per-unit procedure above.
- Produces: skill name `helao-output-catalog`, invoked when a writer changes or a guard test fails.

- [ ] **Step 1: Load `superpowers:writing-skills`** and follow its checklist for the file below.

- [ ] **Step 2: Write SKILL.md** with this content. The vault is private: when writing the file, replace each `Deployment-X` alias with the real folder name from the alias legend.

````markdown
---
name: helao-output-catalog
description: Use when a helao action, analysis, processor or batch script adds or changes an output (data file column, parquet field, action_params result key, action_output key, analysis output, API post), or when a test_readme_outputs.py guard fails. Updates the owning folder README's ## Outputs catalog.
---

# helao output catalog

Every unit that writes or publishes data documents each output field in its own
README under `## Outputs`. Units: `helao/deploy/<dep>/servers/<name>/`,
`helao/deploy/<dep>/scripts/<name>/`, `helao/deploy/<dep>/processors/`.
Design: `docs/superpowers/specs/2026-11-18-output-catalog-design.md` (parent repo).

## When

- A diff touches a writer: `enqueue_data*`, `json_data_keys`, `write_file*`, files
  under `action_output_dir`, `to_parquet`/`write_to_dataset`/`write_table`, `to_csv`,
  `json.dump`, `open(..., "w")`, `ZipFile`, run-time `action_params[...] =`,
  `action_output[...]`, a `DriverPoller.get_data` dict, an analysis `outputs` model,
  an API post.
- `test_readme_outputs.py` fails in any deployment.

## Steps

1. **Scope.** From the diff (or the guard failure list), name the affected units and
   entry points. Rewrite only those `###` sections.
2. **Repo.** Find the owning repo. Parent (public, `unstable`): `base`, `test`.
   Own repos (`main`): `hte` (public), and Deployment-A, B, C, E, F (private).
   Use `git -C <repo>` on every call. Check branch and `status --short` first;
   concurrent sessions switch nested clones.
3. **Trace.** For each entry point, follow data from source to sink and derive each
   field's type from the producing expression. Code only: never read production data,
   never touch `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i`. Unsettled type:
   `unknown (dynamic)` plus reason.
4. **Write** the section (format below), directly after `## Params`. Never rewrite
   `## Params`, `## Vendor software`, `## Notes`. Defects found: append a `## Notes`
   bullet; do not fix code in this skill.
5. **Self-check.** Grep the unit for every pattern in `helao/helpers/readme_outputs.py`
   `WRITER`; each hit maps to a row or to `No data files or action results.`
6. **Guard.** Run the deployment's guard:
   `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<dep>/tests/test_readme_outputs.py -q`.
   A unit that writes through an idiom the regex misses goes in that test's `EXTRA`.
7. **Review.** A separate `reviewer` agent checks rows against cited lines (type,
   structure, missed writers, empty sections). Not the author.
8. **Commit** in the owning repo after review, `black` on changed `.py` first. No push
   without user approval. Parent-repo tracked files never name a private deployment.

## Format

<paste the "Output section format" block and its Rules list from the plan verbatim>

## Traps

- Actions publish results mostly through `action.action_params[...] = ...` at run
  time, not `action_output` (in-tree code sets only `error_message` there,
  `helao/hexagon/app/action_host.py:1503`). Both feed `to_global_params`
  (`helao/hexagon/adapters/native/finalizer.py:280`).
- Analyses assign `self.outputs = <Model>(...)`; catalog that model's fields.
- Rows written by shared code (`helao/hexagon/...`, `scripts/common/`): cite the
  shared writer and the unit's call site.
- The guard checks presence only. An empty `## Outputs` passes it; reviewers reject it.
````

When writing the file, replace the `<paste ...>` line with the actual block from this plan's "Output section format" section (fenced example plus its Rules bullets). Do not leave the placeholder.

- [ ] **Step 3: Link it**

```bash
ln -s /home/dan/Sync/obsidian/agent-kb/projects/helao-async/skills/helao-output-catalog /home/dan/.claude/skills/helao-output-catalog
ls -l /home/dan/.claude/skills/helao-output-catalog/SKILL.md
```
Expected: the `ls` resolves to the vault file.

- [ ] **Step 4: Verify** the file has no secrets and no `<paste` text: `grep -n '<paste' /home/dan/Sync/obsidian/agent-kb/projects/helao-async/skills/helao-output-catalog/SKILL.md` prints nothing. The vault is synced, not git; there is no commit step.

---

### Task 3: Parent repo `test` deployment + parent CLAUDE.md

**Files:**
- Create: `helao/deploy/test/processors/README.md`
- Modify: `helao/deploy/test/servers/action/README.md`, `helao/deploy/test/servers/cpsim/README.md`, `helao/deploy/test/servers/gpsim/README.md` (create any that do not exist)
- Create: `helao/deploy/test/tests/test_readme_outputs.py`
- Modify: `CLAUDE.md` (parent root), section "Conventions worth knowing"

- [ ] **Step 1: Write the failing guard**

```python
"""Guard: every writer unit in the test deployment documents its outputs."""

from pathlib import Path

from helao.helpers.readme_outputs import missing_outputs_sections

EXTRA: list[str] = []


def test_writer_units_document_outputs():
    root = Path(__file__).resolve().parents[1]
    assert missing_outputs_sections(root, EXTRA) == []
```

- [ ] **Step 2: Run it**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/test/tests/test_readme_outputs.py -q`
Expected: FAIL listing `processors`, `servers/action`, `servers/cpsim`, `servers/gpsim`.

- [ ] **Step 3: Document each listed unit** with the per-unit procedure. `processors/` covers `sim_append_params.py` and `sim_hlo_to_csv.py`. Also check `servers/wssim` by hand: it publishes simulated ws data; if any of it is persisted or written into `action_params`, document it and add `"servers/wssim"` to `EXTRA`.

- [ ] **Step 4: Run guard** (Step 2 command). Expected: `1 passed`.

- [ ] **Step 5: Mutation check**: rename one `## Outputs` heading to `## Output`, rerun, expect FAIL naming that unit; restore, expect pass.

- [ ] **Step 6: Add the CLAUDE.md line** at the end of "Conventions worth knowing":

```markdown
- Output catalog: a folder under `helao/deploy/*/servers/`, `scripts/` or `processors/` that writes or publishes data documents every field in its `README.md` under `## Outputs` (type, structure, unit, meaning, `file:line`). Changing a written field means updating that table. `helao/helpers/readme_outputs.py` plus each deployment's `tests/test_readme_outputs.py` check the section exists.
```

- [ ] **Step 7: Review, then commit (main session)**: reviewer agent checks the READMEs against code; then

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/deploy/test/tests/test_readme_outputs.py
git -C /mnt/STORAGE/repos/helao/helao-async add CLAUDE.md helao/deploy/test
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "docs(test): output catalogs + README guard"
```
Before `add`, confirm `git -C ... status --short` shows only these paths (ignore untracked `.helao-env/`, `.pixi/`).

---

### Task 4: `hte` instrument servers (part 1)

Repo: `helao/deploy/hte` (public, `main`).

**Files:** Modify `README.md` in `helao/deploy/hte/servers/` `andor`, `biologic`, `cam`, `gamry`, `nidaqmx`, `spec`, `xafs`, `galil_io`, `galil_motion`.

- [ ] **Step 1: Baseline**: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "from pathlib import Path; from helao.helpers.readme_outputs import missing_outputs_sections as m; print(m(Path('helao/deploy/hte')))"` from the parent root. Expected: list containing the nine units above.
- [ ] **Step 2: Document each unit** with the per-unit procedure. `biologic` has three backends (`eclib`, `olecom`, `eclib2`; read `helao/deploy/hte/servers/biologic/CLAUDE.md` first); document fields per backend where they differ. `andor` has two `wl_source` variants (read `helao/deploy/hte/servers/andor/CLAUDE.md`). `gamry`: poller live data plus technique data files.
- [ ] **Step 3: Re-run Step 1.** Expected: none of the nine units listed.
- [ ] **Step 4: Review, then commit (main session)**:
```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte add servers
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte commit -m "docs: output catalogs for instrument servers (part 1)"
```

---

### Task 5: `hte` servers (part 2)

**Files:** Modify `README.md` in `helao/deploy/hte/servers/` `calc`, `co2sensor`, `diapump`, `htedata`, `kinesis`, `mfc`, `o2sensor`, `pal`, `power_supply`, `sample`, `syringe`, `tec`. Check `pdu` by hand (not flagged); document if it publishes results.

- [ ] **Step 1: Baseline** (Task 4 Step 1 command). Expected: these units listed.
- [ ] **Step 2: Document each unit.** `power_supply_server.py:511-512` rewrites `voltage` and `sleep_time` into `action_params`: these are results. `sample` writes archive/sample DB files: catalog the files and the sample fields written. `pal`: the run-time sample/`action_params` results it publishes for later actions.
- [ ] **Step 3: Re-run baseline.** Expected: none of these units listed.
- [ ] **Step 4: Review, then commit (main session)**: `git -C .../hte add servers`; `commit -m "docs: output catalogs for servers (part 2)"`.

---

### Task 6: `hte` analyses, processors, guard

**Files:**
- Modify: `helao/deploy/hte/servers/analysis/README.md` (analyses `uvis_bkgsubnorm`, `echeuvis_stability`)
- Create: `helao/deploy/hte/processors/README.md` (`hispec_process_all.py`, `hlo_to_csv.py`, `spec_melt_wls.py`, `append_params.py`, `libs/hispec_calibrate_downsample_parquet.py`)
- Create: `helao/deploy/hte/tests/test_readme_outputs.py`

- [ ] **Step 1: Write the guard** (same body as Task 3 Step 1, docstring says `hte`, `EXTRA: list[str] = []`).
- [ ] **Step 2: Run**: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`. Expected: FAIL listing `processors`, `servers/analysis`.
- [ ] **Step 3: Document.** Analyses: fields of `DryUvisOutputs` (`uvis_bkgsubnorm.py:215`) and `EcheUvisOutputs` (`echeuvis_stability.py:367`), plus each S3 artifact. Processors: `hispec_process_all.py` parquet dataset columns (melted wavelength layout), its `Inputs parsed`, and each other processor; note which config hook runs each.
- [ ] **Step 4: Run guard.** Expected: `1 passed`.
- [ ] **Step 5: Mutation check** as Task 3 Step 5.
- [ ] **Step 6: Review, then commit (main session)**:
```bash
/home/dan/miniforge3/envs/helao/bin/black helao/deploy/hte/tests/test_readme_outputs.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte add servers/analysis processors tests/test_readme_outputs.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte commit -m "docs: analysis + processor output catalogs, README guard"
```
`hte` has no `CLAUDE.md`; the parent CLAUDE.md line (Task 3) covers it.

---

### Task 7: Deployment-C servers (analysis, batch_convert)

Repo: `helao/deploy/<Deployment-C>` (private, `main`).

**Files:** Modify `servers/analysis/README.md` (analyses `icpms_local`, `uvis_local`, `xafs_local`, `xrfs_local`; read `servers/analysis/CLAUDE.md` first), `servers/batch_convert/README.md`.

- [ ] **Step 1: Baseline** with the Task 4 Step 1 command on that deployment root. Expected: includes `servers/analysis`.
- [ ] **Step 2: Document.** Each analysis: its `*Outputs` model fields (`IcpmsOutputs` `icpms_local.py:81`, `XafsOutputs` `xafs_local.py:125`, the uvis/xrfs equivalents) and S3 artifacts. `batch_convert` delegates to `scripts/*`: document each action's results, and for files it writes through a script, cite the script's README section rather than duplicating rows.
- [ ] **Step 3: Re-run baseline.** Expected: `servers/analysis` gone.
- [ ] **Step 4: Review, then commit (main session)** in the Deployment-C repo: `add servers/analysis/README.md servers/batch_convert/README.md`; `commit -m "docs: analysis and batch_convert output catalogs"`.

---

### Task 8: Deployment-C batch scripts (part 1: instrument converters)

**Files:** Create `README.md` in `scripts/` `bruker`, `bruker_gadds`, `edax`, `xafs`, `xrfs_calibration`, `xrfs_quantification` (read each folder's `CLAUDE.md` where present, and `scripts/CLAUDE.md`, `scripts/batch_conversion.md`).

- [ ] **Step 1: Baseline.** Expected: these units listed.
- [ ] **Step 2: Document each.** For each `batch_process.py`/CLI entry: inputs parsed; helao records produced (`-seq/-exp/-act/-prc.json`, `.meta.json` + `.jsonl` columns, parquet files, zips); analyses produced (`output` keys, S3 artifacts); API posts (plate notes, registry rows); local registries/libraries (`standards_registry`, `parquet_library`, calibration records) with their columns. One-off repair/backfill scripts (`fix_*`, `rebuild_*`, `reconvert_*`, `backfill_*`, `repair_*`): one row each naming what they rewrite, no full field tables unless they create a new output shape.
- [ ] **Step 3: Re-run baseline.** Expected: these units gone.
- [ ] **Step 4: Review, then commit (main session)**: `add scripts/{bruker,bruker_gadds,edax,xafs,xrfs_calibration,xrfs_quantification}/README.md`; `commit -m "docs: batch script output catalogs (instrument converters)"`.

---

### Task 9: Deployment-C batch scripts (part 2), guard, CLAUDE.md

**Files:**
- Create: `README.md` in `scripts/` `anneal`, `box_notes`, `common`, `ecms_ms`, `icpms`, `legacy_jcap`, `pl_map`, `vase`
- Modify: `scripts/wafer_photo/README.md`
- Create: `tests/test_readme_outputs.py` (that deployment's `tests/`)
- Modify: that deployment's `CLAUDE.md`

- [ ] **Step 1: Write the guard** (Task 3 Step 1 body) with `EXTRA = ["scripts/box_notes", "servers/batch_convert"]` (both publish through idioms the regex misses: API note posts, delegation).
- [ ] **Step 2: Run** the guard. Expected: FAIL listing the units above.
- [ ] **Step 3: Document each** (Task 8 Step 2 rules). `common`: only the writers it owns (`record.py`, `point_map_run.py`, `write_point_map`); callers cite it.
- [ ] **Step 4: Run guard.** Expected: `1 passed`. Mutation check as Task 3 Step 5.
- [ ] **Step 5: CLAUDE.md line** (append to its conventions/rules list; same text as Task 3 Step 6, with "this deployment" in place of `helao/deploy/*`).
- [ ] **Step 6: Review, then commit (main session)**: `black tests/test_readme_outputs.py`; `add scripts tests/test_readme_outputs.py CLAUDE.md` after checking `status --short` shows only README/test/CLAUDE.md changes; `commit -m "docs: batch script output catalogs, README guard"`.

---

### Task 10: Deployment-F

**Files:** Modify `README.md` in `servers/` `empower`, `hiden`, `railarm`; check `meca`, `portal`, `valves`, `zaber` by hand. Create `tests/test_readme_outputs.py`. Modify its `CLAUDE.md`.

- [ ] **Step 1: Guard** (Task 3 Step 1 body). Run: expect FAIL listing `servers/empower`, `servers/hiden`, `servers/railarm`.
- [ ] **Step 2: Document** each, plus any hand-checked unit that publishes results (add it to `EXTRA`). `empower` already describes some data in its README: move nothing, add the `## Outputs` tables and keep existing prose.
- [ ] **Step 3: Guard passes; mutation check; CLAUDE.md line** (as Task 9 Step 5).
- [ ] **Step 4: Review, then commit (main session)** in that repo: `commit -m "docs: output catalogs, README guard"`.

---

### Task 11: Deployment-B

**Files:** Modify `README.md` in `servers/` `actuator`, `robotarm`, `test_station`. Create `tests/test_readme_outputs.py`. Modify its `CLAUDE.md`. Ignore its `notes/` folder entirely (user ruling).

- [ ] **Steps:** as Task 10 (guard red listing the three units, document, guard green, mutation check, CLAUDE.md line, review, commit).

---

### Task 12: Deployment-A

**Files:** Modify `README.md` in `servers/` `advantech_io`, `motion`, `muxvalve`, `potentiostat`; create `processors/README.md` (`append_ref_vshe.py`). Check `io`, `stenner`, `ws_simulator` by hand. Create `tests/test_readme_outputs.py` with `EXTRA = ["processors"]`. Modify its `CLAUDE.md`.

- [ ] **Steps:** as Task 10. Guard red must list the four servers and `processors`.

---

### Task 13: Deployment-E

**Files:** Modify `README.md` in `servers/` `calc`, `oceandirect`; create `processors/README.md` (`hispec2_process_all.py`, `hispec_scale_reference.py`). Create `tests/test_readme_outputs.py` with `EXTRA = []` (the Task 1 regex includes `write_to_dataset(`, which flags `processors`). Modify its `CLAUDE.md`.

- [ ] **Steps:** as Task 10. Guard red must list `servers/calc`, `servers/oceandirect`, `processors`. `oceandirect_server.py` writes `spectra_emitted`, `stopped_executors`, `applied_<key>` into `action_params`: results.

---

### Task 14: Skill correction and final review

- [ ] **Step 1:** Collect every place in Tasks 3-13 where the skill's steps were wrong or missing (implementers report these). Edit the vault `SKILL.md` to fix them.
- [ ] **Step 2:** Run all eight guards:
```bash
cd /mnt/STORAGE/repos/helao/helao-async
for d in base test hte <C> <F> <B> <A> <E>; do PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/$d/tests/test_readme_outputs.py -q || echo "FAIL $d"; done
```
(Substitute real folder names from the alias legend when running.) Expected: no `FAIL` line.
- [ ] **Step 3:** Privacy check on the parent repo: `git -C /mnt/STORAGE/repos/helao/helao-async diff origin/unstable --name-only | xargs grep -nwE '<private names from legend>'` prints nothing.
- [ ] **Step 4:** Whole-branch reviewer pass over all repos' diffs (one `reviewer` agent): samples ≥3 rows per unit against code, rejects empty sections.
- [ ] **Step 5:** Write a memory file `output-catalog.md` (project type) with the finished state and commit hashes; add its index line. Ask the user before any push.
