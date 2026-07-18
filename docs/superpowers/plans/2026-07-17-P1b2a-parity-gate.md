# P1b2a: Hexagon Parity Gate (GM-1…GM-5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the P1b1 hexagon composition (reducer dispatch loop + legacy-wrapped adapters) produces **normalized-byte-identical** artifacts to legacy across GM-1…GM-5, closing the artifact-parity half of the master-spec P1 gate (§12 P1).

**Architecture:** No new runtime code. This is a **capture-and-diff** phase: launch the `goldenhex` group (hexagon ORCH+SIM via the P1b1 graft, legacy sim DB), drive each golden scenario through the P0 `harness.capture` rig, snapshot the tree, and run `harness.parity` against the corresponding **legacy** golden set. Gate = exit 0 (0 normalized diffs) for every scenario. GM-4 (estop lifecycle) has no legacy golden yet — it was deferred in P0 by the `clear_in_finished` dict-mutation bug (fixed on `unstable`, commit `5fe5784a`); this plan captures its legacy baseline first, then diffs the hexagon path against it. §10.3 concurrency suite and §9 behavior tests are **P1b2b — not in this plan.**

**Tech Stack:** Python 3.12 in the `helao` conda env; `launch.py` (uvicorn/Bokeh launcher); `harness/` package (P0 normalizer + `capture`/`parity` CLIs); `helao/hexagon/` (P1a domain/ports + P1b1 adapters/app/graft); `helao/deploy/test/configs/{golden,goldenhex}.yml`.

## Global Constraints

- **Zero legacy edits.** The hexagon composition wraps legacy behavior; parity is achieved by construction, not by patching legacy. No file under `helao/core/`, `helao/helpers/`, or `helao/deploy/test/servers/` is modified. If a diff can only be closed by editing legacy, STOP and escalate — that is a real fidelity finding, not a task step.
- **No private-deployment names** in any committed file, comment, log, or docstring. This is the public parent repo. Deployment aliases only (A/B/C/D) if a deployment must be referenced at all; this phase touches only the `test` deployment.
- **All Python runs via `conda run -n helao`** — never the OS python (3.14). `PYTHONPATH` must be the repo root (`/mnt/STORAGE/repos/helao/helao-async`); `launch.py` and `conda run` set this from the env config, but capture/parity invocations run from the repo root.
- **Normalizer volatile-field list is EXACTLY master-spec §5.5** — no additions. All per-scenario value-masking (masked HLO columns, row-count tolerances, content-masked files) lives in the **golden set's `provenance.yml`**, never in harness code. `harness.parity` reads masking from the golden's manifest.
- **Golden sets** live outside the repo at `/home/dan/helao_goldens/<scenario>/{run1,run2}`. Legacy captures use config prefix `golden` (root `/home/dan/INST_hlo_golden`). Hexagon candidates use config prefix `goldenhex` (root `/home/dan/INST_hlo_hexsmoke`) and are written to `/home/dan/hexsmoke_captures/<scenario>_p1b2/`. Ports are identical across `golden.yml`/`goldenhex.yml` (8001/8002/8010) so `harness.capture` works unmodified.
- **`harness.capture` refuses a non-fresh root** — every launch/capture cycle wipes its config root first. One scenario per launch; never reuse a live group across scenarios.
- **Parity gate is `harness.parity` exit 0** (0 diffs) for the hexagon candidate vs the legacy golden `run1`. A nonzero exit is a blocker: root-cause it (systematic-debugging), do not mask by adding to §5.5 or inventing new manifest masks beyond what legacy-vs-legacy already required.
- **Reference state:** branch off `unstable` at `f413864b` (P1b1 merged). Existing legacy goldens GM-1/2/3/5 were captured at legacy sha `2c390c69` (pre-P0-merge); Task 1 re-verifies one on the current sha before trusting any hexagon diff.

---

### Task 1: Preflight — legacy still reproduces its own golden on the current sha

**Files:**
- Create: `helao/hexagon/tests/smoke/parity_run.sh` (reusable launch→capture→kill→diff driver)
- Test: the driver's own exit code against GM-1 legacy

**Interfaces:**
- Consumes: `launch.py <prefix> --no-hot-reload`; `harness.capture --scenario <S> --root <R> --out <O> --config-prefix <prefix>`; `helao/hexagon/tests/smoke/kill_group.py <root> [prefix]`; `harness.parity --golden <G> --candidate <C> --report <report>`.
- Produces: `parity_run.sh <scenario> <config_prefix> <root> <golden_dir> <candidate_dir>` — wipes `<root>`, background-launches the group, waits for ports 8001/8002/8010, runs capture to `<candidate_dir>`, kills the group, runs `harness.parity` golden-vs-candidate, and exits with parity's exit code. Every later task invokes this script.

- [ ] **Step 1: Write the reusable driver**

`helao/hexagon/tests/smoke/parity_run.sh`:

```bash
#!/usr/bin/env bash
# Launch a HELAO group, capture one golden scenario, kill it, and diff the
# captured tree against a legacy golden. Exit code = harness.parity exit code
# (0 PASS, 1 diffs, 2 harness error). Used by the P1b2a parity gate.
#
# Usage: parity_run.sh <scenario> <config_prefix> <root> <golden_dir> <candidate_dir>
set -u
SCEN="$1"; PREFIX="$2"; ROOT="$3"; GOLDEN="$4"; CAND="$5"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO" || exit 2
LAUNCHLOG="/tmp/p1b2a_${PREFIX}_${SCEN}.launch.log"

echo "[parity_run] wiping fresh root $ROOT"
rm -rf "$ROOT"
rm -rf "$CAND"

echo "[parity_run] launching $PREFIX (log: $LAUNCHLOG)"
nohup conda run -n helao python launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
LAUNCH_PID=$!

echo "[parity_run] waiting for ports 8001/8002/8010"
UP=0
for i in $(seq 1 90); do
  if conda run -n helao python - <<'PY' 2>/dev/null
import socket, sys
ok = all(socket.socket().connect_ex(("127.0.0.1", p)) == 0 for p in (8001, 8002, 8010))
sys.exit(0 if ok else 1)
PY
  then UP=1; break; fi
  sleep 2
done
if [ "$UP" -ne 1 ]; then
  echo "[parity_run] FAIL ports never came up; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 5  # settle: orch loop parked, action servers registered

echo "[parity_run] capturing $SCEN -> $CAND"
conda run -n helao python -m harness.capture \
  --scenario "$SCEN" --root "$ROOT" --out "$CAND" --config-prefix "$PREFIX"
CAP_RC=$?

echo "[parity_run] killing group"
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
kill "$LAUNCH_PID" 2>/dev/null
if [ "$CAP_RC" -ne 0 ]; then
  echo "[parity_run] FAIL capture rc=$CAP_RC; launch tail:"; tail -40 "$LAUNCHLOG"; exit 2
fi

echo "[parity_run] parity: golden=$GOLDEN candidate=$CAND"
conda run -n helao python -m harness.parity \
  --golden "$GOLDEN" --candidate "$CAND" --report "${CAND}/parity-report.json"
exit $?
```

- [ ] **Step 2: Make it executable and confirm the group is not already running**

Run:
```bash
chmod +x helao/hexagon/tests/smoke/parity_run.sh
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_golden golden 2>/dev/null
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_hexsmoke goldenhex 2>/dev/null
ps aux | grep -E "fast_launcher|launch.py" | grep -v grep || echo "no stray launchers"
```
Expected: "no stray launchers".

- [ ] **Step 3: Re-capture GM-1 on the CURRENT legacy sha and diff vs the existing golden**

This proves the legacy `golden` config still reproduces the 2c390c69 golden on `f413864b` (P0/P1a/P1b1 merges + the `clear_in_finished` fix added trees but must not have perturbed legacy GM-1 behavior). If this fails, every later hexagon diff is ambiguous — stop and escalate.

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-1 golden /home/dan/INST_hlo_golden \
  /home/dan/helao_goldens/GM-1/run1 \
  /home/dan/hexsmoke_captures/gm1_legacy_recheck
```
Expected: final line `parity run <12-hex>: PASS (0 diffs) scenario=GM-1`, script exit 0.

- [ ] **Step 4: If Step 3 fails, escalate; if it passes, commit the driver**

If nonzero: read `/home/dan/hexsmoke_captures/gm1_legacy_recheck/parity-report.json`, classify the diffs (real legacy drift vs harness/env), and STOP — report to the controller. Do not proceed.

If exit 0:
```bash
git add helao/hexagon/tests/smoke/parity_run.sh
git commit -m "test(hexagon): reusable launch/capture/kill/diff driver for P1b2a parity gate (P1b2a T1)

Preflight confirmed legacy 'golden' still reproduces the GM-1 golden on the
current sha (0 normalized diffs), so any hexagon-path diff is attributable
to the composition, not legacy drift.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HUFTqzW3UT5jnsm1XfweE5"
```

---

### Task 2: GM-4 legacy baseline (estop lifecycle) — the P0-deferred capture

**Files:**
- Create: `/home/dan/helao_goldens/GM-4/run1/` + `/run2/` (golden set, outside repo)
- Create: `/home/dan/helao_goldens/GM-4/baseline-report.json` (run1-vs-run2 baseline diff)

**Interfaces:**
- Consumes: `parity_run.sh` (Task 1) is NOT used here (baseline is legacy-vs-legacy, two independent runs); use raw `harness.capture` twice + `harness.parity` once. `harness.capture --scenario GM-4` builds the three-leg lifecycle sequence (stop-intent drain+resume, `skip_experiment` truncation, `estop_orch` mid-experiment → `[finished, estopped]` + deferred promotion, then `clear_estop`) per P0 capture.py.
- Produces: the GM-4 legacy golden set that Task 7 diffs the hexagon path against. Establishes GM-4 satisfies the P0 gate criterion (two legacy runs normalized-identical) now that `clear_in_finished` is fixed.

- [ ] **Step 1: Capture GM-4 legacy run1**

Run:
```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_golden golden 2>/dev/null
rm -rf /home/dan/INST_hlo_golden
nohup conda run -n helao python launch.py golden --no-hot-reload > /tmp/p1b2a_gm4_run1.log 2>&1 &
# wait ~40s for 8001/8002/8010, then:
conda run -n helao python -m harness.capture \
  --scenario GM-4 --root /home/dan/INST_hlo_golden \
  --out /home/dan/helao_goldens/GM-4/run1 --config-prefix golden
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_golden golden
```
Expected: `captured GM-4 -> /home/dan/helao_goldens/GM-4/run1`, exit 0; `/home/dan/helao_goldens/GM-4/run1/provenance.yml` and `root/` present.

- [ ] **Step 2: Verify the estopped terminal state landed (sanity before trusting the baseline)**

Run:
```bash
grep -rl "estopped" /home/dan/helao_goldens/GM-4/run1/root/RUNS_FINISHED 2>/dev/null | head
conda run -n helao python - <<'PY'
import glob, yaml
ymls = glob.glob("/home/dan/helao_goldens/GM-4/run1/root/**/*-seq.yml", recursive=True)
ymls += glob.glob("/home/dan/helao_goldens/GM-4/run1/root/**/*-exp.yml", recursive=True)
found = False
for y in ymls:
    d = yaml.safe_load(open(y))
    st = d.get("sequence_status") or d.get("experiment_status") or []
    if "estopped" in st:
        print("estopped terminal status present:", y, st); found = True
print("OK" if found else "WARN no estopped status found")
PY
```
Expected: at least one artifact carries an `estopped` status alongside `finished` (the `[finished, estopped]` terminal set). If absent, the estop leg did not fire — stop and inspect `/tmp/p1b2a_gm4_run1.log`.

- [ ] **Step 3: Capture GM-4 legacy run2 (fresh root, independent run)**

Run:
```bash
rm -rf /home/dan/INST_hlo_golden
nohup conda run -n helao python launch.py golden --no-hot-reload > /tmp/p1b2a_gm4_run2.log 2>&1 &
# wait for ports, then:
conda run -n helao python -m harness.capture \
  --scenario GM-4 --root /home/dan/INST_hlo_golden \
  --out /home/dan/helao_goldens/GM-4/run2 --config-prefix golden
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_golden golden
```
Expected: `captured GM-4 -> /home/dan/helao_goldens/GM-4/run2`, exit 0.

- [ ] **Step 4: Baseline parity — run1 vs run2 must be normalized-identical**

Run:
```bash
conda run -n helao python -m harness.parity \
  --golden /home/dan/helao_goldens/GM-4/run1 \
  --candidate /home/dan/helao_goldens/GM-4/run2 \
  --report /home/dan/helao_goldens/GM-4/baseline-report.json
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-4`, exit 0.

- [ ] **Step 5: If baseline shows diffs, resolve via manifest masking — but only what legacy-vs-legacy demands**

A nonzero baseline means real nondeterminism in the estop leg (e.g. completion-order-variable `dispatched_*_abbr`, unseeded sim values). Legitimate masks go in **`/home/dan/helao_goldens/GM-4/run1/provenance.yml`** using only the three sanctioned fields (`masked_hlo_columns`, `hlo_row_count_tolerance`, `content_masked_files`) and stable-key sorting the harness already applies. Do NOT touch `harness/` code or §5.5. Re-run Step 4 until exit 0. If a diff is a genuine ordering hazard not covered by existing normalization, STOP and escalate (it may be a spec §5.5 amendment, which is out of scope for this plan).

- [ ] **Step 6: Record the baseline (goldens are outside the repo — nothing to git-commit)**

No repo commit for the golden data. Append to the ledger:
```bash
echo "P1b2a-Task 2: complete — GM-4 legacy golden captured (run1+run2), baseline PASS (0 diffs); estopped terminal status verified. Golden at /home/dan/helao_goldens/GM-4/." >> .superpowers/sdd/progress.md
```

---

### Task 3: GM-1 hexagon-path parity (primary — streamed data + processes + sync)

**Files:**
- Create: `/home/dan/hexsmoke_captures/GM-1_p1b2/` (candidate + `parity-report.json`)

**Interfaces:**
- Consumes: `parity_run.sh` (Task 1); legacy golden `/home/dan/helao_goldens/GM-1/run1`.
- Produces: proof that the hexagon composition reproduces GM-1 byte-for-byte (this was run end-to-end in P1b1 T12 as a wiring smoke; here it is the parity claim).

- [ ] **Step 1: Run the hexagon GM-1 capture-and-diff**

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-1 goldenhex /home/dan/INST_hlo_hexsmoke \
  /home/dan/helao_goldens/GM-1/run1 \
  /home/dan/hexsmoke_captures/GM-1_p1b2
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-1`, script exit 0.

- [ ] **Step 2: If diffs appear, root-cause (do not mask)**

Read `/home/dan/hexsmoke_captures/GM-1_p1b2/parity-report.json`. Because Task 1 proved legacy reproduces GM-1 at 0 diffs on this sha, any diff here is a **hexagon composition fidelity gap** (a DD-2/DD-3 behavior difference, an adapter that reaches past a port, a missed legacy side-effect). Diagnose with systematic-debugging; the fix is in `helao/hexagon/` (never legacy, never §5.5, never a new mask). Re-run Step 1 until exit 0. If the fix touches `helao/hexagon/` code, commit it with a `fix(hexagon):` message naming the parity finding.

- [ ] **Step 3: Record**

```bash
echo "P1b2a-Task 3: complete — GM-1 hexagon parity PASS (0 diffs) vs legacy golden. Candidate /home/dan/hexsmoke_captures/GM-1_p1b2." >> .superpowers/sdd/progress.md
```

---

### Task 4: GM-2 hexagon-path parity (scheduling / nonblocking waits)

**Files:**
- Create: `/home/dan/hexsmoke_captures/GM-2_p1b2/`

**Interfaces:**
- Consumes: `parity_run.sh`; legacy golden `/home/dan/helao_goldens/GM-2/run1`. GM-2 = `TEST_consecutive_noblocking` — nonblocking waits, `wait_for_*` start conditions, cross-cycle `from_global_exp_params` handoff (exercises the loop's start-condition and global-params paths).

- [ ] **Step 1: Run the hexagon GM-2 capture-and-diff**

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-2 goldenhex /home/dan/INST_hlo_hexsmoke \
  /home/dan/helao_goldens/GM-2/run1 \
  /home/dan/hexsmoke_captures/GM-2_p1b2
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-2`, script exit 0.

- [ ] **Step 2: If diffs appear, root-cause (do not mask)**

Same rule as Task 3 Step 2. GM-2's likely fidelity risks: nonblocking-flag survival across the endpoint (the `send_nbstatuspackage → update_nonblocking` path) and `from_global_exp_params` handoff ordering. Fix in `helao/hexagon/`; re-run until exit 0.

- [ ] **Step 3: Record**

```bash
echo "P1b2a-Task 4: complete — GM-2 hexagon parity PASS (0 diffs)." >> .superpowers/sdd/progress.md
```

---

### Task 5: GM-3 hexagon-path parity (manual/diag — direct action POST, RUNS_DIAG)

**Files:**
- Create: `/home/dan/hexsmoke_captures/GM-3_p1b2/`

**Interfaces:**
- Consumes: `parity_run.sh`; legacy golden `/home/dan/helao_goldens/GM-3/run1`. GM-3 = one direct (non-orch) POST to `http://127.0.0.1:8002/SIM/acquire_data` — synthesized `seq--`/`exp--` parents, whole tree under RUNS_DIAG, never synced (exercises the action server's standalone artifact path independent of the orchestrator loop).

- [ ] **Step 1: Run the hexagon GM-3 capture-and-diff**

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-3 goldenhex /home/dan/INST_hlo_hexsmoke \
  /home/dan/helao_goldens/GM-3/run1 \
  /home/dan/hexsmoke_captures/GM-3_p1b2
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-3`, script exit 0.

- [ ] **Step 2: If diffs appear, root-cause (do not mask)**

Same rule as Task 3 Step 2. GM-3 isolates the hexagon-hosted SIM action server's own artifact writing (synthesized parents, RUNS_DIAG placement). A diff here points at the action-app wrap (`makeActionApp`) or an artifact-store/data-sink path, not the orch loop. Fix in `helao/hexagon/`; re-run until exit 0.

- [ ] **Step 3: Record**

```bash
echo "P1b2a-Task 5: complete — GM-3 hexagon parity PASS (0 diffs)." >> .superpowers/sdd/progress.md
```

---

### Task 6: GM-5 hexagon-path parity (sync leg — reset_sync / finish_pending round-trip)

**Files:**
- Create: `/home/dan/hexsmoke_captures/GM-5_p1b2/`

**Interfaces:**
- Consumes: `parity_run.sh`; legacy golden `/home/dan/helao_goldens/GM-5/run1`. GM-5 = GM-1's sequence carried through the recording sim DB, then `reset_sync` (zip → `.orig`, files back to FINISHED) + `finish_pending` round-trip, re-quiesce, snapshot — exercises `.prg` lifecycle, `-prc.yml`, the RUNS_SYNCED zip member set, and the recorded S3 key/payload set twice over.

- [ ] **Step 1: Run the hexagon GM-5 capture-and-diff**

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-5 goldenhex /home/dan/INST_hlo_hexsmoke \
  /home/dan/helao_goldens/GM-5/run1 \
  /home/dan/hexsmoke_captures/GM-5_p1b2
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-5`, script exit 0.

- [ ] **Step 2: If diffs appear, root-cause (do not mask)**

Same rule as Task 3 Step 2. GM-5's fidelity surface is the sync/S3 leg (the sim DB is legacy in `goldenhex`, so a diff most likely traces to what the hexagon ORCH hands the syncer: `-prc.yml` content, `.prg` bookkeeping, or process-group metadata). Fix in `helao/hexagon/`; re-run until exit 0.

- [ ] **Step 3: Record**

```bash
echo "P1b2a-Task 6: complete — GM-5 hexagon parity PASS (0 diffs)." >> .superpowers/sdd/progress.md
```

---

### Task 7: GM-4 hexagon-path parity (estop lifecycle — DD-3, the riskiest)

**Files:**
- Create: `/home/dan/hexsmoke_captures/GM-4_p1b2/`

**Interfaces:**
- Consumes: `parity_run.sh`; the **Task 2** legacy golden `/home/dan/helao_goldens/GM-4/run1`. GM-4 exercises the three DD-3 live-estop re-check sites through the reducer runtime: stop-intent drain, `skip_experiment`, and `estop_orch` mid-experiment → single finalizer, `[finished, estopped]` terminal artifacts, deferred promotion, then `clear_estop`.

- [ ] **Step 1: Run the hexagon GM-4 capture-and-diff**

Run:
```bash
helao/hexagon/tests/smoke/parity_run.sh \
  GM-4 goldenhex /home/dan/INST_hlo_hexsmoke \
  /home/dan/helao_goldens/GM-4/run1 \
  /home/dan/hexsmoke_captures/GM-4_p1b2
```
Expected: `parity run <12-hex>: PASS (0 diffs) scenario=GM-4`, script exit 0.

- [ ] **Step 2: If diffs appear, root-cause (do not mask) — expect this to be where composition fidelity is tested hardest**

Read the report. GM-4 is where the reducer FSM's estop path, the DD-3 re-read-live re-checks (`OrchCommandRunner` guard sites), and the single-finalizer guarantee are proven against real legacy artifacts. Likely finding shapes: a `[finished, estopped]` status list ordered/deduped differently, a duplicated `finished` from a double finalizer, a missed deferred-promotion, or the `_estop_transition` log-parity backlog item (domain alerts `reason` vs legacy fixed `"ORCH E-STOP"` — LOGGER.alert only, not artifact-affecting; confirm it does not leak into an artifact). Fix in `helao/hexagon/` (domain/app); re-run until exit 0. If a fix requires a domain reducer change, keep it behind the existing P1a tests (re-run `pytest helao/hexagon` after).

- [ ] **Step 3: Record**

```bash
echo "P1b2a-Task 7: complete — GM-4 hexagon parity PASS (0 diffs) vs Task-2 legacy golden; estop lifecycle byte-faithful." >> .superpowers/sdd/progress.md
```

---

### Task 8: Gate roll-up — all five green, boundary + suite + pyright clean

**Files:**
- Create: `/home/dan/hexsmoke_captures/P1b2a-gate-summary.txt` (run IDs per scenario)

**Interfaces:**
- Consumes: all five `parity-report.json` candidates; `pytest helao/hexagon`; the AST boundary test; `pyright helao/hexagon`.
- Produces: the recorded P1 artifact-parity gate result (spec §12 P1 gate, first clause).

- [ ] **Step 1: Collect the five parity run IDs and confirm each report is PASS**

Run:
```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python - <<'PY' | tee /home/dan/hexsmoke_captures/P1b2a-gate-summary.txt
import json, sys
scen = {
  "GM-1": "/home/dan/hexsmoke_captures/GM-1_p1b2/parity-report.json",
  "GM-2": "/home/dan/hexsmoke_captures/GM-2_p1b2/parity-report.json",
  "GM-3": "/home/dan/hexsmoke_captures/GM-3_p1b2/parity-report.json",
  "GM-4": "/home/dan/hexsmoke_captures/GM-4_p1b2/parity-report.json",
  "GM-5": "/home/dan/hexsmoke_captures/GM-5_p1b2/parity-report.json",
}
bad = 0
for s, p in scen.items():
    r = json.load(open(p))
    n = r.get("n_diffs", -1)
    rid = r.get("run_id", "?")
    status = "PASS" if n == 0 else f"FAIL({n})"
    print(f"{s}: {status} run_id={rid}")
    bad += (n != 0)
print("GATE:", "PASS" if bad == 0 else f"FAIL ({bad} scenarios with diffs)")
sys.exit(1 if bad else 0)
PY
```
Expected: five `PASS` lines, `GATE: PASS`, exit 0.

- [ ] **Step 2: Re-assert the boundary test + full hexagon suite + pyright**

Run:
```bash
conda run -n helao python -m pytest helao/hexagon -q
conda run -n helao pyright helao/hexagon
```
Expected: pytest all-pass (P1b1's 170 + any parity-fix pins), `pyright helao/hexagon` → 0 errors, 0 warnings.

- [ ] **Step 3: Format any hexagon files changed by parity fixes, then commit the gate summary + ledger**

Run:
```bash
# only if Tasks 3-7 changed any helao/hexagon/*.py:
git diff --name-only | grep '^helao/hexagon/.*\.py$' | xargs -r conda run -n helao black
echo "=== P1b2a GATE PASSED: GM-1..5 hexagon parity 0 diffs; boundary+suite+pyright clean. ===" >> .superpowers/sdd/progress.md
git add .superpowers/sdd/progress.md
# add any hexagon fix files individually (never git add -A; never stage helao/framework or private deploys)
git commit -m "test(hexagon): P1b2a parity gate PASSED — GM-1..5 byte-parity on hexagon path (P1b2a T8)

Hexagon composition (reducer dispatch loop + legacy-wrapped adapters)
reproduces every golden scenario with 0 normalized diffs vs legacy,
including GM-4 estop lifecycle (legacy baseline captured this phase).
Closes the artifact-parity clause of the master-spec P1 gate; the
concurrency suite (§10.3) and §9 behavior tests are P1b2b.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HUFTqzW3UT5jnsm1XfweE5"
```

- [ ] **Step 4: Final whole-branch review**

Dispatch the final code reviewer (Opus) over the branch diff (`git merge-base unstable HEAD`..HEAD): confirm zero legacy edits, no private names, no §5.5/harness-code changes, any hexagon parity fixes are correct and test-pinned, and the gate summary reflects real PASS reports. Then `finishing-a-development-branch`.

---

## Self-Review

**Spec coverage (§12 P1 gate, artifact-parity clause):** GM-1 (T3), GM-2 (T4), GM-3 (T5), GM-5 (T6), GM-4 (T2 legacy baseline + T7 hexagon) — all five covered against legacy goldens; boundary test re-asserted (T8). The concurrency-suite and §9-behavior clauses are explicitly deferred to P1b2b (stated in Goal + T8 commit). ✅

**Placeholder scan:** no "TBD"/"handle edge cases"/"similar to Task N" — every task carries its exact command and expected output; the shared driver is written once (T1) and invoked verbatim per scenario (DRY, per writing-plans' "files that change together"). ✅

**Type/name consistency:** `parity_run.sh <scenario> <config_prefix> <root> <golden_dir> <candidate_dir>` used identically in T1/T3-T7; golden paths `/home/dan/helao_goldens/<S>/run1`, candidates `/home/dan/hexsmoke_captures/<S>_p1b2` consistent throughout; `harness.capture`/`harness.parity`/`kill_group.py` signatures match the P0/P1b1 artifacts verified in the repo. ✅

**Risk note:** the capture tasks are runtime/iterative, not pure-code TDD. Each task's "test" is its parity exit code; a nonzero exit converts the task into a systematic-debugging finding whose fix lands in `helao/hexagon/` only. This is by design — P1b2a is where composition byte-fidelity is actually proven, so surfacing a real diff (especially GM-4) is a success of the gate, not a plan failure.
