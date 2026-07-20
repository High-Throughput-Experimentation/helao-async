# P3e — offline preflight validator + gamry hexagon canary

> Sub-project of P3. The Linux-green half of the per-station cut-over gate; the runtime/at-station half is the hardware gate.

**Outcome (2026-07-18).** Branch `feat/p3e-preflight-validator`.

- `helao/hexagon/preflight.py` — offline preflight validator (spec §8.3, line 234). Given a config prefix, runs the hexagon static gates with disconnected adapters on Linux, no launch: (1) config sanity (unique keys, unique host:port, fast XOR bokeh); (2) shim completeness — every `deployment: hexagon` server has a shim under `helao/deploy/hexagon/servers/<group>/<module>.py`; (3) endpoint-checklist presence — every hexagon ACTION server has a frozen checklist under `helao/hexagon/tests/checklists/<deployment>/` (deployment-aware; skipped for deployments without a checklist set); (4) library collision on the config's `experiment_libraries`+`sequence_libraries`, `allow_shadow: true`-overridable. CLI: `python -m helao.hexagon.preflight <config>`.
- `helao/deploy/hte/configs/gamryhex.yml` — the **gamry-station hexagon canary** (gamry.yml + `deployment: hexagon` on PSTAT + ACTVIS; ports/root/params identical so an on-station golden diff compares like-for-like). gamry.yml stays legacy for rollback.
- `helao/hexagon/tests/test_preflight.py` (8 passed): gamryhex + all P2 goldenhex configs pass; missing-shim / duplicate-host:port / fast-xor-bokeh / library-collision / allow_shadow-override negative cases.

## The remaining gate is HARDWARE (hard stop)

The runtime half of §8.3 — launch each hexagon server, diff its live `/openapi.json` against the frozen checklist — plus station smoke, soak, and the on-station golden diff (§6.6) all require Windows + live instruments (no hte config launches on Linux; even `gamryhex` sim needs the station's COM/Gamry runtime, since GamryDriver constructor-connects). Per-station runbook: preflight (this validator, offline) → launch hexagon composition → runtime openapi diff → smoke → soak → on-station golden diff → sign-off. Canary = the gamry station via `gamryhex`. Rollback = drop the two `deployment: hexagon` keys.
