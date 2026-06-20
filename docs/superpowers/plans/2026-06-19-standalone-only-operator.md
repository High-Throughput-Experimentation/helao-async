# Standalone-Only BokehOperator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the standalone Bokeh operator the only `BokehOperator` implementation by stripping the integrated operator + `LocalBackend` from the orchestrator and launching the operator as a `group: operator` server in every in-scope config.

**Architecture:** The operator becomes an ordinary `group: operator` Bokeh server (`bokeh: standalone_operator`) launched by `bokeh_launcher.py`, using `BokehOperator(vis, RemoteBackend(...))` over HTTP + the orchestrator's status WebSocket. The orchestrator imports no Bokeh and no operator code. The `OrchBackend` ABC stays as the contract `RemoteBackend` implements.

**Tech Stack:** Python 3.12, FastAPI, Bokeh 3.9, pydantic v2, YAML configs.

**Spec:** `docs/superpowers/specs/2026-06-19-standalone-only-operator-design.md`

---

## File Structure

- Modify `helao/core/servers/orch.py` — remove all integrated-operator/Bokeh code.
- Modify `helao/core/servers/operator/orch_backend.py` — delete `_OpShim` + `LocalBackend`; keep `OrchBackend` ABC + `RemoteBackend`.
- Modify `helao/core/tests/test_standalone_operator.py` — delete the four `LocalBackend`/`_OpShim` test cases + their `run_all()` calls.
- Modify `helao/helpers/config_loader.py` — mark `enable_op` deprecated/ignored in `OrchServerParams`.
- Modify configs (hte + test tracked; priv + lila + mea in nested repos) — drop `enable_op`/`bokeh_port`, add an `OPERATOR` server entry on the reclaimed port.

### Reclaimed operator port table

| Deployment | Configs | Operator port |
|---|---|---|
| hte | adss, adss3, anec, ccsi1, ccsi2, clad, eche4, eche5, eche6, eche7, eche8, eche10, ecms1, ecms2, hispec, partialccsi1, power_supply_test, uvis, xrfs1 | 5002 |
| mea | amts | 5002 |
| priv | icpm1, note1, xrfs_priv1 | 5002 |
| priv | test_alert, uvis4 | 5001 |
| lila | electrode-demo, simulation | 5001 |
| test | test, demo0, ws_demo | 5001 |
| test | demo1 | 5011 |

All in-scope orchestrator servers use key `ORCH`. The operator's `host` mirrors that config's `ORCH` host.

---

## Task 1: Strip integrated-operator code from orch.py

**Files:**
- Modify: `helao/core/servers/orch.py`

- [ ] **Step 1: Establish the test baseline (green before changes)**

Run: `PYTHONPATH=$PWD conda run -n helao python helao/core/tests/test_standalone_operator.py`
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 2: Remove the Bokeh + operator imports**

In `helao/core/servers/orch.py` delete these import lines:

```python
from bokeh.server.server import Server          # line 35
from helao.core.servers.operator.bokeh_operator import BokehOperator   # line 44
from helao.core.servers.vis import HelaoVis      # line 45
```

If `from functools import partial` exists and `partial` is now unused (it was used only at the old line 292), remove that import too. Verify with `grep -n "partial(" helao/core/servers/orch.py` — if no hits remain, remove the import.

- [ ] **Step 3: Remove the `bokehapp` class annotation**

Delete line ~95:

```python
    bokehapp: Server
```

- [ ] **Step 4: Remove the operator attribute initializers**

Delete these three lines from `__init__` (around 153-155):

```python
        self.bokehapp = None
        self.orch_op = None
        self.op_enabled = self.server_params.get("enable_op", False)
```

- [ ] **Step 5: Remove the `start_operator` launch branch in `myinit`**

Replace (around 229-231):

```python
        if self.op_enabled:
            self.start_operator()
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
```

with:

```python
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
```

- [ ] **Step 6: Delete the `start_operator` and `makeBokehApp` methods**

Delete the entire block from `def start_operator(self):` (line ~278) through the `return doc` that ends `makeBokehApp` (line ~325). That removes both methods.

- [ ] **Step 7: Delete the `update_operator` method**

Delete (around 2296-2299):

```python
    async def update_operator(self, msg):
        # ...docstring/body...
        if self.op_enabled and self.orch_op:
            await self.orch_op.update_q.put(msg)
```

- [ ] **Step 8: Remove every `update_operator` call site**

Delete these lines (each is a standalone statement; remove the whole line):
- `await self.update_operator(True)` at lines ~622, ~1238, ~1498, ~1519, ~1577, ~1616, ~2357, ~2414
- `self.update_operator(True)` at line ~2498 (note: no `await`)

The commented-out reference at line ~1190 is inside a comment block — leave it or delete the comment line; either is fine.

- [ ] **Step 9: Confirm no operator/Bokeh references remain**

Run: `grep -nE "bokeh|BokehOperator|LocalBackend|update_operator|start_operator|makeBokehApp|orch_op|op_enabled|HelaoVis" helao/core/servers/orch.py`
Expected: no matches (or only matches inside comments you chose to keep). If a match appears outside a comment, fix it.

- [ ] **Step 10: Verify orch.py imports cleanly**

Run: `PYTHONPATH=$PWD conda run -n helao python -c "import helao.core.servers.orch"`
Expected: no output, exit 0 (no ImportError/NameError).

- [ ] **Step 11: Run the operator + orch test suite**

Run: `PYTHONPATH=$PWD conda run -n helao python helao/core/tests/test_standalone_operator.py`
Expected: `ALL STANDALONE_OPERATOR TESTS PASS` (LocalBackend tests still pass — they construct a mock orch and don't touch orch.py).

- [ ] **Step 12: Commit**

```bash
git add helao/core/servers/orch.py
git commit -m "refactor(orch): remove integrated Bokeh operator and update_operator"
```

---

## Task 2: Delete LocalBackend + _OpShim and their tests

**Files:**
- Modify: `helao/core/servers/operator/orch_backend.py`
- Modify: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Delete `_OpShim` and `LocalBackend`**

In `helao/core/servers/operator/orch_backend.py` delete the entire block from `class _OpShim:` (line ~121) through the end of `LocalBackend.close` (the `self.orch.orch_op = None` line ~257), i.e. everything between the module-level `_STEP_ATTRS` dict and `class RemoteBackend(OrchBackend):` (line ~260). Keep one blank-line separation before `class RemoteBackend`.

Do NOT remove `_SEQ_KEYS`, `_EXP_KEYS`, `_STEP_ATTRS` — `RemoteBackend` uses them.

- [ ] **Step 2: Update the module docstring**

The module docstring (lines 1-10) describes two backends. Edit the second sentence so it no longer claims a `LocalBackend`:

```python
"""Orchestrator-access backend for the Bokeh operator UI.

The :class:`BokehOperator` UI talks only to an :class:`OrchBackend`.
:class:`RemoteBackend` drives a remote orchestrator over OrchAPI HTTP/RPC
endpoints and the Base status WebSocket.

List/state methods return *normalized plain dicts* so the UI never has to
branch on object-vs-JSON. See the method docstrings for the contract.
"""
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `PYTHONPATH=$PWD conda run -n helao python -c "from helao.core.servers.operator.orch_backend import OrchBackend, RemoteBackend; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Delete the four LocalBackend test functions**

In `helao/core/tests/test_standalone_operator.py` delete these whole functions (from `def` to their `print(... PASS)` line, inclusive):
- `test_local_backend_normalized_shapes` (lines ~106-151)
- `test_local_backend_prepend` (lines ~475-490)
- `test_local_backend_move_remove` (lines ~745-764)
- `test_local_backend_get_queue_object` (lines ~977-996)

- [ ] **Step 5: Remove their calls from `run_all()`**

In `run_all()` (line ~1145) delete the four call lines:

```python
    test_local_backend_normalized_shapes()
    test_local_backend_prepend()
    test_local_backend_move_remove()
    test_local_backend_get_queue_object()
```

- [ ] **Step 6: Confirm no stray references to the deleted symbols**

Run: `grep -nE "LocalBackend|_OpShim" helao/core/tests/test_standalone_operator.py helao/core/servers/operator/orch_backend.py`
Expected: no matches.

Run repo-wide: `grep -rnE "LocalBackend|_OpShim" helao/ --include=*.py`
Expected: no matches.

- [ ] **Step 7: Run the test suite**

Run: `PYTHONPATH=$PWD conda run -n helao python helao/core/tests/test_standalone_operator.py`
Expected: `ALL STANDALONE_OPERATOR TESTS PASS` (now without the four removed cases).

- [ ] **Step 8: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/core/tests/test_standalone_operator.py
git commit -m "refactor(operator): delete LocalBackend and _OpShim; drop their tests"
```

---

## Task 3: Mark enable_op deprecated in config_loader

**Files:**
- Modify: `helao/helpers/config_loader.py:150-164`

`OrchServerParams` is a pydantic v2 `BaseModel` with no `extra="forbid"`, so unknown keys (`bokeh_port`, leftover `enable_op` in untouched configs) are ignored at validation. Keep the `enable_op` field for documentation and back-compat, but mark it deprecated.

- [ ] **Step 1: Update the docstring + field comment**

Replace the `enable_op` docstring line and field with:

```python
    """Per-orchestrator ``params:`` block from a config YAML.

    Attributes:
        enable_op: DEPRECATED and ignored. The operator now runs as a separate
            ``group: operator`` server; the orchestrator no longer hosts it.
        heartbeat_interval: Seconds between status pings sent to action servers.
        ignore_heartbeats: Server keys whose missed heartbeats should not
            trigger error handling.
        verify_plates: Whether plate barcode verification is required.
    """

    enable_op: Optional[bool] = None  # deprecated, ignored
    heartbeat_interval: Optional[float] = 10.0
    ignore_heartbeats: Optional[List[str]] = None
    verify_plates: Optional[bool] = True
```

- [ ] **Step 2: Verify config_loader imports cleanly**

Run: `PYTHONPATH=$PWD conda run -n helao python -c "import helao.helpers.config_loader; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add helao/helpers/config_loader.py
git commit -m "chore(config): mark OrchServerParams.enable_op deprecated/ignored"
```

---

## Task 4: Migrate tracked configs (test deployment)

**Files:**
- Modify: `helao/deploy/test/configs/test.yml`
- Modify: `helao/deploy/test/configs/demo0.yml`
- Modify: `helao/deploy/test/configs/demo1.yml`
- Modify: `helao/deploy/test/configs/ws_demo.yml`

- [ ] **Step 1: Edit `test.yml` — strip ORCH op params**

Change the `ORCH` `params:` block from:

```yaml
    params:
      enable_op: true
      bokeh_port: 5001
      launch_browser: true
    exp_postprocess_libs:
```

to:

```yaml
    params:
    exp_postprocess_libs:
```

(If `params:` would become empty with no sibling keys, set it to `params: {}`. Here `exp_postprocess_libs`/`seq_postprocess_libs` are siblings of `params`, so leave `params:` followed by its remaining keys — there are none under `params` now, so write `params: {}`.)

Resulting ORCH block:

```yaml
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    params: {}
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
```

- [ ] **Step 2: Edit `test.yml` — rename STANDALONE_OP → OPERATOR, port 5004 → 5001**

Replace:

```yaml
  STANDALONE_OP:
    group: operator
    bokeh: standalone_operator
    host: 127.0.0.1
    port: 5004
    params:
      orch_key: ORCH
      doc_name: "Standalone Operator (test)"
      poll_interval: 5
```

with:

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: 127.0.0.1
    port: 5001
    params:
      orch_key: ORCH
      doc_name: "Operator (test)"
      poll_interval: 5
```

- [ ] **Step 3: Edit `demo0.yml` and `ws_demo.yml`**

In each, remove `enable_op: true` and `bokeh_port: 5001` from the `ORCH` `params:` (leave `params: {}` if empty), and add a sibling server entry (operator port 5001, host = that config's ORCH host):

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: <ORCH host from this file>
    port: 5001
    params:
      orch_key: ORCH
      poll_interval: 5
```

- [ ] **Step 4: Edit `demo1.yml`**

Same as Step 3 but the removed `bokeh_port` is `5011`, so the operator entry uses `port: 5011`:

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: <ORCH host from demo1.yml>
    port: 5011
    params:
      orch_key: ORCH
      poll_interval: 5
```

- [ ] **Step 5: Validate each config loads**

Run:

```bash
PYTHONPATH=$PWD conda run -n helao python -c "
from helao.helpers.config_loader import read_config
for p in ['test','demo0','demo1','ws_demo']:
    c = read_config(p)
    srv = c['servers']
    assert 'OPERATOR' in srv, (p, 'no OPERATOR')
    assert srv['OPERATOR']['bokeh'] == 'standalone_operator', p
    assert 'enable_op' not in (srv['ORCH'].get('params') or {}), (p,'enable_op left')
    print(p, 'OPERATOR port', srv['OPERATOR']['port'])
"
```

Expected: prints `test OPERATOR port 5001`, `demo0 OPERATOR port 5001`, `demo1 OPERATOR port 5011`, `ws_demo OPERATOR port 5001`, no assertion error.

- [ ] **Step 6: Check no host:port collisions in these configs**

Run:

```bash
PYTHONPATH=$PWD conda run -n helao python -c "
from helao.helpers.config_loader import read_config
for p in ['test','demo0','demo1','ws_demo']:
    srv = read_config(p)['servers']
    seen = {}
    for k,v in srv.items():
        if 'host' in v and 'port' in v:
            hp = (v['host'], v['port'])
            assert hp not in seen, (p, hp, k, seen[hp])
            seen[hp] = k
    print(p, 'no collisions')
"
```

Expected: `no collisions` for all four.

- [ ] **Step 7: Commit**

```bash
git add helao/deploy/test/configs/test.yml helao/deploy/test/configs/demo0.yml helao/deploy/test/configs/demo1.yml helao/deploy/test/configs/ws_demo.yml
git commit -m "feat(test-configs): launch standalone OPERATOR server, drop integrated op"
```

---

## Task 5: Migrate tracked configs (hte deployment)

**Files (all under `helao/deploy/hte/configs/`):** adss.yml, adss3.yml, anec.yml, ccsi1.yml, ccsi2.yml, clad.yml, eche4.yml, eche5.yml, eche6.yml, eche7.yml, eche8.yml, eche10.yml, ecms1.yml, ecms2.yml, hispec.yml, icpm1.yml, partialccsi1.yml, power_supply_test.yml, uvis.yml, xrfs1.yml

Each has an `ORCH` `params:` block containing `enable_op: true` and `bokeh_port: 5002`. The operator port is **5002** for every hte config.

- [ ] **Step 1: For each file, remove the two op params**

Delete the `enable_op: true` and `bokeh_port: 5002` lines from the `ORCH` `params:` block. If `params:` has other sibling keys (e.g. `heartbeat_interval`, `ignore_heartbeats`, `verify_plates`), keep them. If removing the two lines empties `params:`, set it to `params: {}`.

Example (`anec.yml`) — change:

```yaml
    params:
      enable_op: true
      bokeh_port: 5002
```

to:

```yaml
    params: {}
```

- [ ] **Step 2: For each file, add the OPERATOR server entry**

Insert as a sibling of `ORCH` (same indentation level, two spaces), using that file's `ORCH` host:

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: <ORCH host from this file>
    port: 5002
    params:
      orch_key: ORCH
      poll_interval: 5
```

Note: in these configs the integrated operator used 5002, and port 5001 is the `VIS` server — do not use 5001. The `bokeh_port: 5003` lines elsewhere belong to other servers (e.g. aligner/secondary vis); leave them untouched.

- [ ] **Step 3: Validate all hte configs load and have no collisions**

Run:

```bash
PYTHONPATH=$PWD conda run -n helao python -c "
from helao.helpers.config_loader import read_config
names = ['adss','adss3','anec','ccsi1','ccsi2','clad','eche4','eche5','eche6','eche7','eche8','eche10','ecms1','ecms2','hispec','icpm1','partialccsi1','power_supply_test','uvis','xrfs1']
for p in names:
    srv = read_config(p)['servers']
    assert srv['OPERATOR']['port'] == 5002, (p, srv['OPERATOR']['port'])
    assert srv['OPERATOR']['bokeh'] == 'standalone_operator', p
    assert 'enable_op' not in (srv['ORCH'].get('params') or {}), (p,'enable_op left')
    seen = {}
    for k,v in srv.items():
        if 'host' in v and 'port' in v:
            hp=(v['host'],v['port']); assert hp not in seen,(p,hp,k,seen[hp]); seen[hp]=k
    print(p, 'ok')
"
```

Expected: `ok` for each of the 20 configs (note `read_config` resolves bare prefixes across deployments; if a prefix collides with another deployment, pass the full path instead).

- [ ] **Step 4: Commit**

```bash
git add helao/deploy/hte/configs/*.yml
git commit -m "feat(hte-configs): launch standalone OPERATOR server on 5002, drop integrated op"
```

---

## Task 6: Whole-tree verification (tracked repo)

**Files:** none (verification only)

- [ ] **Step 1: Operator/orch test suite**

Run: `PYTHONPATH=$PWD conda run -n helao python helao/core/tests/test_standalone_operator.py`
Expected: `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 2: Data browser test suite (unrelated but confirms no collateral breakage)**

Run: `PYTHONPATH=$PWD conda run -n helao python helao/deploy/test/tests/test_data_browser.py`
Expected: `ALL DATA_BROWSER TESTS PASS`.

- [ ] **Step 3: Project unit tests**

Run: `PYTHONPATH=$PWD conda run -n helao python run_unit_tests.py >/dev/null 2>&1; echo "exit=$?"`
Expected: `exit=0`.

- [ ] **Step 4: Repo-wide grep for removed symbols**

Run: `grep -rnE "LocalBackend|_OpShim|update_operator|start_operator|makeBokehApp" helao/core --include=*.py`
Expected: no matches in `helao/core/servers/orch.py` or `orch_backend.py`. (`makeBokehApp` still legitimately appears in the standalone operator module and the data browser app — those are NOT under `helao/core/servers/orch*`.)

- [ ] **Step 5: Smoke launch the test group (manual)**

Run: `./helao.sh test`
Expected: group launches; the `OPERATOR` server starts and serves Bokeh on `http://127.0.0.1:5001`; opening it shows the operator UI connected to `ORCH` (queue tables populate, Start/Stop reachable). Terminate with `CTRL-x`.

---

## Task 7: Migrate nested-repo configs (priv, lila, mea)

These deployments are **separate git repositories** nested in-tree and invisible to the parent repo's `git status`. Each requires `cd` into the deployment dir and a commit on its own remote/branch.

**Files:**
- `helao/deploy/priv/configs/icpm1.yml`, `note1.yml`, `xrfs_priv1.yml` (operator port **5002**)
- `helao/deploy/priv/configs/test_alert.yml`, `uvis4.yml` (operator port **5001**)
- `helao/deploy/lila/configs/electrode-demo.py`, `simulation.py` (operator port **5001**)
- `helao/deploy/mea/configs/amts.yml` (operator port **5002**)

- [ ] **Step 1: Edit the priv `.yml` configs**

For each priv yaml, remove `enable_op` + `bokeh_port` from `ORCH` `params:` (leave `params: {}` if empty) and add the operator entry. For `icpm1.yml`, `note1.yml`, `xrfs_priv1.yml` use `port: 5002`; for `test_alert.yml`, `uvis4.yml` use `port: 5001`:

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: <ORCH host from this file>
    port: <5002 for icpm1/note1/xrfs_priv1, 5001 for test_alert/uvis4>
    params:
      orch_key: ORCH
      poll_interval: 5
```

- [ ] **Step 2: Edit `mea/configs/amts.yml`**

Remove `enable_op: true` + `bokeh_port: 5002` from `ORCH` `params:`; add:

```yaml
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: <ORCH host from amts.yml>
    port: 5002
    params:
      orch_key: ORCH
      poll_interval: 5
```

- [ ] **Step 3: Edit the lila `.py` configs (dict format, port 5001)**

In `lila/configs/simulation.py` and `lila/configs/electrode-demo.py`, change the `ORCH` entry's `"params"` to drop `enable_op`/`bokeh_port`:

```python
    "ORCH": {
        "host": HOSTIP,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {},
    },
```

and add an `OPERATOR` entry to the same servers dict:

```python
    "OPERATOR": {
        "host": HOSTIP,
        "port": 5001,
        "group": "operator",
        "bokeh": "standalone_operator",
        "params": {"orch_key": "ORCH", "poll_interval": 5},
    },
```

(`electrode-demo.py`'s VIS is on 5004, so 5001 is free; confirm.)

- [ ] **Step 4: Validate each nested config loads (full path, no collisions)**

Run:

```bash
PYTHONPATH=$PWD conda run -n helao python -c "
from helao.helpers.config_loader import read_config
import glob
paths = (glob.glob('helao/deploy/priv/configs/*.yml')
         + ['helao/deploy/mea/configs/amts.yml']
         + glob.glob('helao/deploy/lila/configs/*.py'))
targets = {'icpm1','note1','xrfs_priv1','test_alert','uvis4','amts','simulation','electrode-demo'}
for path in paths:
    name = path.split('/')[-1].rsplit('.',1)[0]
    if name not in targets: continue
    srv = read_config(path)['servers']
    assert 'OPERATOR' in srv, (name,'no OPERATOR')
    assert 'enable_op' not in (srv['ORCH'].get('params') or {}), (name,'enable_op left')
    seen={}
    for k,v in srv.items():
        if 'host' in v and 'port' in v:
            hp=(v['host'],v['port']); assert hp not in seen,(name,hp,k,seen[hp]); seen[hp]=k
    print(name,'OPERATOR port',srv['OPERATOR']['port'])
"
```

Expected: prints each name with port 5002 (icpm1/note1/xrfs_priv1/amts) or 5001 (test_alert/uvis4/simulation/electrode-demo); no assertion error.

- [ ] **Step 5: Commit each nested repo separately**

```bash
cd helao/deploy/priv && git add configs/*.yml && git commit -m "feat(configs): launch standalone OPERATOR server, drop integrated op" && cd -
cd helao/deploy/lila && git add configs/simulation.py configs/electrode-demo.py && git commit -m "feat(configs): launch standalone OPERATOR server, drop integrated op" && cd -
cd helao/deploy/mea && git add configs/amts.yml && git commit -m "feat(configs): launch standalone OPERATOR server, drop integrated op" && cd -
```

Push each nested repo per its own workflow (ask the user before pushing nested repos).

---

## Notes / out of scope

- `lila_gl` is excluded; its configs keep `enable_op`/`bokeh_port` (now ignored fields).
- `helao/core/servers/operator/helao_operator.py` is untouched.
- No change to `BokehOperator` UI behavior.
