# P3-pre — Dependent-Surface Inventory + Endpoint Checklist (hte) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the committed, reproducible gate-input artifacts that must exist **before** the P3 hte wave begins — frozen per-server endpoint checklists, the BaseAPI system-surface checklist, the member-surface audit, the dependent-surface inventory, and a loud flat-namespace collision check — so the wave never hits the old attempt's mid-flight "Wave 3.5 emergency" (spec §8.3(3), AVOID #8).

**Architecture:** Pure Linux tooling + audit artifacts. Reuse the P0 AST route extractor (`harness/endpoints.py`) — do NOT reimplement it. Freeze extractions as JSON under a committed checklist tree; add a reproducibility test (regenerate == frozen) and a collision-detection test. The grep-derived inventories are generated markdown artifacts. **No production code under `helao/deploy/hte/**` or `helao/hexagon/**` is modified** — this sub-project only reads legacy source and writes test/checklist/audit files.

**Tech Stack:** Python 3.12 (`conda run -n helao`), `ast` via `harness.endpoints`, pytest under `harness/tests/`, `black` line-length 88.

## Global Constraints

- **conda run -n helao** for every python/pytest invocation (OS python is 3.14 — wrong).
- **black** (line length 88) on changed `.py` files immediately before every commit.
- **Reuse `harness/endpoints.py`** (`extract_routes`, `diff_route_sets`, CLI `python -m harness.endpoints`) — do not rebuild the extractor.
- **Read-only over legacy** — never edit `helao/deploy/hte/**` or `helao/hexagon/**` in this sub-project.
- **Nested deployment repos are private** — this sub-project touches only the public parent repo (`helao/deploy/hte/` is tracked/public). Do not name any private deployment.
- Branch: `feat/p3-pre-hte-inventory` off `unstable`. Do not push without authorization.
- Frozen extractions are checked in (they are the gate baseline); the reproducibility test guards against legacy drift.

## Legacy inputs (frozen maps — read-only references)

- 23 action-server modules: `helao/deploy/hte/servers/action/*.py` (list + server_keys in the P3 decomposition doc §1).
- 13 exp modules `helao/deploy/hte/experiments/*.py`; 14 seq modules `helao/deploy/hte/sequences/*.py`. (NOTE: exp/seq libraries live at the deployment root, NOT under `servers/` — verified on `unstable`.)
- Known collision hazards: `CSIL_exp.py` reuses `CCSI_sub_*` names from `CCSI_exp.py`; `ECHEUVIS_postseq` defined in both `ECHEUVIS_seq.py` and `HISPEC_seq.py`.
- BaseAPI system surface (§8.2): `/get_config`, `/get_status`, `/attach_client`, `/stop_executor`, `/{key}/estop`, `/shutdown`, `/get_lbuf`, `/list_executors`, `/loaded_modules`, WS `ws_status`/`ws_data`/`ws_live`.

---

### Task 1: Freeze per-server endpoint checklists for all 23 hte action servers

**Files:**
- Create: `helao/hexagon/tests/checklists/hte/<server_module>.json` (23 files, e.g. `gamry_server2.json`)
- Create: `helao/hexagon/tests/checklists/hte/servers.json` (manifest: module→server_key(s))
- Create: `harness/hte_freeze.py` (driver: iterate the manifest, call `extract_routes`, write JSON)

**Interfaces:**
- Consumes: `harness.endpoints.extract_routes(module_path: Path, server_key: Optional[str]) -> List[dict]`
- Produces: `harness/hte_freeze.py` exposes `SERVERS: list[tuple[str, str | None]]` (module filename, representative server_key) and `freeze_all(out_dir: Path) -> list[Path]`.

- [ ] **Step 1: Write the manifest** `servers.json` mapping each of the 23 modules to its server_key(s) from the P3 decomposition doc §1 (multi-key servers list all keys; representative key = first). Modules with no tracked server_key (`HTEdata_server`, `o2sensor_server`, `pdu_server`, `tec_server`) record `null` representative + a note.

- [ ] **Step 2: Write `harness/hte_freeze.py`**

```python
"""Freeze hte legacy endpoint checklists (spec §8.3, P3-pre).

Runs the P0 AST extractor over each hte action-server module and writes the
frozen route set as the endpoint-parity baseline for the P3 wave.
"""
from __future__ import annotations
import json
from pathlib import Path
from harness.endpoints import extract_routes

HTE_ACTION = Path("helao/deploy/hte/servers/action")
OUT = Path("helao/hexagon/tests/checklists/hte")

# (module filename, representative server_key for {server_key} substitution)
SERVERS: list[tuple[str, str | None]] = [
    ("HTEdata_server.py", None),
    ("analysis_server.py", "ANA"),
    ("andor_server.py", "ANDOR"),
    ("biologic_server.py", "BIOLOGIC"),
    ("calc_server.py", "CALC"),
    ("cam_server.py", "CAM"),
    ("co2sensor_server.py", "CO2SENSOR"),
    ("sync_server.py", "DB"),
    ("diapump_server.py", "DOSEPUMP"),
    ("galil_io.py", "IO"),
    ("galil_motion.py", "MOTOR"),
    ("gamry_server2.py", "PSTAT"),
    ("kinesis_server.py", "KMOTOR"),
    ("mfc_server.py", "MFC"),
    ("nidaqmx_server.py", "NI"),
    ("o2sensor_server.py", None),
    ("pal_server.py", "PAL"),
    ("pdu_server.py", None),
    ("power_supply_server.py", "POWER_SUPPLY"),
    ("sample_server.py", "SAMPLE"),
    ("spec_server.py", "SPEC_T"),
    ("syringe_server.py", "WORKSYRINGE"),
    ("tec_server.py", None),
]


def freeze_all(out_dir: Path = OUT) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for module, key in SERVERS:
        routes = extract_routes(HTE_ACTION / module, server_key=key)
        dst = out_dir / (Path(module).stem + ".json")
        dst.write_text(json.dumps(routes, indent=2) + "\n")
        written.append(dst)
    return written


if __name__ == "__main__":
    for p in freeze_all():
        print(p)
```

- [ ] **Step 3: Run the freeze**

Run: `conda run -n helao python -m harness.hte_freeze`
Expected: prints 23 paths; `helao/hexagon/tests/checklists/hte/*.json` created. Spot-check `gamry_server2.json` contains ~16 PSTAT routes and `sample_server.json` ~35 SAMPLE routes (matches §8.1 counts). Note static-only limit: BaseAPI system routes + config-shaped dyn endpoints are NOT in these files by design (runtime /openapi.json cross-check is P3b/P3e).

- [ ] **Step 4: Commit** (see final black step in Task 5's commit pattern; commit this task independently)

```bash
conda run -n helao black harness/hte_freeze.py
git add harness/hte_freeze.py helao/hexagon/tests/checklists/hte/
git commit -m "feat(hexagon): P3-pre freeze hte endpoint checklists (23 servers, §8.3)"
```

---

### Task 2: Reproducibility test — frozen extraction == regenerated

**Files:**
- Create: `harness/tests/test_hte_checklist.py`

**Interfaces:**
- Consumes: `harness.hte_freeze.SERVERS`, `harness.endpoints.extract_routes`, `harness.endpoints.diff_route_sets`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
import pytest
from harness.hte_freeze import SERVERS, HTE_ACTION, OUT
from harness.endpoints import extract_routes, diff_route_sets


@pytest.mark.parametrize("module,key", SERVERS)
def test_frozen_matches_regenerated(module, key):
    frozen_path = OUT / (Path(module).stem + ".json")
    frozen = json.loads(frozen_path.read_text())
    current = extract_routes(HTE_ACTION / module, server_key=key)
    assert diff_route_sets(frozen, current) == []
```

- [ ] **Step 2: Run to verify it passes** (frozen was just generated by the same extractor)

Run: `conda run -n helao python -m pytest harness/tests/test_hte_checklist.py -q`
Expected: 23 passed. (This test's value is *future* drift detection — if legacy hte source changes, the frozen baseline must be consciously re-frozen.)

- [ ] **Step 3: Sanity — force a mismatch** temporarily edit one frozen JSON (add a bogus route), rerun, confirm 1 failure with a `missing`/`extra` diff, then revert the JSON. This proves the test actually gates.

- [ ] **Step 4: Commit**

```bash
conda run -n helao black harness/tests/test_hte_checklist.py
git add harness/tests/test_hte_checklist.py
git commit -m "test(hexagon): P3-pre hte checklist reproducibility gate"
```

---

### Task 3: BaseAPI system-surface checklist + member-surface audit

**Files:**
- Create: `helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md` (the §8.2 shared surface every hexagon hte server must provide)
- Create: `helao/hexagon/tests/checklists/hte/_member_surface.md` (grep-derived Base/Active/app member usage per server)

- [ ] **Step 1: Write the BaseAPI system-surface checklist** — enumerate verbatim from §8.2: routes `/get_config`, `/get_status`, `/attach_client`, `/stop_executor`, `/{key}/estop`, `/shutdown`, `/get_lbuf`, `/list_executors`, `/loaded_modules`; WS `ws_status`/`ws_data`/`ws_live`; the action-lifecycle POST contract; queuing middleware; estop exception handler (HTTP exception on action route → estop + stop-executors); co-located RPC mirror. One sign-off checkbox per item (these are the routes the static extractor cannot see — they're runtime-registered by BaseAPI).

- [ ] **Step 2: Generate the member-surface audit.** For each of the 23 action modules AND the exp/seq libraries, grep the driver-facing Base/Active member surface the old attempt's crashes came from. Run and record results:

```bash
conda run -n helao python - <<'PY'
import re, subprocess
from pathlib import Path
PATTERNS = [
    r"app\.server_params", r"app\.base\b", r"app\.driver\b",
    r"\bdyn_endpoints\b", r"\bpoller_class\b",
    r"setup_and_contain_action\(", r"\bget_main_error\b",
    r"active\.(split|enqueue_data|append_sample|write_file_nowait|set_estop|"
    r"finish|contain|action)\b",
    r"base\.(helaodirs|world_cfg|server_cfg|actionservermodel|dflt|aloop|"
    r"put_lbuf|fast_urls)\b",
]
roots = [Path("helao/deploy/hte/servers/action"),
         Path("helao/deploy/hte/experiments"),
         Path("helao/deploy/hte/sequences")]
for root in roots:
    for f in sorted(root.glob("*.py")):
        hits = []
        text = f.read_text()
        for pat in PATTERNS:
            for m in set(re.findall(pat, text)):
                hits.append(m if isinstance(m, str) else "".join(m))
        if hits:
            print(f"{f}: {sorted(set(hits))}")
PY
```

Paste the output into `_member_surface.md` grouped by server, with a one-line-per-server note of which members each server/library consumes (this is the surface each hexagon hte adapter MUST reproduce; gaps here = the §8.2 per-station crash class).

- [ ] **Step 3: Commit**

```bash
git add helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md helao/hexagon/tests/checklists/hte/_member_surface.md
git commit -m "docs(hexagon): P3-pre hte BaseAPI system-surface + member-surface audit (§8.2)"
```

---

### Task 4: Dependent-surface inventory (§8.3(3))

**Files:**
- Create: `helao/hexagon/tests/checklists/hte/_dependent_surface.md`

- [ ] **Step 1: Generate the four-part inventory.** Run and record:

```bash
conda run -n helao python - <<'PY'
import re
from pathlib import Path

# (a) exp/seq library imports (what the libraries import from helao.*)
for root in ["experiments", "sequences"]:
    p = Path("helao/deploy/hte") / root
    for f in sorted(p.glob("*.py")):
        imps = re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", f.read_text(), re.M)
        helao = sorted({i for i in imps if i.startswith("helao")})
        print(f"[{root}] {f.name}: {helao}")

# (c) config references to shared/action modules + (d) bokeh_port claims
cfgs = Path("helao/deploy/hte/configs")
for f in sorted(cfgs.glob("*.yml")):
    t = f.read_text()
    fasts = sorted(set(re.findall(r"fast:\s*(\S+)", t)))
    bokehs = sorted(set(re.findall(r"bokeh:\s*(\S+)", t)))
    bports = re.findall(r"bokeh_port:\s*(\d+)", t)
    print(f"{f.name}: fast={fasts} bokeh={bokehs} bokeh_port={bports}")
PY
```

Record in `_dependent_surface.md`: (a) library→helao import map, (b) note the `active.*`/`base.*` member usage cross-referenced from Task 3, (c) per-config server module set, (d) `bokeh_port` claims (the "invisible port" hazard). Add the explicit AVOID#8 line: **experiments/sequences libraries are in the P3c wave plan from day one** (their omission forced the old Wave 3.5 emergency).

- [ ] **Step 2: Commit**

```bash
git add helao/hexagon/tests/checklists/hte/_dependent_surface.md
git commit -m "docs(hexagon): P3-pre hte dependent-surface inventory (§8.3(3))"
```

---

### Task 5: Flat-namespace collision check (loud, tested)

**Files:**
- Create: `harness/hte_collisions.py`
- Create: `harness/tests/test_hte_collisions.py`

**Interfaces:**
- Produces: `harness.hte_collisions.scan_collisions(lib_dir: Path) -> dict[str, list[str]]` — maps a duplicated top-level function name → the list of module files (len ≥ 2) defining it.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from harness.hte_collisions import scan_collisions

EXP = Path("helao/deploy/hte/experiments")
SEQ = Path("helao/deploy/hte/sequences")


def test_known_seq_collision_detected():
    cols = scan_collisions(SEQ)
    # ECHEUVIS_postseq defined in both ECHEUVIS_seq.py and HISPEC_seq.py
    assert "ECHEUVIS_postseq" in cols
    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])


def test_known_exp_collision_detected():
    cols = scan_collisions(EXP)
    # CSIL_exp.py forks CCSI_sub_* names from CCSI_exp.py
    ccsi_dupes = {n: m for n, m in cols.items() if n.startswith("CCSI_sub_")}
    assert ccsi_dupes, "expected CCSI_sub_* forks across CCSI_exp.py/CSIL_exp.py"
    for mods in ccsi_dupes.values():
        assert {"CCSI_exp.py", "CSIL_exp.py"} <= set(mods)
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest harness/tests/test_hte_collisions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.hte_collisions'`.

- [ ] **Step 3: Write `harness/hte_collisions.py`**

```python
"""Flat-namespace collision scanner for hte exp/seq libraries (spec §4.3.12).

The Library port registers experiment/sequence functions in a flat name-keyed
dict; two modules defining the same top-level function name silently shadow
under one config's *_libraries list. This surfaces those collisions loudly so
the P3c load-time collision check has a frozen expected set.
"""
from __future__ import annotations
import ast
from collections import defaultdict
from pathlib import Path


def _top_level_funcs(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text())
    return [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def scan_collisions(lib_dir: Path) -> dict[str, list[str]]:
    name_to_modules: dict[str, list[str]] = defaultdict(list)
    for f in sorted(Path(lib_dir).glob("*.py")):
        if f.name == "__init__.py":
            continue
        for fn in _top_level_funcs(f):
            name_to_modules[fn].append(f.name)
    return {n: m for n, m in name_to_modules.items() if len(m) >= 2}
```

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest harness/tests/test_hte_collisions.py -q`
Expected: 2 passed.

- [ ] **Step 5: Emit the frozen collision set** into the inventory so P3c has a baseline:

Run: `conda run -n helao python -c "from harness.hte_collisions import scan_collisions; from pathlib import Path; import json; print(json.dumps({'exp': scan_collisions(Path('helao/deploy/hte/experiments')), 'seq': scan_collisions(Path('helao/deploy/hte/sequences'))}, indent=2))" | tee helao/hexagon/tests/checklists/hte/_collisions.json`
Expected (verified on `unstable`): ~30 exp collisions (28 `CCSI_sub_*` + `CCSI_debug_co2purge` + `CCSI_leaktest_co2`, all across `CCSI_exp.py`/`CSIL_exp.py`) and 1 seq collision (`ECHEUVIS_postseq` across `ECHEUVIS_seq.py`/`HISPEC_seq.py`). Any collision beyond these is a new hazard — note it at the top of `_dependent_surface.md`.

- [ ] **Step 6: Commit**

```bash
conda run -n helao black harness/hte_collisions.py harness/tests/test_hte_collisions.py
git add harness/hte_collisions.py harness/tests/test_hte_collisions.py helao/hexagon/tests/checklists/hte/_collisions.json
git commit -m "feat(hexagon): P3-pre hte flat-namespace collision scan (§4.3.12)"
```

---

## Self-Review

**Spec coverage (§8.3):**
- §8.3(1) generated-not-written frozen extraction → Task 1 (reuses `harness/endpoints.py`) + Task 2 (reproducibility). ✔
- §8.3(1) BaseAPI system-surface + member surface (§8.2) → Task 3. ✔
- §8.3(2) runtime /openapi.json cross-check → explicitly deferred to P3b/P3e (needs a launched hexagon server; not Linux-freezable here). Noted in Task 1 Step 3 + Task 3 Step 1.
- §8.3(3) dependent-surface inventory (a/b/c/d) → Task 4. ✔
- §8.3(4) flat-namespace collision check → Task 5. ✔

**Placeholder scan:** no TBD/TODO; every code step has full code; grep audits produce concrete recorded output.

**Type consistency:** `SERVERS`, `HTE_ACTION`, `OUT` defined in Task 1's `harness/hte_freeze.py` and consumed unchanged in Task 2. `scan_collisions(lib_dir) -> dict[str, list[str]]` defined Task 5 Step 3, consumed Task 5 Step 1 + Step 5.

**Deferred-by-design (not gaps):** runtime openapi diff (needs launch), and everything hardware — this sub-project is Linux-complete audit tooling only.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-18-P3-pre-dependent-surface-inventory.md`. Recommended: **Subagent-Driven** (superpowers:subagent-driven-development) — fresh subagent per task, review between tasks. Five small tasks, all Linux-complete.
