# hte member-surface audit (Base/Active/app driver-facing members)

Grep-derived inventory of the driver-facing `Base`/`Active`/`app` member
surface each hexagon hte adapter must reproduce (spec §8.2). This is the
surface whose omission caused the old attempt's per-station crash class —
every member listed below for a given module is a hard dependency a
hexagon replacement must satisfy.

**Reproducibility note:** `conda run -n helao <script> <<'PY' ... PY` (stdin
heredoc) silently swallowed all stdout in this environment — `conda run`
does not propagate stdout when the child reads from a piped heredoc. The
plan's script is unmodified in substance; it was run from a temp `.py` file
(`conda run -n helao python3 /tmp/p3pre_member_surface.py`) instead of via
stdin heredoc to get real output. Anyone re-running this audit should invoke
the script as a file, not via `python - <<'PY'`.

## Method

```bash
conda run -n helao python3 /tmp/p3pre_member_surface.py
```

Script (verbatim logic from the plan, patterns unchanged):

```python
import re
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
```

## Raw output (action servers — `helao/deploy/hte/servers/action/*.py`)

```
helao/deploy/hte/servers/action/HTEdata_server.py: ['action', 'app.base', 'app.driver', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/andor_server.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/biologic_server.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/calc_server.py: ['action', 'app.base', 'app.driver', 'finish', 'helaodirs', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/cam_server.py: ['action', 'app.base', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/co2sensor_server.py: ['action', 'app.base', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/sync_server.py: ['app.driver']
helao/deploy/hte/servers/action/diapump_server.py: ['action', 'app.base', 'app.driver', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/galil_io.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/galil_motion.py: ['action', 'app.base', 'app.driver', 'app.server_params', 'dyn_endpoints', 'finish', 'get_main_error', 'setup_and_contain_action(', 'world_cfg']
helao/deploy/hte/servers/action/gamry_server2.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/kinesis_server.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/mfc_server.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/nidaqmx_server.py: ['action', 'app.base', 'app.driver', 'app.server_params', 'dyn_endpoints', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/o2sensor_server.py: ['action', 'app.base', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/pal_server.py: ['action', 'actionservermodel', 'app.base', 'app.driver', 'app.server_params', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/pdu_server.py: ['action', 'app.base', 'app.driver', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/power_supply_server.py: ['action', 'app.base', 'app.driver', 'dyn_endpoints', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/sample_server.py: ['action', 'app.base', 'app.driver', 'app.server_params', 'append_sample', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/spec_server.py: ['action', 'app.base', 'app.driver', 'append_sample', 'dyn_endpoints', 'finish', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/syringe_server.py: ['action', 'app.base', 'app.driver', 'finish', 'poller_class', 'setup_and_contain_action(']
helao/deploy/hte/servers/action/tec_server.py: ['action', 'app.base', 'app.driver', 'finish', 'poller_class', 'setup_and_contain_action(']
```

`analysis_server.py` and the `helao/deploy/hte/experiments/*.py` /
`helao/deploy/hte/sequences/*.py` libraries produced **no hits** — confirmed
by direct inspection, not a script defect (see "Per-server / per-library
notes" below).

## Per-server / per-library notes

| Module | Members consumed |
|---|---|
| `HTEdata_server.py` | `app.base`, `app.driver`, action-lifecycle (`setup_and_contain_action`, `.action`/`.finish` on the returned `active`) |
| `analysis_server.py` | **none matched** — endpoints are generated at `makeApp` time from `core.drivers.data.analysis_driver.make_analysis_app` against `params.analyses`; it does not touch `app.driver`/`app.base`/`active.*` directly in this module (the generated function bodies live in the core driver, out of this grep's scope) |
| `andor_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, action-lifecycle |
| `biologic_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, action-lifecycle |
| `calc_server.py` | `app.base`, `app.driver`, `base.helaodirs`, action-lifecycle |
| `cam_server.py` | `app.base`, action-lifecycle (no `app.driver` hit — driver accessed some other way / not through this pattern set) |
| `co2sensor_server.py` | `app.base`, `poller_class`, action-lifecycle |
| `sync_server.py` | `app.driver` only (deprecated/dead per prior memory — minimal surface, do not migrate) |
| `diapump_server.py` | `app.base`, `app.driver`, `poller_class`, action-lifecycle |
| `galil_io.py` | `app.base`, `app.driver`, `dyn_endpoints`, `poller_class`, action-lifecycle |
| `galil_motion.py` | `app.base`, `app.driver`, `app.server_params`, `dyn_endpoints`, `get_main_error`, `base.world_cfg`, action-lifecycle |
| `gamry_server2.py` | `app.base`, `app.driver`, `dyn_endpoints`, `poller_class`, action-lifecycle |
| `kinesis_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, `poller_class`, action-lifecycle |
| `mfc_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, `poller_class`, action-lifecycle |
| `nidaqmx_server.py` | `app.base`, `app.driver`, `app.server_params`, `dyn_endpoints`, `poller_class`, action-lifecycle |
| `o2sensor_server.py` | `app.base`, `poller_class`, action-lifecycle (no `app.driver` hit) |
| `pal_server.py` | `app.base`, `app.driver`, `app.server_params`, `base.actionservermodel`, action-lifecycle |
| `pdu_server.py` | `app.base`, `app.driver`, action-lifecycle |
| `power_supply_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, action-lifecycle (no explicit `finish` hit) |
| `sample_server.py` | `app.base`, `app.driver`, `app.server_params`, `active.append_sample`, action-lifecycle |
| `spec_server.py` | `app.base`, `app.driver`, `dyn_endpoints`, `active.append_sample`, action-lifecycle |
| `syringe_server.py` | `app.base`, `app.driver`, `poller_class`, action-lifecycle |
| `tec_server.py` | `app.base`, `app.driver`, `poller_class`, action-lifecycle |
| `helao/deploy/hte/experiments/*.py` (13 modules) | **none matched** — experiment functions build `Experiment`/`ActionPlanMaker`-style dispatch objects and do not access `app`/`active`/`base` members directly; their dependent surface is the imported `helao.*` API (see Task 4 inventory), not this pattern set |
| `helao/deploy/hte/sequences/*.py` (14 modules) | **none matched** — same reasoning as experiments; sequence functions compose experiments, no direct member access |

## Gap flag for hexagon adapters (§8.2 crash class)

The action-server column above is the minimum per-server member surface a
hexagon adapter must reproduce. Notably:
- `app.driver` and `app.base` are near-universal (21/23 and 22/23 action
  modules respectively) — any hexagon `app` shim missing either attribute
  breaks nearly every hte action server.
- `dyn_endpoints` and `poller_class` are used by roughly half the servers
  (the hardware-polling ones) — hexagon adapters for those servers must
  wire dynamic-endpoint generation and pollers identically.
- `app.server_params` appears on `galil_motion.py`, `nidaqmx_server.py`,
  `pal_server.py`, `sample_server.py` — config mutation at runtime
  (`allow_concurrent_actions` etc.) must be preserved per-server, not
  centralized/removed.
