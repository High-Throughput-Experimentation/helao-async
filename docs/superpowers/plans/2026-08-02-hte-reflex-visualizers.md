# HTE Reflex Visualizers — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or execute inline. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Port the `hte` deployment's ten Bokeh visualizers to Reflex panels, so an HTE station can run the Reflex UI stack with the same charts it has today.

**Architecture:** Panels are additive files under `helao/deploy/hte/servers/reflex/`, named exactly as the existing `live_vis` / `action_vis` config values (`co2_vis.py`, `gamry_vis.py`, …). `resolve_panel_module` looks them up in `servers/reflex/` while the Bokeh stack keeps using `servers/visualizer/`, so **no station config changes** — adding a `reflex:` server to a config is all it takes. The Bokeh path is untouched.

**Tech stack:** Reflex 0.9.7, the `plots` facade over `xy`, `LiveVisState` / `ActionVisState` mixins.

## Global Constraints

- Panel modules expose `WS_PATH`, `STATE_BASE`, `build(server_key, state_cls)`. `STATE_BASE` **must be a mixin** (`make_panel_state` raises otherwise).
- `rx.foreach` vars need concrete element annotations (`list[list[str]]`); a bare `list` fails the *frontend build*, not import.
- Only `plots.py` and `xy_component.py` may import `xy`.
- Filter non-numeric columns before they reach `plots` — a string takes down the whole chart from inside the render.
- `pull()` is called every tick and returns payloads; `plots.chart(...)` binds **once** in `build()`.
- Run `pyright` on every new file: this suite cannot execute a Reflex handler.
- `black` before every commit.
- The 10 modules are named by 20 tracked hte configs. `tec_vis` and `syringe_vis` exist but **no config in any deployment names them** — out of scope; say so rather than porting dead code.

## File Structure

- `helao/deploy/hte/servers/reflex/__init__.py`
- `helao/deploy/hte/servers/reflex/_live.py` — shared live-panel machinery (rolling mean, series extraction, panel factory)
- `helao/deploy/hte/servers/reflex/{co2,mfc,temp,pressure}_vis.py` — thin, declaring axis labels and which columns carry a rolling mean
- `helao/deploy/hte/servers/reflex/{gamry,biologic,nidaqmx,power_supply,sample,spec}_vis.py` — action panels
- `helao/deploy/hte/tests/test_reflex_live_panels.py`, `test_reflex_action_panels.py`
- `helao/deploy/hte/configs/htereflex.yml` — dev config for verification only; **no station config is edited**

---

### Task 1: Shared live-panel layer + the four live panels

**Files:** create `_live.py`, `co2_vis.py`, `mfc_vis.py`, `temp_vis.py`, `pressure_vis.py`, `test_reflex_live_panels.py`.

All four Bokeh live visualizers share one shape: a time series of N columns against `datetime`, a `FWIN`-point rolling mean for some of them, and a latest-value table. Only the axis label, the column set, and which columns get a mean differ. That goes in `_live.py` once.

**Rolling-mean fidelity:** Bokeh computes `uniform_filter1d` over the whole accumulated vector and streams the tail. The Reflex panel computes it over the visible window snapshot. The two agree everywhere except the leading edge of the window, where `mode="nearest"` has less history to work with. Document it; do not pretend they are identical.

- [ ] **Step 1:** Tests for `rolling_mean` (window shorter than the filter returns the input unchanged, matching Bokeh's `len(mvec) >= FWIN` guard; a full window smooths; an empty array stays empty), for `mean_column_names`, and for `series_for` (non-numeric columns dropped, x column excluded, mean columns appended).
- [ ] **Step 2:** Run, watch fail.
- [ ] **Step 3:** Implement `_live.py`, then the four panels as declarations over it.
- [ ] **Step 4:** Run tests. **Step 5:** pyright, black, commit.

---

### Task 2: Dev config and live verification of the live panels

**Files:** create `helao/deploy/hte/configs/htereflex.yml`; create `helao/core/tests/browser_check_hte_panels.py`.

The config mirrors `goldenreflex`: simulated action servers for the four live panels plus a `reflex:` UI server on two consecutive ports. No station config is touched.

- [ ] **Step 1:** Write the config against hte's simulated drivers.
- [ ] **Step 2:** Rebuild the frontend bundle (stage in `/tmp` — `/mnt/STORAGE` is `noexec`; verify `frontend.zip` exists **before** deleting the old bundle).
- [ ] **Step 3:** Launch and run the browser check: every panel renders, charts paint, and the body changes between samples.
- [ ] **Step 4:** black, commit.

---

### Task 3: Action panels — `nidaqmx_vis` and `power_supply_vis`

The two simplest `ws_data` panels. `ws_data` carries a pickled `DataPackageModel` whose samples sit at `.datamodel.data[key][column]` — a different payload from `ws_live`, already handled by `ingest.NORMALIZERS`.

- [ ] Steps as Task 1: tests for the extraction, then the panels, then pyright/black/commit.

---

### Task 4: Action panels — `gamry_vis` and `biologic_vis`

The two potentiostat panels. Both render multiple technique-dependent plots; read each Bokeh module's `_add_plots` for the trace set before writing the port.

- [ ] Steps as above.

---

### Task 5: Action panels — `spec_vis` and `sample_vis`

`spec_vis` renders spectra; `sample_vis` renders a plate map and can reuse `plots.scatter_map` (the operator's plate tab already does).

- [ ] Steps as above.

---

### Task 6: Verify the action panels live, and document

- [ ] Extend the dev config with the action servers, rebuild the bundle, run the browser check.
- [ ] CLAUDE.md: hte panels resolve by the same config key as the Bokeh visualizers, so no station config changes.
- [ ] black, commit.

## Risks

- **Ten panels is the same order of work as the whole operator port.** Tranches are ordered so the four live panels — which share one shape — land and are verified before the six bespoke action panels start.
- **The action panels are each different.** If one turns out to need a chart shape the `plots` facade lacks, add it to the facade rather than importing `xy` in a panel (a test enforces that).
- **No hardware.** Verification runs against hte's simulated drivers; anything that only appears with a real instrument is a station gate, not a Linux gate.
