# Framework — `hte` Production Deployment Migration Plan (DRAFT, GATED)

**Date:** 2026-06-24
**Status:** DRAFT for review. **GATED** — no code written until explicitly approved. The
master rewrite design (§8/§9) gates production `hte` migration as its own cycle behind
the completed `test` pilot. This is that plan.

## 1. Context & why it's gated

Everything the framework needs is proven: the `test` deployment now runs end-to-end on
`helao/framework/` (SP-VIS/SP-ORCH/SP-DEPLOY cycles; suite 1172, live-verified operator).
`hte` is **production, live-hardware** (real potentiostats, motion, IO, spectrometers),
including **Windows-only drivers** (Galil motion/IO via `gclib`, Gamry pstat via
`comtypes`) that cannot run on Linux/CI. A regression here can damage hardware or lose
experiment data. So this migration is **incremental, reversible, hardware-smoke-gated**,
not a big-bang import-swap.

## 2. Surface to migrate

| Category | Count | Notes |
|---|---|---|
| action servers (`servers/action/`) | 22 | import `helao.core.servers.base_api` (22×), `helao.helpers.premodels` (20×), models/sample/error/file/hlostatus, `helao.helpers.executor` |
| drivers (`drivers/`) | 31 files on legacy | incl. Windows-only Galil/Gamry; some pull `helao.core.drivers.{helao_driver,data.sync_driver,data.analysis_driver}`, `helao.helpers.bubble_detection` |
| orchestrator (`servers/orchestrator/async_orch2.py`) | 1 | → framework `deployment: framework` orchestrator entry (exists) |
| operator (`servers/operator/`) | 4 | `standalone_operator` → framework entry (exists); `gcld_operator`(+`_test`) custom; `helao_operator` → framework adapter (exists) |
| visualizers (`servers/visualizer/`) | 15 | generic live/action_visualizer + data_browser → framework (exist); ~12 per-instrument `*_vis.py` (gamry/biologic/pal/spec/tec/etc.) → import-swap |
| configs (`configs/*.yml`) | 21 | add `deployment: framework` to generic apps; per-station |

All migration *patterns* are already proven on `test`: import-swap `helao.core`→
`helao.framework` (SP7), `app/base_api.Base/BaseAPI` action wiring (SP7/SP8), launcher
`deployment: framework` resolution + config-global bridge (SP-DEPLOY-2), framework orch
ZMQ RPC server (fix 88256e0f), generic `app/servers/*` Bokeh entries (SP-DEPLOY-1).

## 3. Framework-readiness gaps to close FIRST (Wave 0)

Before touching `hte`, port/seam the deps `hte` needs that the framework lacks. Audit
every `helao.core`/`helao.helpers` symbol the 22 servers + 31 drivers import and confirm a
framework home; known gaps so far:

- **`helao.helpers.bubble_detection`** — not in framework (2 action servers use it). Port to `support/` or seam.
- **`helao.core.drivers.data.analysis_driver`** — not in framework (1 server). Port or seam.
- **`helao.helpers.executor`** — legacy `Executor` base action servers subclass; confirm the framework `domain/executor.Executor` is API-compatible for hte servers (SP7 test servers used it, but hte servers may use more surface). Reconcile.
- Driver contract: hte drivers implement the `HelaoDriver` ABC (`ports/driver.py` exists). Confirm any per-vendor helpers (range/readz for Gamry, `.dmc` for Galil) need no framework changes (they're data files / vendor code, not core imports).
- Any other symbol the audit surfaces (e.g. `zdeque`, `import_autolibs`, `to_json`, `ws_utils` — several already used as legacy seams; decide port-vs-seam per the established strangler-fig rule).

**Wave 0 deliverable:** a complete dependency-audit table (symbol → framework home or
"port needed" or "legacy seam OK"), and the missing helpers ported with parity tests.
No `hte` edits in Wave 0.

## 4. Migration waves (incremental, reversible)

Each wave is its own spec→plan→branch→merge, validated before the next. **Reversibility:**
the launcher `deployment:` override is per-server, so a single station/server can point at
`framework` OR stay legacy independently — migrate + validate one server/station at a time;
revert by flipping the config key back. Keep legacy `helao/core` intact throughout.

- **Wave 0 — framework-readiness gaps** (§3). Pure framework additions; no hte edits.
- **Wave 1 — drivers.** Import-swap the 31 driver files `helao.core`/`helpers`→framework. Split: (a) Linux-testable sim/data drivers, (b) **Windows-only Galil/Gamry/spec** drivers — these need a Windows station for any smoke; unit-test the import-swap + non-hardware logic on CI, defer hardware smoke to the station bring-up (Wave 5).
- **Wave 2 — action servers.** Import-swap the 22 servers to `app/base_api.Base/BaseAPI` + framework models/executor (SP7 template). Golden-master each server's `makeApp` builds + endpoint surface vs legacy. No config change yet (servers still launched via legacy path until Wave 4 flips configs).
- **Wave 3 — orchestrator + operator + visualizers.** Orchestrator → framework entry (exists). Operator: `standalone_operator`/`helao_operator` → framework (exist); **`gcld_operator`(+`_test`)** is custom — port/repoint it (its own sub-step; inspect its `helao.core` surface). Visualizers: generic hosts + data_browser → framework entries; ~12 per-instrument `*_vis.py` → import-swap to `app/vis`/`adapters/vis_subscriber` base classes (SP-DEPLOY-2 template).
- **Wave 4 — configs.** Per config (21), add `deployment: framework` to the generic apps; verify per-server `action_vis`/`live_vis` resolution (the bokeh launcher keeps `CONFIG["deployment"]`=real deployment for framework hosts — SP-DEPLOY-2). Migrate one config/station at a time.
- **Wave 5 — per-station hardware bring-up & cut-over.** On each real station (Windows where Galil/Gamry live): launch the framework-wired group, run the smoke checklist (§5), parallel-run vs legacy where feasible, then cut the station over. One station at a time; bake-in period before the next.

## 5. Validation strategy

1. **Golden-master (offline, CI):** for each migrated server/driver, byte/structure-compare framework output (action/exp/seq meta, HLO files, endpoint surface) vs legacy on recorded fixtures — the rewrite's standing technique. Extend the existing golden-master suites.
2. **Dependency-audit gate:** Wave 0 audit table must show zero unresolved `helao.core`/`helpers` symbols for the servers/drivers in a given wave before that wave starts.
3. **Boundary + full framework suite** green at every wave (as established).
4. **Hardware smoke checklist (Wave 5, per station):**
   - All servers in the station's config reach ready/healthy (HTTP + RPC reachable).
   - Each driver `connect`/`get_status`/`stop`/`reset`/`disconnect` round-trips against the real instrument.
   - One representative sequence runs end-to-end: enqueue → dispatch → action on hardware → HLO data written → sync to RUNS_*; compare data/meta vs a legacy run of the same sequence.
   - Operator UI: render, queue ops, append, dropdown→params, status WS live (the live-verified test behaviors, now on production).
   - Estop path exercised (operator estop → servers estop) — safety-critical.
   - Galil/Gamry (Windows): motion moves, IO toggles, a pstat technique (e.g. OCV/CV) produces expected data.
5. **Parallel-run (optional, where a station can run both):** run a non-destructive sequence on framework + legacy, diff outputs.
6. **Rollback:** revert the station's config `deployment:` keys to legacy; legacy `helao/core` is untouched, so rollback is a config flip + relaunch.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hardware damage / data loss on a real station | Incremental per-station; estop smoke; parallel/golden-master before cut-over; instant config rollback |
| Windows-only drivers (Galil/Gamry) untestable on CI | Import-swap + non-hardware logic unit-tested on CI; hardware smoke on a Windows station in Wave 5; keep legacy path until smoke passes |
| Hidden `helao.core`/`helpers` symbol with no framework home | Wave 0 dependency-audit gate (zero unresolved before a wave starts) |
| `gcld_operator` custom logic drift | Treat as its own sub-step; inspect + golden-master separately |
| Big-bang temptation under pressure | Hard rule: one server/station at a time, bake-in between; legacy stays intact |
| Framework executor/base_api surface narrower than hte uses | Reconcile in Wave 0 (SP7 covered the common surface; hte may use more) |

## 7. Sign-off gates (human)

- **Gate A:** approve Wave 0 dependency-audit table + close gaps before any hte edit.
- **Gate B:** approve each wave's spec/plan (driver/action/orch-operator-vis/config) before execution.
- **Gate C:** per-station — approve hardware-smoke results before cutting that station over; explicit go/no-go.
- **Gate D:** decommission legacy `helao/core` ONLY after the LAST station is migrated + baked-in (separate, final step — out of this plan).

## 8. Out of scope

- Deleting legacy `helao/core`/`helpers` (only after all stations migrate — Gate D).
- Private deployments (separate repos, their own cycles).
- Behavior/feature changes — this is a relocation onto the framework, parity-preserving.

## 9. Recommended first concrete step

Run **Wave 0**: produce the full dependency-audit table (grep every `helao.core`/
`helao.helpers` symbol across `hte/servers` + `hte/drivers`, map each to a framework home
or flag port-needed), and port the two known gaps (`bubble_detection`, `analysis_driver`)
with parity tests. That's pure framework-side work (no hte edits, no hardware) and
de-risks everything downstream. Approve to proceed.
