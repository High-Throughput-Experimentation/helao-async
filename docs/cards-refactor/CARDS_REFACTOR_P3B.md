# CARDS Refactor — P3 sub-increment 3b: Typed config injection (Alignment + Domain Integrity)

> Derived from `CARDS_AUDIT.md` Part 1 Alignment findings ("`CONFIG` mutable singleton seeded at
> import, no injection boundary (acknowledged TODO base.py:119)"; "World config = untyped dict,
> deep-navigated (`world_cfg["servers"][key]["host"]` base.py:148)"; "`load_global_config(...,
> set_global=False)` — flag flips a pure read into a global mutation (config_loader.py:129)";
> "`config_loader.py:150-192` — `HelaoConfig`/`ServerConfig` pydantic models (exist but under-used)")
> and `CARDS_REFACTOR_P3.md` §3b sketch + §2.5 harness design. Line numbers in the audit have drifted
> slightly after 3a: on current `feat/cards-refactor` HEAD the TODO is base.py:121 and the deep nav is
> base.py:150-151. Branch: `feat/cards-refactor`, parent repo only (no nested-repo changes in 3b).
>
> **Risk class: MEDIUM.** 3b changes `Base.__init__` — the constructor path of every FastAPI server —
> and the launcher config-install path of every process. It is **not statically byte-provable**;
> correctness is integration-level. Therefore 3b-T0 builds the end-to-end sim harness (spec'd in P3
> §2.5, never built in 3a) and every task gates against it. Hard constraints: YAML config shape
> unchanged; every server in every tracked deployment (hte + test) still constructs; hte validated on
> Linux `test` sims + `py_compile` only, no live hardware. Python via `conda run -n helao`.

---

## 1. Decisions (made, not asked)

### D1 — 3b ships as ONE sub-increment; no 3b-i/3b-ii split
The mandated scope — (1) loader split, (2) injection seam, (3) typed access in base.py — is smaller
than it looks once the code is inspected. Step (3) in base.py is exactly two blocks (orchestrator
topology at base.py:143-155 and `run_type` at base.py:165-171); everything else `world_cfg` does in
base.py is shallow `.get()` or whole-dict pass-through, which stays on the dict shim by design.
Splitting steps (2) and (3) into separate increments would run the expensive e2e harness twice for
two halves of the same file and the same seam. The serial chokepoint (one task owns
`config_loader.py`; one owns `base.py`+`server_api.py`) is unavoidable either way, so splitting buys
no parallelism. **The wider typed-access campaign (orch.py's ~12 `world_cfg` nav sites, vis.py,
base_api.py, a typed `helao_dirs` overload) is explicitly deferred** and sketched in §8 as "3b-ii"
follow-up work — it is not needed to land the seam.

### D2 — Config-validation audit runs as an independent parallel task (3b-TA), and it does not block anything: the P3 §4 open question is ANSWERED
Verified live on this branch, 2026-07-10:

```
conda run -n helao python -c "
import glob
from helao.helpers.config_loader import read_config, HelaoConfig
paths = sorted(glob.glob('helao/deploy/hte/configs/*.yml') + glob.glob('helao/deploy/test/configs/*.yml'))
fails = []
for p in paths:
    try: HelaoConfig(**read_config(p))
    except Exception as e: fails.append((p, e))
print(len(paths), 'checked,', len(fails), 'failures')"
# -> 25 checked, 0 failures   (21 hte + 4 test)
```

**All 25 tracked configs pass `HelaoConfig` validation today.** There is nothing to fix-or-waive;
3b-TA codifies this as a permanent regression test in the suite. Additionally, "make validation
unconditional" turns out to already be the runtime status quo: both launchers call
`load_global_config(confArg, True)`, so every launched config is schema-validated on every launch
already (fast_launcher.py:63, bokeh_launcher.py:69). What 3b actually changes is the *shape* of that
call (retiring the control-coupling flag), not whether validation happens.

### D3 — `install_global_config` installs the RAW dict, never the validated dump
Load-bearing discovery (this is the single most important fact for the executor):

```python
# fast_launcher.py:62-64 (bokeh_launcher.py:68-70 identical) — CURRENT
if config_loader.CONFIG is None:
    config_loader.CONFIG = config_loader.load_global_config(confArg, True)
CONFIG = config_loader.CONFIG
```

`load_global_config(confArg, True)` internally sets `CONFIG = munchify(HelaoConfig(**d).model_dump(
exclude_unset=True, exclude_none=True))` — and then the launcher **immediately overwrites** it with
the function's return value, the raw dict. The munchified validated dump is dead code: at runtime
`CONFIG` is the raw `read_config()` dict (a ruamel `CommentedMap`, a `dict` subclass — the `Munch`
annotation on `config_loader.CONFIG` is already wrong today). This overwrite is *load-bearing*,
because the validated dump silently drops every key `HelaoConfig`/`ServerConfig` doesn't declare:
`loaded_config_path`, `helao_repo_root`, `helao_credentials_path`, launcher-added `deployment`
(fast_launcher.py:135) and `restore_queues_on_startup` (fast_launcher.py:142-143, which relies on
`server_config` being the *same dict object* that `HelaoFastAPI` later reads as `server_cfg`), plus
per-server extras like `action_vis`/`live_vis`/`log_level`. Installing the dump would break the
fleet. So in 3b the typed model is a **validated view**; the raw dict remains the runtime source of
truth behind the `world_cfg` shim. Promoting the typed model to the SoT (requires `extra="allow"` +
declaring the launcher keys) is deferred (§9).

### D4 — Harness lives at `.omc/artifacts/p3/` (shared asset for 3b/3c/3d), with two config fixes the P3 §2.5 sketch missed
Verified against launcher/importer code, an out-of-tree config needs:
1. **Explicit `deployment:` per server.** fast_launcher's deployment auto-detection
   (fast_launcher.py:84-134) globs `<config_grandparent>/*/servers/<group>/<fast>.py`; for a config
   under `.omc/artifacts/p3/` (or `/tmp/`) that glob is empty → `FileNotFoundError`. An explicit
   `deployment:` key (fast_launcher.py:87) skips detection entirely. `async_orch2` lives in
   `helao/deploy/hte/servers/orchestrator/`, the sims in `test`.
2. **Explicit `experiment_path:`/`sequence_path:`.** `import_autolibs.py:135-144` derives the
   library dir from `CONFIG["loaded_config_path"]`'s grandparent basename — garbage for an
   out-of-tree config — but honors config keys `experiment_path`/`sequence_path` as overrides
   (repo-root-relative; all harness processes run with cwd = repo root).

The harness drives servers via `fast_launcher.py` directly (one process per server, exactly what
`launch.py` shells out to) instead of `launch.py` — this sidesteps the keyboard monitor, log
zipping, and the hot-reload watcher, none of which belong in a headless determinism harness.

### D5 — Baseline purity rule
The T0 baseline (two runs, see §3) MUST be captured with a clean working tree at the 3b entry HEAD
**before** any T1/T2 edit is applied. 3b-TA (a new test file + one registry line, no runtime code)
is the only task allowed to run concurrently with T0. Execution order is therefore:
**Wave 1:** T0 ∥ TA → **Wave 2:** T1 → **Wave 3:** T2 → **Wave 4:** V (sweep/compare/commit/push).

---

## 2. Current-state evidence (all verified on HEAD, 2026-07-10)

| Fact | Where |
|---|---|
| `set_global` flag flips pure read into global mutation | config_loader.py:129-147 |
| Both launchers pass `set_global=True`, then overwrite `CONFIG` with the raw dict; validated Munch discarded | fast_launcher.py:62-64, bokeh_launcher.py:68-70 |
| `HelaoConfig`/`ServerConfig` exist, under-used (validate-and-discard only) | config_loader.py:150-223 |
| Import-time snapshots of `config_loader.CONFIG` (the "seeded at import, no injection boundary" audit finding): `server_api.py:17` (consumed at :64, :142 → becomes `app.helao_cfg` → `Base.world_cfg`), `base.py:91` (consumed at :1116), `orch.py:65` (dead — zero uses), `import_autolibs.py:22` (consumed at :135) | grep-verified |
| `Base.__init__` TODO + deep dict nav | base.py:121 (TODO), 143-155 (orch topology, incl. the audit-cited `world_cfg["servers"][key]["host"]` at :150), 165-171 (`run_type`) |
| Only `Base` constructors: `base_api.py:650` (`Base(app=self, dyn_endpoints=...)`) and `Orch(Base)` via `super().__init__(fastapp)` (orch.py:105); core tests use hand-rolled fakes, not real `Base` | grep-verified |
| All 25 tracked configs pass `HelaoConfig` validation | §1 D2 |
| Codehashes hash deployment/library source files (`base.py:393` hashes the endpoint's own module; `import_autolibs` hashes library files) — never `base.py`/`config_loader.py` → codehashes are a free integrity check in the e2e diff | base.py:393, import_autolibs.py:123-125 |
| `yml_load` uses ruamel round-trip → `CONFIG` is a `CommentedMap` (dict subclass) at runtime | yml_tools.py:58-73 |
| No in-repo caller of `load_global_config` besides the two launchers; no importer of `munchify`/`Munch` from config_loader; no importer of `CONFIG` *from* server_api | grep-verified |

---

## 3. 3b-T0 — Build the reusable e2e sim harness + baseline (exact contents)

All five files below go in `/mnt/STORAGE/repos/helao/helao-async/.omc/artifacts/p3/` (operational
artifacts, not committed under `helao/`). They are deliberately **stdlib-only / helao-import-free**
where they observe behavior, so the harness is immune to the code under test.

### 3.1 `demo0_linux.tpl.yml`
Derived from `helao/deploy/test/configs/demo0.yml`: OPERATOR/ACTVIS/GPVIS removed (ORCH + CPSIM +
GPSIM only), `action_vis`/`live_vis` visualizer-wiring keys dropped, Windows `root` replaced by a
`__HLO_ROOT__` placeholder, plus the two D4 fixes. Determinism params kept (GPSIM
`random_seed: 9999`, CPSIM `plate_id: 2750`).

```yaml
dummy: true
simulation: true
experiment_libraries:
  - OERSIM_exp
sequence_libraries:
  - OERSIM_seq
experiment_path: helao/deploy/test/experiments
sequence_path: helao/deploy/test/sequences
run_type: simulation
root: __HLO_ROOT__
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    deployment: hte
    params: {}
  CPSIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: cpsim_server
    deployment: test
    params:
      plate_id: 2750
  GPSIM:
    host: 127.0.0.1
    port: 8003
    group: action
    fast: gpsim_server
    deployment: test
    params:
      random_seed: 9999
```

### 3.2 `enqueue_oersim.py` (stdlib only)
The orchestrator unpacks a sequence server-side when `planned_experiments` is empty and
`sequence_name` is in its imported `sequence_lib` (orch.py:731-738 → `unpack_sequence`), so the
payload is a minimal dict — no helao imports needed. Endpoint: `POST /append_sequence` with
`{"sequence": {...}}` (orch_api.py:406-407, `Body(..., embed=True)`), then `POST /start`
(orch_api.py:331). Completion is judged from the filesystem (no syncer/DB in this group, so a
finished sequence rests in `RUNS_FINISHED`).

```python
#!/usr/bin/env python
"""Enqueue OERSIM_activelearn on the harness ORCH and wait for completion.

Stdlib only on purpose: the harness must not import the code under test.
Usage: python enqueue_oersim.py <hlo_root> [--host H] [--port P] [--timeout S]
"""
import argparse, glob, json, os, sys, time, urllib.request

SEQ = {
    "sequence_name": "OERSIM_activelearn",
    "sequence_label": "p3-harness",
    "sequence_params": {
        "init_random_points": 5,
        "stop_condition": "max_iters",
        "thresh_value": 10,
    },
}

def post(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    return json.loads(body) if body else None

def count_seq_ymls(root, runs_dir):
    return len(glob.glob(os.path.join(root, runs_dir, "**", "*-seq.yml"), recursive=True))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hlo_root")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    # readiness: wait for the orch API to answer
    deadline = time.time() + 180
    while True:
        try:
            post(f"{base}/list_sequences")
            break
        except Exception:
            if time.time() > deadline:
                print("FATAL: ORCH did not come up within 180 s", file=sys.stderr)
                sys.exit(2)
            time.sleep(2)

    post(f"{base}/append_sequence", {"sequence": SEQ})
    post(f"{base}/start")
    print("sequence enqueued + started; polling for completion...")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        terminal = sum(
            count_seq_ymls(args.hlo_root, d)
            for d in ("RUNS_FINISHED", "RUNS_SYNCED", "RUNS_NOSYNC")
        )
        active = count_seq_ymls(args.hlo_root, "RUNS_ACTIVE")
        if terminal >= 1 and active == 0:
            print(f"DONE: {terminal} terminal seq yml(s), RUNS_ACTIVE clean")
            return
        time.sleep(5)
    print("FATAL: sequence did not finish within timeout", file=sys.stderr)
    sys.exit(3)

if __name__ == "__main__":
    main()
```

### 3.3 `normalize_runs_tree.py` (stdlib only)
Per P3 §2.5: volatile tokens replaced by placeholders numbered in order of first appearance so
cross-references still align positionally; file/dir names normalized the same way; sorted manifest
implicit in the ordered output. `*_codehash` fields are deliberately NOT normalized (3b never edits
deployment server/experiment/sequence source — codehash equality is a free integrity check).
`LOGS/`, `STATES/`, `FAULTS/` are skipped (process logs are inherently volatile); only `RUNS_*`
trees are walked.

```python
#!/usr/bin/env python
"""Emit a normalized, diffable snapshot of the RUNS_* trees under an hlo root.

Usage: python normalize_runs_tree.py <hlo_root>  > snapshot.norm
"""
import hashlib, os, re, sys

PATTERNS = [
    ("UUID", re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
    ("ISOTS", re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?")),
    ("DIRTS", re.compile(r"\d{8}\.\d{6,9}")),           # %Y%m%d.%H%M%S(%f) dir stamps
    ("EPOCHNS", re.compile(r"\b1[6-9]\d{17}\b")),        # epoch nanoseconds
    ("EPOCH", re.compile(r"\b1[6-9]\d{8}(?:\.\d+)?\b")),  # epoch seconds
]

class Normalizer:
    def __init__(self):
        self.maps = {name: {} for name, _ in PATTERNS}
    def sub(self, text):
        for name, rx in PATTERNS:
            table = self.maps[name]
            def repl(m, table=table, name=name):
                tok = m.group(0)
                if tok not in table:
                    table[tok] = f"<{name}:{len(table)}>"
                return table[tok]
            text = rx.sub(repl, text)
        return text

def main():
    root = sys.argv[1]
    norm = Normalizer()
    entries = []
    for runs_dir in sorted(d for d in os.listdir(root) if d.startswith("RUNS_")):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, runs_dir)):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                entries.append((os.path.relpath(full, root), full))
    out = []
    for rel, full in entries:
        try:
            with open(full, "r", encoding="utf-8") as f:
                body = norm.sub(f.read())
        except (UnicodeDecodeError, ValueError):
            with open(full, "rb") as f:
                body = "BINARY sha256=" + hashlib.sha256(f.read()).hexdigest()
        out.append(f"===== {norm.sub(rel)} =====\n{body}\n")
    sys.stdout.write("".join(out))

if __name__ == "__main__":
    main()
```

### 3.4 `import_smoke.py`
Constructs **every FastAPI `makeApp`** referenced by every tracked `test` config, replicating
fast_launcher's preamble (install config → resolve deployment → import → `makeApp(key)`), one
isolated subprocess per server so module state can't mask failures. Bokeh modules are
import-checked only (`makeBokehApp` needs a live Document). Version-agnostic so the identical
script runs at baseline (pre-3b) and post-change.

```python
#!/usr/bin/env python
"""makeApp construction smoke over all tracked test-deployment configs.

Run from repo root: conda run -n helao python .omc/artifacts/p3/import_smoke.py
Exit 0 iff every server passes. Prints one line per server: OK/FAIL <config> <key>.
"""
import glob, os, subprocess, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

CHILD = r'''
import glob, os, sys, tempfile
cfg_path, key = sys.argv[1], sys.argv[2]
from helao.helpers import config_loader
cfg = config_loader.read_config(cfg_path)
cfg["root"] = tempfile.mkdtemp(prefix="p3smoke_")
config_loader.HelaoConfig(**cfg)  # schema gate
if hasattr(config_loader, "install_global_config"):   # post-3b
    config_loader.install_global_config(cfg)
else:                                                  # baseline (pre-3b)
    config_loader.CONFIG = cfg
cfg["deployment"] = os.path.basename(os.path.dirname(os.path.dirname(cfg_path)))
scfg = cfg["servers"][key]
group = scfg["group"]
name = scfg.get("fast") or scfg.get("bokeh")
kind = "fast" if scfg.get("fast") else "bokeh"
dep = scfg.get("deployment")
if dep is None:  # mirror fast_launcher.py:88-134 cross-deployment resolution
    hits = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(cfg_path))),
        "*", "servers", group, f"{name}.py")))
    cfg_dep_dir = os.path.dirname(os.path.dirname(cfg_path))
    pref = [h for h in hits if h.startswith(cfg_dep_dir)]
    chosen = (pref or hits)[0]
    dep = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(chosen))))
cfg["deployment"] = dep
mod = __import__(f"helao.deploy.{dep}.servers.{group}.{name}", fromlist=["x"])
if kind == "fast":
    app = mod.makeApp(key)
    assert app is not None, "makeApp returned None"
print("constructed" if kind == "fast" else "imported")
'''

def main():
    from helao.helpers.yml_tools import yml_load  # read-only; safe in parent
    failures = 0
    for cfg_path in sorted(glob.glob(os.path.join(REPO, "helao/deploy/test/configs/*.yml"))):
        cfg = yml_load(open(cfg_path).read())
        for key, scfg in (cfg.get("servers") or {}).items():
            r = subprocess.run(
                [sys.executable, "-c", CHILD, cfg_path, key],
                cwd=REPO, capture_output=True, text=True, timeout=300,
            )
            status = "OK  " if r.returncode == 0 else "FAIL"
            failures += r.returncode != 0
            print(f"{status} {os.path.basename(cfg_path)} {key}")
            if r.returncode != 0:
                print(r.stdout, r.stderr, file=sys.stderr)
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
```

### 3.5 `run_e2e.sh`
```bash
#!/usr/bin/env bash
# One deterministic OERSIM run: launch ORCH+CPSIM+GPSIM, enqueue, wait, shutdown, normalize.
# Usage: run_e2e.sh <label>     (label in {baseline, baseline2, post, ...})
set -euo pipefail
LABEL="${1:?usage: run_e2e.sh <label>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
ROOT="/tmp/hlo_p3_${LABEL}"
CFG="/tmp/p3_demo0_${LABEL}.yml"
PYEXE="$(conda run -n helao python -c 'import sys; print(sys.executable)')"
export PYTHONPATH="$REPO"

rm -rf "$ROOT"; mkdir -p "$ROOT"
sed "s|__HLO_ROOT__|$ROOT|" "$HERE/demo0_linux.tpl.yml" > "$CFG"
cd "$REPO"

pids=()
"$PYEXE" fast_launcher.py "$CFG" CPSIM  &> "/tmp/p3_${LABEL}_cpsim.log" & pids+=($!)
"$PYEXE" fast_launcher.py "$CFG" GPSIM  &> "/tmp/p3_${LABEL}_gpsim.log" & pids+=($!)
sleep 10
"$PYEXE" fast_launcher.py "$CFG" ORCH   &> "/tmp/p3_${LABEL}_orch.log"  & pids+=($!)
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

"$PYEXE" "$HERE/enqueue_oersim.py" "$ROOT" --port 8001 --timeout 900

for port in 8001 8002 8003; do
  curl -s -X POST "http://127.0.0.1:${port}/shutdown" -d '' >/dev/null || true
done
sleep 5
cleanup; trap - EXIT

"$PYEXE" "$HERE/normalize_runs_tree.py" "$ROOT" > "$HERE/${LABEL}.norm"
echo "wrote $HERE/${LABEL}.norm ($(wc -l < "$HERE/${LABEL}.norm") lines)"
```

### 3.6 T0 acceptance criteria (all mandatory)
```bash
bash .omc/artifacts/p3/run_e2e.sh baseline     # reaches DONE (sequence finished)
bash .omc/artifacts/p3/run_e2e.sh baseline2
diff .omc/artifacts/p3/baseline.norm .omc/artifacts/p3/baseline2.norm   # MUST be empty (determinism proof)
conda run -n helao python .omc/artifacts/p3/import_smoke.py \
  | tee .omc/artifacts/p3/smoke_baseline.txt                             # record baseline outcome table
conda run -n helao python run_unit_tests.py                              # suite green at baseline
```
- **No file under `helao/` may be modified by T0.** Baseline captured on clean 3b-entry HEAD (D5).
- If the two baseline runs differ: strengthen the normalizer (new volatile-token pattern with a
  written justification) and re-run until clean. Escalation rule inherited from P3 §2.5: the yml
  criterion (all `-act/-exp/-seq.yml` diff clean) is absolute and may never be weakened; hlo
  headers must diff clean; hlo data-row deltas need an individually written timing cause.
- If any smoke entry FAILs at baseline, it is a pre-existing latent break: log it in
  `.omc/plans/open-questions.md`, exclude it from the pass-requirement (post-change must then be
  identical-or-better vs `smoke_baseline.txt`), and do NOT fix it inside 3b.

---

## 4. 3b-TA — Config-validation audit test (independent, parallel)

**New file `helao/core/tests/unit_test_config_validation.py`** (standalone script, repo `TestReporter`
convention) + one registry line in `run_unit_tests.py`.

```python
"""Validate every tracked deployment config against the HelaoConfig schema.

Guards the 3b invariant: the typed config model must accept every config the
launchers can be pointed at (helao/deploy/{hte,test}/configs/*.yml). Baseline
evidence 2026-07-10: 25/25 pass. Any future failure here is a schema/config
divergence that would break the launch-time validation path.
"""

__all__ = ["config_validation_unit_test"]

import os
from glob import glob

from helao.helpers.config_loader import HelaoConfig, ServerConfig, read_config
from helao.core.tests._test_utils import TestReporter


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def config_validation_unit_test() -> bool:
    reporter = TestReporter("config_validation")
    root = _repo_root()
    for deployment in ("hte", "test"):
        paths = sorted(
            glob(os.path.join(root, "helao", "deploy", deployment, "configs", "*.yml"))
        )
        reporter.check(
            f"{deployment}: at least one tracked config found",
            lambda paths=paths: len(paths) >= 1,
        )
        for path in paths:
            name = f"{deployment}/{os.path.basename(path)}"
            try:
                parsed = HelaoConfig(**read_config(path))
                ok = all(
                    isinstance(v, ServerConfig) for v in (parsed.servers or {}).values()
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: {exc!r}")
                ok = False
            reporter.check(f"{name} validates against HelaoConfig", lambda ok=ok: ok)
    return reporter.success()


if __name__ == "__main__":
    raise SystemExit(0 if config_validation_unit_test() else 1)
```

`run_unit_tests.py` registry addition (one line, after the existing `config_loader` entry):
```python
    ("config_validation", config_validation_unit_test),
```
plus the corresponding import. **Do not hardcode 25** — count may legitimately grow.

Verification: `conda run -n helao python helao/core/tests/unit_test_config_validation.py` exits 0;
`conda run -n helao python run_unit_tests.py` exits 0.

---

## 5. 3b-T1 — Loader split: retire the `set_global` control-coupling flag

**Files (exclusive):** `helao/helpers/config_loader.py`, `fast_launcher.py`, `bokeh_launcher.py`,
`helao/core/tests/unit_test_config_loader.py`.

### 5.1 `config_loader.py` — before (lines 129-147)
```python
def load_global_config(confArg: str, set_global: bool = False) -> dict:
    config_dict = read_config(confArg)
    if set_global:
        global CONFIG
        CONFIG = munchify(
            HelaoConfig(**config_dict).model_dump(exclude_unset=True, exclude_none=True)
        )
    return config_dict
```

### 5.2 `config_loader.py` — after
```python
def read_validated_config(conf_arg: str) -> Tuple[dict, "HelaoConfig"]:
    """Read a config and validate it against :class:`HelaoConfig`. Pure — no module state.

    Returns:
        ``(config_dict, validated)``: the raw dict from :func:`read_config`
        (the runtime source of truth) and its validated typed view. The typed
        view ignores keys the schema does not declare (``loaded_config_path``,
        per-server ``action_vis``/``deployment``/...); it is a schema gate and
        typed accessor, not a replacement for the dict.
    """
    config_dict = read_config(conf_arg)
    return config_dict, HelaoConfig(**config_dict)


def install_global_config(config_dict: dict) -> dict:
    """Publish ``config_dict`` as the module-level :data:`CONFIG` (explicit mutation).

    Installs the object AS-IS. Never install ``HelaoConfig(...).model_dump()``
    here: pydantic drops launcher-added keys (``loaded_config_path``,
    ``deployment``, ``restore_queues_on_startup``, per-server extras) and would
    break fast_launcher's ``server_config`` same-object aliasing (its ``--restore``
    mutation must stay visible through ``HelaoFastAPI.server_cfg``).
    """
    global CONFIG
    CONFIG = config_dict
    return CONFIG


def load_global_config(confArg: str, set_global: bool = False) -> dict:
    """DEPRECATED shim — use :func:`read_validated_config` + :func:`install_global_config`.

    Historical behavior: with ``set_global=True`` this stored a munchified
    ``HelaoConfig`` dump on ``CONFIG`` and returned the raw dict; both in-repo
    callers immediately overwrote ``CONFIG`` with that raw return value, so the
    validated dump was never observable at runtime. The shim now validates and
    installs the raw dict directly — the identical net module state.
    """
    if set_global:
        config_dict, _validated = read_validated_config(confArg)
        install_global_config(config_dict)
        return config_dict
    return read_config(confArg)
```

Housekeeping in the same file:
- `__all__ = ["read_config", "read_validated_config", "install_global_config", "load_global_config", "CONFIG"]`
- `CONFIG: Optional[dict] = None` (the `Munch` annotation is factually wrong today — see §2). Add
  `Tuple` to the typing import. Drop `from munch import munchify, Munch` **only after** a repo grep
  confirms nothing imports `munchify`/`Munch` via config_loader (verified clean 2026-07-10; re-verify
  at execution time).
- Docstring note on module header: `CONFIG` is the raw launcher-augmented dict, by design (D3).

### 5.3 Launchers — before/after (identical in both files)
```python
# BEFORE (fast_launcher.py:62-64 / bokeh_launcher.py:68-70)
if config_loader.CONFIG is None:
    config_loader.CONFIG = config_loader.load_global_config(confArg, True)
CONFIG = config_loader.CONFIG

# AFTER
if config_loader.CONFIG is None:
    config_dict, _validated = config_loader.read_validated_config(confArg)
    config_loader.install_global_config(config_dict)
CONFIG = config_loader.CONFIG
```
Net state identical to today (same raw dict object ends up on `CONFIG`); validation still runs on
every launch; the transient never-observed munchified value disappears.

### 5.4 `unit_test_config_loader.py` additions
Append a section (save `config_loader.CONFIG`, restore in `finally` — the suite runs single-process):
- `read_validated_config(demo_path)` returns `(dict, HelaoConfig)`; dict has `loaded_config_path`;
  validated `run_type == "simulation"`.
- `install_global_config(d)` → `config_loader.CONFIG is d` (object identity — the D3 contract).
- `load_global_config(demo_path, set_global=True)` returns the dict AND `config_loader.CONFIG` is
  that same dict (shim parity).
- `CONFIG = None` reset, then `load_global_config(demo_path)` (default flag) leaves `CONFIG is None`
  (pure-read path unchanged).

### 5.5 T1 verification
- `conda run -n helao python run_unit_tests.py` exit 0.
- `python -c "import helao.helpers.config_loader"` + both launcher files `py_compile`.
- grep gate: `grep -rn "load_global_config" --include='*.py' . | grep -v config_loader.py` → empty
  (no remaining callers; launchers migrated).
- e2e + smoke gates deferred to 3b-V (T1 alone is launch-path-equivalent by construction, but the
  increment gate is collective).

---

## 6. 3b-T2 — Injection seam + typed access + import-time snapshot retirement

**Files (exclusive):** `helao/core/servers/base.py`, `helao/helpers/server_api.py`,
`helao/core/servers/orch.py` (2-line deletion), `helao/helpers/import_autolibs.py` (2-line change),
`helao/core/tests/unit_test_config_seam.py` (new), `run_unit_tests.py` (one registry line).
Depends on T1 (serial chokepoint — same seam).

### 6.1 `server_api.py` — kill the import-time snapshot, open the top of the injection chain
```python
# BEFORE (line 17)
CONFIG = config_loader.CONFIG
# AFTER: line deleted.

# BEFORE (HelaoFastAPI, lines 48 + 64)
def __init__(self, helao_srv: str, *args, **kwargs):
    ...
    self.helao_cfg = CONFIG
# AFTER
def __init__(self, helao_srv: str, *args, helao_cfg: Optional[dict] = None, **kwargs):
    ...
    self.helao_cfg = helao_cfg if helao_cfg is not None else config_loader.CONFIG

# BEFORE (HelaoBokehAPI, lines 134 + 142)
def __init__(self, helao_srv: str, doc):
    ...
    self.helao_cfg = CONFIG
# AFTER
def __init__(self, helao_srv: str, doc, helao_cfg: Optional[dict] = None):
    ...
    self.helao_cfg = helao_cfg if helao_cfg is not None else config_loader.CONFIG
```
(add `from typing import Optional`). Keyword-only-after-`*args` for HelaoFastAPI → zero impact on
every existing `makeApp` call site in every deployment. Behavior in the launcher flow is identical
(launcher installs `CONFIG` before importing the server module); what changes is that importing
`server_api` before config install no longer freezes `None` into the class — the audit's "seeded at
import" coupling is gone at this layer.

### 6.2 `base.py` — the injection seam (the audit's TODO at base.py:121)
Imports: add `from helao.helpers.config_loader import HelaoConfig, ServerConfig` and
`from pydantic import ValidationError` (no circularity: config_loader imports only yml_tools +
pydantic). Delete the dead-ish snapshot `CONFIG = config_loader.CONFIG` (line 91) and rewrite its
single consumer (line 1116) as `config_loader.CONFIG["deployment"]` (lazy — identical value in the
launcher flow, no import-order coupling).

```python
# BEFORE (signature + config block, lines 121-171, abridged to the changed parts)
    # TODO: add world_cfg: dict parameter for BaseAPI to pass config instead of fastapp
    def __init__(self, app: HelaoFastAPI, dyn_endpoints=None):
        ...
        self.world_cfg = self.app.helao_cfg
        orch_keys = [
            k
            for k, d in self.world_cfg.get("servers", {}).items()
            if d["group"] == "orchestrator"
        ]
        if orch_keys:
            self.orch_key = orch_keys[0]
            self.orch_host = self.world_cfg["servers"][self.orch_key]["host"]
            self.orch_port = self.world_cfg["servers"][self.orch_key]["port"]
        else:
            self.orch_key = None
            self.orch_host = None
            self.orch_port = None
        ...
        if "run_type" in self.world_cfg:
            LOGGER.info(f"Found run_type in config: {self.world_cfg['run_type']}")
            self.run_type = self.world_cfg["run_type"].lower()
        else:
            raise ValueError(
                "Missing 'run_type' in config, cannot create server object.",
            )

# AFTER
    def __init__(
        self,
        app: HelaoFastAPI,
        dyn_endpoints=None,
        helao_cfg: Optional[HelaoConfig] = None,
    ):
        ...
        # Dict shim — stays the runtime source of truth for deployment code
        # reading self.base.world_cfg[...]; do not remove in 3b.
        self.world_cfg = self.app.helao_cfg
        # Typed view (3b injection seam). Injected for tests/future callers;
        # defaults to validating the same dict the shim exposes.
        try:
            self.typed_cfg: HelaoConfig = (
                helao_cfg if helao_cfg is not None else HelaoConfig(**self.world_cfg)
            )
        except ValidationError as exc:
            raise ValueError(
                f"world config failed HelaoConfig validation: {exc}"
            ) from exc
        self.typed_server_cfg: Optional[ServerConfig] = (
            self.typed_cfg.servers or {}
        ).get(self.server.server_name)

        servers_cfg = self.typed_cfg.servers or {}
        orch_keys = [k for k, s in servers_cfg.items() if s.group == "orchestrator"]
        if orch_keys:
            self.orch_key = orch_keys[0]
            self.orch_host = servers_cfg[self.orch_key].host
            self.orch_port = servers_cfg[self.orch_key].port
        else:
            self.orch_key = None
            self.orch_host = None
            self.orch_port = None
        ...
        LOGGER.info(f"Found run_type in config: {self.typed_cfg.run_type}")
        self.run_type = self.typed_cfg.run_type.lower()
```

Behavior-parity notes (executor must preserve, reviewer must check):
- `helao_dirs(self.world_cfg, ...)`, the `root` ValueError guard, `.get("dummy"/"simulation")`
  reads (base.py:1178-1179), and `async_action_dispatcher(self.world_cfg, ...)` (base.py:721) all
  **stay on the dict shim** — typed migration of those is 3b-ii (§8).
- Dict iteration order == pydantic `Dict[str, ServerConfig]` insertion order → same first-orch
  selection.
- The old `run_type`-missing `ValueError` becomes unreachable: `HelaoConfig` requires
  `run_type`+`root`, so the `ValidationError→ValueError` wrap fires first. The documented "Raises
  ValueError" contract is preserved; only the message changes, and only for configs that today are
  unlaunchable anyway (launchers validate at load). Declared error-path delta, not a runtime one.
- `Orch(Base)`'s `super().__init__(fastapp)` (orch.py:105) and `base_api.py:650`'s
  `Base(app=self, dyn_endpoints=...)` need no change — the new param is optional.
- Docstring: update to document `helao_cfg` and delete the now-implemented TODO comment.

### 6.3 `orch.py` + `import_autolibs.py` — same snapshot pattern, same fix
- `orch.py:60,65`: delete `from helao.helpers import config_loader` + `CONFIG = config_loader.CONFIG`
  — grep-verified zero uses of either in the rest of the file (dead snapshot).
- `import_autolibs.py:22`: delete `CONFIG = config_loader.CONFIG`; at line ~135 replace
  `CONFIG["loaded_config_path"]` with `config_loader.CONFIG["loaded_config_path"]`. Identical value
  in every launched process; removes the import-order landmine.
- `vis_subscriber.py:71` and `analysis_driver.py:505` already do the lazy
  `config_loader.CONFIG or {}` pattern — no change.

### 6.4 New standalone test `helao/core/tests/unit_test_config_seam.py`
Registered in `run_unit_tests.py` (`("config_seam", config_seam_unit_test)`). Uses a duck-typed stub
app (`Base.__init__` touches only `app.server`, `app.server_cfg`, `app.server_params`,
`app.helao_cfg` — grep-verified), so no FastAPI/uvicorn machinery is needed:

1. Load `demo0.yml` via `read_validated_config`; override `root` to a tempdir; build a stub app:
   `MachineModel(server_name="ORCH", machine_name=..., hostname=..., port=...)` + `server_cfg` /
   `server_params` slices + `helao_cfg` = the raw dict.
2. `b1 = Base(app=stub)` (default path) and `b2 = Base(app=stub, helao_cfg=validated)` (injected
   path). Assert `b1.orch_key == b2.orch_key`, `orch_host`, `orch_port`, `run_type` all equal, and
   each equals the legacy dict navigation result computed inline from the raw dict
   (`world_cfg["servers"][key]["host"]` etc.).
3. Assert `b1.world_cfg is stub.helao_cfg` (shim is the same object — deployment-code contract).
4. Assert `b1.typed_server_cfg.host == b1.world_cfg["servers"]["ORCH"]["host"]`.
5. Negative: `Base(app=stub_with_cfg_missing_run_type)` raises `ValueError` (wrap works).
6. `HelaoFastAPI`/`HelaoBokehAPI` lazy+injection: with `config_loader.CONFIG` saved/None, assert
   `HelaoBokehAPI("X", doc=stub_doc, helao_cfg=cfg_dict)` uses the injected dict (Bokeh variant is
   the cheap one to construct; for `HelaoFastAPI` assert via source-level behavior only if
   construction proves heavy — RPC dispatcher creation is registry-only, no socket bind, so direct
   construction should work). Restore `config_loader.CONFIG` in `finally`.

### 6.5 T2 verification
- `conda run -n helao python helao/core/tests/unit_test_config_seam.py` exit 0; suite exit 0.
- Import smokes: `python -c "import helao.core.servers.base, helao.core.servers.orch, helao.helpers.server_api, helao.helpers.import_autolibs"`.
- grep gates: `grep -rn '^CONFIG = config_loader.CONFIG' helao/` → empty;
  `grep -n 'TODO: add world_cfg' helao/core/servers/base.py` → empty.
- No stray diff: `git diff` shows only the documented substitutions + new files.

---

## 7. Task table

Executor model: **Sonnet** for all tasks. Every task's gate includes
`conda run -n helao python run_unit_tests.py` exit 0 and a no-stray-diff check.

| ID | Title | Files (exclusive ownership) | Depends | Group | Verification |
|----|-------|------------------------------|---------|-------|--------------|
| 3b-T0 | Build reusable e2e sim harness + capture baseline on clean HEAD | `.omc/artifacts/p3/{demo0_linux.tpl.yml, enqueue_oersim.py, normalize_runs_tree.py, import_smoke.py, run_e2e.sh, baseline.norm, baseline2.norm, smoke_baseline.txt}` — **nothing under `helao/`** | — | Wave 1 (∥ TA) | §3.6: run reaches DONE; double-run determinism diff EMPTY; smoke baseline table recorded; suite green at baseline |
| 3b-TA | Config-validation audit test (all tracked hte+test configs) | `helao/core/tests/unit_test_config_validation.py` (new), `run_unit_tests.py` (registry line) | — | Wave 1 (∥ T0) | §4: standalone test exit 0 (25/25 today); suite exit 0 |
| 3b-T1 | Loader split: `read_validated_config` + `install_global_config`, retire `set_global` flag, migrate both launchers | `helao/helpers/config_loader.py`, `fast_launcher.py`, `bokeh_launcher.py`, `helao/core/tests/unit_test_config_loader.py` | T0, TA (D5 ordering) | Wave 2 (serial) | §5.5 |
| 3b-T2 | Injection seam (`Base.__init__` + `HelaoFastAPI`/`HelaoBokehAPI`), typed orch-topology/run_type access, retire import-time CONFIG snapshots | `helao/core/servers/base.py`, `helao/helpers/server_api.py`, `helao/core/servers/orch.py`, `helao/helpers/import_autolibs.py`, `helao/core/tests/unit_test_config_seam.py` (new), `run_unit_tests.py` (registry line) | T1 | Wave 3 (serial — chokepoint owner of base.py) | §6.5 |
| 3b-V | Verification sweep: suite + all-makeApp import-smoke + hte py_compile + e2e capture/compare + commit + push | — (no code changes; may add normalizer patterns per §3.6 escalation with written cause) | T0, TA, T1, T2 | Wave 4 (serial-post) | §7.1 below |

### 7.1 3b-V sweep (all must pass)
```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python helao/core/tests/unit_test_config_validation.py
conda run -n helao python helao/core/tests/unit_test_config_loader.py    # via suite, but run standalone too
conda run -n helao python helao/core/tests/unit_test_config_seam.py

# every tracked test-deployment makeApp constructs (compare against baseline table)
conda run -n helao python .omc/artifacts/p3/import_smoke.py | tee .omc/artifacts/p3/smoke_post.txt
diff .omc/artifacts/p3/smoke_baseline.txt .omc/artifacts/p3/smoke_post.txt   # MUST be empty

# hte: constructors compile (Windows-only imports not executable on Linux)
conda run -n helao python -m compileall -q helao/deploy/hte/servers helao/deploy/hte/drivers

# end-to-end behavior identity
bash .omc/artifacts/p3/run_e2e.sh post
diff .omc/artifacts/p3/baseline.norm .omc/artifacts/p3/post.norm             # MUST be empty

# grep gates
grep -rn "load_global_config" --include='*.py' . | grep -v "config_loader.py"          # empty
grep -rn "^CONFIG = config_loader.CONFIG" helao/ --include='*.py'                       # empty
grep -rEn "world_cfg\[.servers.\]\[[^]]+\]\[.(host|port).\]" helao/core/servers/base.py # empty
```
Then: **one parent-repo commit** (T1+T2+TA test files; harness stays untracked under `.omc/`) on
`feat/cards-refactor`, commit message stating the e2e diff-empty proof and the smoke-parity result;
push (per-increment push policy). **No nested-repo commits in 3b** — Deployment-A/Deployment-B/Deployment-C are untouched
(their deployment code reads `self.base.world_cfg[...]`, which the shim preserves; `Base.__init__`
gains only an optional trailing param).

---

## 8. Deferred: 3b-ii sketch (wider typed access — next detail pass, before/alongside 3c)

- orch.py `world_cfg` nav sites: `:125` (`"DB" in servers`), `:320`, `:963`
  (`world_cfg["servers"][act.action_server.server_name]`), `:2476`, `:2532/:2569` (`world_cfg["root"]`)
  → route through `self.typed_cfg` (Orch inherits the seam from Base for free).
- vis.py:66-67 (`HelaoVis`) — mirror the Base seam for Bokeh apps; base_api.py:652/:717.
- `helao_dirs(world_cfg: dict, ...)` — typed overload accepting `HelaoConfig`.
- Retire the deprecated `load_global_config` shim once private-deployment grep confirms zero callers
  outside this workspace.
- Endgame (3c/3d of the Alignment thread): make the typed model the SoT — requires
  `model_config = ConfigDict(extra="allow")` + declaring launcher keys (`loaded_config_path`,
  `deployment`, `restore_queues_on_startup`, `log_level`, `action_vis`, `live_vis`, ...) as real
  `HelaoConfig`/`ServerConfig` fields, then flipping `install_global_config` to store the model and
  `world_cfg` to a `model_dump` view. Only after the harness has gated 3b and 3b-ii.

---

## 9. Risk and rollback

- **The D3 landmine.** The one way an executor silently breaks the fleet is installing the validated
  dump instead of the raw dict (drops `loaded_config_path`/`deployment`/`restore_queues_on_startup`
  aliasing). Guarded three ways: the docstring contract, the object-identity assertion in
  unit_test_config_loader (§5.4), and the e2e diff.
- **Baseline purity (D5).** T1/T2 edits before baseline capture invalidate the whole proof. T0 runs
  first on clean HEAD; 3b-V re-runs the harness on the changed tree only.
- **Double validation cost.** `Base.__init__` now validates `HelaoConfig(**world_cfg)` once per
  process in addition to the launcher's validation — microseconds on a 25-server config, once per
  process lifetime. Not a risk, just declared.
- **Declared error-path deltas (not runtime deltas):** (i) a config missing `run_type`/`root` now
  fails `Base.__init__` with the wrapped-ValidationError `ValueError` message instead of the legacy
  message — such configs cannot pass the launchers today; (ii) a hypothetical external caller of
  `load_global_config(x, True)` that did *not* overwrite `CONFIG` would now see the raw dict instead
  of the validated Munch — no such caller exists in-repo (grep-verified), and the raw dict is what
  every in-repo consumer already gets.
- **Harness nondeterminism** (gpflow/GP fitting in GPSIM despite `random_seed: 9999`): surfaced by
  the T0 double-baseline check *before* any code changes, so it can never be misattributed to 3b.
  Mitigations in order: strengthen normalizer patterns (with written cause), shorten the sequence
  (`thresh_value`), and as a hard floor the P3 §2.5 rule — yml files must diff clean, no exceptions.
- **Process cleanup on Linux:** `run_e2e.sh` resolves the env's python binary once (avoids
  conda-run wrapper orphans), shuts servers down via `POST /shutdown`, then kills PIDs as fallback.
  If orphans persist, `pkill -f fast_launcher.py` is the manual escape hatch.
- **hte exposure:** zero hte files change; hte constructors are exercised via core (`Base`,
  `HelaoFastAPI`) through the test-deployment smoke, plus `compileall`. The hot-reload watcher only
  affects running production groups on their deployed branches — not `feat/cards-refactor`.
- **Rollback:** single parent commit; `git revert` restores launchers+loader+seam atomically. The
  harness under `.omc/artifacts/p3/` is non-code and survives (intentionally — 3c/3d reuse it).
  No cross-repo ordering constraints (no nested-repo commits).

---

## 10. Open questions (appended to `.omc/plans/open-questions.md`)

- [x] ~~Do any tracked hte/test configs fail `HelaoConfig` validation today?~~ **ANSWERED
      2026-07-10: no — 25/25 pass** (§1 D2). 3b-TA codifies it.
- [ ] When to promote the typed model to runtime SoT (`extra="allow"` + launcher-key fields, flip
      `install_global_config` to store the model)? Proposed: after 3b-ii lands and one soak cycle.
- [ ] `ServerConfig` runtime keys used but undeclared (`deployment`, `restore_queues_on_startup`,
      `log_level`, `action_vis`, `live_vis`, `regular_update*`, `hlo_postprocess_libs`, `cmd_print`):
      declare as fields vs `extra="allow"` — decide in the SoT-promotion increment.
- [ ] Deprecated `load_global_config` shim removal timing — grep private deployments outside this
      workspace first.
- [ ] Harness config placement: stays `.omc/artifacts/p3/` (untracked) for 3b; consider promoting
      `demo0_linux.yml` to a tracked `test` config once stable, so any machine can re-baseline.
- [ ] If T0's import-smoke baseline reveals any pre-existing FAIL among tracked test configs, it is
      logged here as a latent break (excluded from 3b's pass criterion, fixed outside 3b).
