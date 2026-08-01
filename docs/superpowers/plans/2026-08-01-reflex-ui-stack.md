# Reflex UI Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Reflex + xy UI stack that runs alongside the existing Bokeh operator/visualizers, opt-in per config entry, with the `test` deployment's three simulator visualizers as the first working slice.

**Architecture:** A new `reflex:` config key launches a single multi-page Reflex app per orchestration group via `reflex_launcher.py`. A process-wide ingest layer opens one WebSocket per action server and writes into numpy ring buffers; per-session Reflex background tasks read snapshots at a user-settable rate and feed a thin plot facade that is the only module importing `xy`. The Bokeh path is untouched.

**Tech Stack:** Python 3.14 (conda env `helao`), Reflex 0.9.x, xy 0.0.x, numpy, FastAPI/uvicorn, pytest, black.

**Spec:** `docs/superpowers/specs/2026-08-01-reflex-ui-design.md`

---

## Global Constraints

- Python 3.14 in the conda env named `helao`. Run every Python/pytest command through `conda run -n helao ...` or an activated env — never the OS python.
- `PYTHONPATH` must point at the repo root (the env config already sets this).
- **`black` (default settings, line length 88) on every changed file as the final step before each `git add`/`git commit`.** No exceptions.
- `pyright` (`pyrightconfig.json`, basic mode) is the authoritative type checker. Never remove an existing `# type: ignore`.
- Dependency pins, added to both `helao_dev_linux-64.yml` and `helao_dev_win-64.yml` under the `pip:` section: `reflex>=0.9.7,<0.10` and `xy==0.0.5`. Both are Apache-2.0.
- Never name a private deployment in a tracked parent-repo file. Refer to them as "private deployments". Only `hte` and `test` may be named.
- Tests run **one file per pytest process** (`python run_tests.py`). Never collect the tree as a single pytest session — it hangs.
- The Bokeh path must remain behaviorally unchanged. Every change to `launch.py`, `config_loader.py`, or `vis_subscriber.py` is additive. Existing tests must stay green.
- xy's ESM render client (`<xy pkg>/static/index.js`, ~411 KB) ships inside the published wheel and is copied into the Reflex assets directory at build time. Nothing fetches from a CDN — lab stations may be airgapped. A source-checkout xy install lacks the asset; xy's own error names the fix.
- Everything in this plan targets the `test` deployment and `helao/core/`. No `hte` files are touched.
- Work on branch `feat/reflex-ui-stack` off `unstable`. Do not push or open a PR; commit locally only.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `helao/core/servers/reflex/__init__.py` | Package marker. Empty. |
| `helao/core/servers/reflex/ringbuffer.py` | `RingBuffer` (numeric columnar) and `RowBuffer` (mixed-type rows). No IO, no Reflex, no xy. |
| `helao/core/servers/reflex/ingest.py` | `IngestStatus`, `WsIngest`, `IngestRegistry`. Owns WebSocket lifetime and message normalization. |
| `helao/core/servers/reflex/xy_component.py` | The hand-written Reflex binding for xy: `XYChart` (NoSSR), `BufferStore`, the buffer route, and the ESM asset copy. Only module importing `xy.widget` / `xy.channel`. Deletable once xy ships `xy.reflex`. |
| `helao/core/servers/reflex/plots.py` | The plot facade: `time_series`, `spectra`, `scatter_map`, `histogram`, `chart`. The **only** module importing xy's charting API. |
| `helao/core/servers/reflex/state.py` | `VisPanelState` base plus `make_panel_state()`, which mints a per-`(module, server_key)` Reflex State subclass. |
| `helao/core/servers/reflex/discovery.py` | Shared deployment search order + panel-module resolution. |
| `helao/core/servers/reflex/app.py` | Builds the `rx.App`, registers routes from config, owns the ingest lifespan. |
| `helao/core/servers/reflex/_app/rxconfig.py` | Reflex project config. Required by the `reflex` CLI. |
| `helao/core/servers/reflex/_app/helao_ui/__init__.py` | Reflex app package marker. |
| `helao/core/servers/reflex/_app/helao_ui/helao_ui.py` | Reflex entrypoint; imports and exposes `app` from `helao.core.servers.reflex.app`. |
| `reflex_launcher.py` | Repo-root launcher, sibling of `bokeh_launcher.py`. Starts the Reflex backend and serves the prebuilt frontend. |
| `helao/deploy/test/servers/reflex/__init__.py` | Package marker. Empty. |
| `helao/deploy/test/servers/reflex/wssim_panel.py` | Reflex panel for the websocket simulator (`ws_live`, time series + latest-value table). |
| `helao/deploy/test/servers/reflex/oersim_panel.py` | Reflex panel for the OER simulator (`ws_data`, action-scoped scatter). |
| `helao/deploy/test/servers/reflex/gpsim_panel.py` | Reflex panel for the GP simulator (`ws_live`, histograms + acquisition table). |
| `helao/deploy/test/configs/goldenreflex.yml` | Test config exercising the Reflex stack against the sims. |
| `helao/core/tests/test_reflex_ringbuffer.py` | Unit tests for `RingBuffer` / `RowBuffer`. |
| `helao/core/tests/test_reflex_ingest.py` | Integration tests for `WsIngest` against a fake WebSocket server. |
| `helao/core/tests/test_reflex_config.py` | Unit tests for `reflex:` config validation and route composition. |
| `helao/core/tests/test_reflex_launcher.py` | Unit tests for bundle resolution in `reflex_launcher.py`. |
| `helao/core/tests/test_reflex_xy_component.py` | Unit tests for the binding: buffer store, frame encoding, HTTP route, asset copy, shim contract. |
| `helao/core/tests/test_reflex_plots.py` | Unit tests for the plot facade. |
| `helao/core/tests/test_reflex_panels.py` | Unit tests for the `test` deployment panel modules. |
| `helao/core/tests/test_reflex_routes_e2e.py` | End-to-end route smoke test. |
| `docs/superpowers/notes/2026-08-01-xy-api-probe.md` | Recorded xy/Reflex API surface from the Task 0 gate. |

**Modified:**

| Path | Change |
|---|---|
| `helao/helpers/config_loader.py:200-221` | Add `reflex: Optional[str]` to `ServerConfig`. |
| `launch.py:542` | Add `"reflex"` to `PIDD.codeKeys`. |
| `launch.py:1129-1148` | Add a `reflex` branch that spawns `reflex_launcher.py`. |
| `launch.py:915-918` | Reserve `port + 1` for Reflex servers in the host:port uniqueness check. |
| `launch.py:1218-1240` | Map Reflex servers to their loaded-modules snapshot (same path as bokeh). |
| `helao/core/servers/vis_subscriber.py:60-88` | Delete `_deployment_search_order`; import the shared one from `discovery.py`. |
| `helao_dev_linux-64.yml`, `helao_dev_win-64.yml` | Add the `reflex` and `xy` pip pins. |
| `.gitignore` | Ignore the exported frontend bundle directory. |
| `CLAUDE.md` | Document the `reflex:` config key, `reflex_launcher.py`, and the bundle build command. |

**Deviations from the spec, deliberate:**

1. The spec puts `RingBuffer`, `WsIngest`, and `IngestRegistry` in one `ingest.py`. Split: buffers are pure data structures with no IO and belong in their own file so they can be tested and reasoned about without asyncio.
2. The spec's facade signatures take a buffer (`time_series(buf, ...)`). The facade takes plain numpy arrays instead, so it is testable with no ingest layer present.
3. The binding (`xy_component.py`) and the facade (`plots.py`) land as one task rather than two. A facade with no binding renders nothing and a binding with no caller cannot be reviewed, so a reviewer could not meaningfully accept one without the other.
4. The facade is split across two call sites — `plots.<kind>()` returns a `ChartPayload` from a panel's `pull`, and `plots.chart()` binds the component in `build`. The spec describes the facade returning a component directly, which would produce a chart that paints once and never updates, because `build` runs only at page composition.
5. Reflex frontend and backend run on two ports (`port` and `port + 1`). Reflex's production model separates them, and a single-port merge depends on API surface this plan will not assume.

---

## Task 0: Pin dependencies and record the verified xy API

The dependency gate has **already been run** and its outcome is recorded below — you are not re-deciding it. `xy` 0.0.5 and `reflex` 0.9.7 install cleanly into the `helao` env on Python 3.14 with no resolver conflict, and `run_unit_tests.py` still passes with both present.

The gate's decisive finding: **`xy.reflex` does not exist.** xy's own source calls the Reflex adapter planned, unshipped work. HELAO writes that binding itself (spec Decision 7), which is Task 4. What xy *does* ship — and what the binding stands on — is verified below.

Your job in this task is to pin the dependencies and turn the verified findings into the API note that Tasks 4-7 read as their source of truth. Re-run the probe to confirm the environment matches, and record real output.

**Files:**
- Create: `docs/superpowers/notes/2026-08-01-xy-api-probe.md`
- Modify: `helao_dev_linux-64.yml`, `helao_dev_win-64.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: pinned versions in both env files, and a committed API note that Tasks 4-7 read for exact xy call signatures.

### Verified findings (recorded 2026-08-01, `helao` env, Python 3.14.6)

**Versions:** `reflex` 0.9.7, `xy` 0.0.5. Both Apache-2.0.

**`xy.reflex`:** absent. `importlib.util.find_spec("xy.reflex")` returns `None`. Not a naming difference — confirmed against xy's shipped source.

**xy submodules:** `channel`, `channels`, `columns`, `components`, `config`, `dom`, `export`, `facets`, `interaction`, `kernels`, `lod`, `marks`, `plugins`, `pyplot`, `styles`, `styling`, `widget`.

**xy chart breadth at 0.0.5** — wider than the README implies. Marks and chart constructors include: `line`/`line_chart`, `scatter`/`scatter_chart`, `bar`/`bar_chart`, `hist`/`histogram`/`histogram_chart`, `heatmap`/`heatmap_chart`, `contour`/`contour_chart`, `step`/`step_chart`, `stairs`/`stairs_chart`, `area`/`area_chart`, `box`/`box_chart`, `violin`/`violin_chart`, `ecdf`/`ecdf_chart`, `hexbin`/`hexbin_chart`, `errorbar`/`errorbar_chart`, `error_band`, `segments`, `stem`, `sankey`, `pie_chart`, `polar_chart`, `polar_bar_chart`, `radar_chart`, `wind_rose`, `triangle_mesh`, `contour`. Axis/annotation helpers: `x_axis`, `y_axis`, `r_axis`, `theta_axis`, `hline`, `vline`, `x_band`, `y_band`, `label`, `callout`, `legend`, `tooltip`, `colorbar`, `modebar`, `annotations`, `threshold`, `threshold_zone`.

Every chart HELAO's Bokeh visualizers draw has a direct counterpart. In particular `hist` exists, so histograms are native — do **not** fake them with step lines.

**Composition API:** `xy.chart(*children: Component, **props) -> Chart`. Declarative: marks and axes are child components, not method calls on a figure.

**The renderer, which is what makes the binding possible:**

- `xy.widget.bundled_js(which="widget"|"standalone") -> str` reads a bundled client build from the `static/` directory inside the installed xy package. Both files ship in the wheel: `index.js` (ESM, ~411 KB) and `standalone.js` (IIFE, ~411 KB). xy's docstring is explicit that this is versioned and CDN-free for airgapped use.
- `Figure.build_payload_split(px_width: Optional[int] = None) -> tuple[dict, list[memoryview]]` — a data-less JSON spec plus raw per-column binary buffers. xy documents this same split layout as serving both first paint **and streaming append**.
- `xy.channel` exposes the wire protocol: `encode_frame`, `encode_frame_parts`, `decode_frame`, `handle_message`, `FRAME_MAGIC`, `FRAME_VERSION`, `FRAME_HEADER_SIZE`, `FRAME_ALIGNMENT`, `FrameDecodeError`, `FrameEncodeError`, `FrameLimits`, `DEFAULT_FRAME_LIMITS`, `Reply`, `DecodedFrame`, `Selection`, `normalize_window`, `SELECTION_EVENT_ID_LIMIT`, `SELECTION_EVENT_ROW_LIMIT`.
- `xy.widget.FigureWidget` (anywidget) shows the intended contract: traits `spec` (Dict, synced) and `buffers` (Any, synced as raw binary), plus callbacks `on_hover`, `on_click`, `on_brush`, `on_select`, `on_view_change`, `on_animation_start`, `on_animation_end` wired through `ChannelCallbacks` and `handle_message`.

**Reflex 0.9.7 capabilities Tasks 4-10 depend on** — all confirmed present: `rx.data_table`, `rx.card`, `rx.badge`, `rx.cond`, `rx.State`, `App.register_lifespan_task`, `rx.NoSSRComponent`, and `rx.Component`'s `library` / `tag` / `add_imports` / `_get_custom_code` / `is_default` / `lib_dependencies` wrapping surface.

- [ ] **Step 1: Install the two dependencies into the `helao` env**

```bash
conda run -n helao pip install 'reflex>=0.9.7,<0.10' 'xy==0.0.5'
```

Expected: both install with no resolver conflict. If pip reports an incompatibility with an existing pin, **stop and report it** — do not force-install and do not use `--no-deps`.

- [ ] **Step 2: Re-run the probe and capture its output**

Write this to the scratchpad (not the repo) and run it:

```python
# scratchpad/probe_xy.py
import importlib.util as u
import inspect
import pathlib

import reflex as rx
import xy
import xy.channel
import xy.widget

print("reflex", getattr(rx, "__version__", "?"))
print("xy", getattr(xy, "__version__", "?"))
print("xy.reflex spec:", u.find_spec("xy.reflex"))

static = pathlib.Path(xy.widget.__file__).parent / "static"
print("static dir exists:", static.exists())
for f in sorted(static.iterdir()) if static.exists() else []:
    print("  asset:", f.name, f.stat().st_size)

print("chart signature:", inspect.signature(xy.chart))
print("build_payload_split:", inspect.signature(xy._figure.Figure.build_payload_split))
print("bundled_js:", inspect.signature(xy.widget.bundled_js))

# Enumerate rather than spot-check: the note's submodule and chart-breadth
# lists are what Tasks 4-7 call xy by, so they must be derived from real
# output, never transcribed by hand.
import pkgutil

print("SUBMODULES:", ",".join(
    sorted(m.name for m in pkgutil.iter_modules(xy.__path__)
           if not m.name.startswith("_"))))
print("EXPORTS:", ",".join(sorted(n for n in dir(xy) if not n.startswith("_"))))

for name in ("line", "scatter", "bar", "hist", "heatmap", "step", "x_axis", "y_axis"):
    print(f"xy.{name}:", hasattr(xy, name))

for name in ("encode_frame_parts", "decode_frame", "handle_message", "Selection"):
    print(f"xy.channel.{name}:", hasattr(xy.channel, name))

for name in ("data_table", "card", "badge", "cond", "State", "NoSSRComponent"):
    print(f"rx.{name}:", hasattr(rx, name))
print("App.register_lifespan_task:", hasattr(rx.App, "register_lifespan_task"))
```

```bash
conda run -n helao python <scratchpad>/probe_xy.py
```

- [ ] **Step 3: Confirm the environment matches the recorded findings**

Every line of probe output must agree with the "Verified findings" section above. If any disagrees — a different version resolved, a missing `static/` directory, an absent mark — **stop and report the discrepancy**. Do not update the findings to match a surprise; a mismatch means the environment is not what the plan was built against.

The one failure with a documented fix: if `static/index.js` is missing, the install came from a source checkout rather than a published wheel. xy's own error message names the fix (`npm ci && node js/build.mjs`). Report it rather than running that yourself — it needs network access and is a decision, not a step.

- [ ] **Step 4: Write the API note**

Write `docs/superpowers/notes/2026-08-01-xy-api-probe.md`. Start from the "Verified findings" section above — but **regenerate the submodule and chart-breadth lists from the `SUBMODULES:` and `EXPORTS:` lines your own probe just printed**, rather than copying those two lists across. Everything a later task calls xy by must trace to output in this note, not to prose written before it ran. If a regenerated list differs from the findings above, the probe wins: record it and report the difference.

Then add a `## Probe output` section containing the **complete verbatim stdout** from Step 2, and a closing section:

```markdown
## Consequences for the implementation

- There is no `xy.reflex`. `helao/core/servers/reflex/xy_component.py` (Task 4) is the
  HELAO-written binding, built on `bundled_js`, `build_payload_split`, and `xy.channel`.
  Delete it when xy ships its own adapter.
- Histograms are native (`xy.hist`). Do not fake them with step lines.
- The ESM asset ships inside the wheel. The launcher copies it to the frontend build;
  nothing fetches from a CDN, which is what airgapped lab stations need.
- Re-run the probe after any version bump and update this note.
```

No `<...>` placeholders may remain. Every value must be real probe output.

- [ ] **Step 5: Pin the dependencies in both env files**

Add to the `pip:` list in `helao_dev_linux-64.yml` and `helao_dev_win-64.yml`, matching the surrounding indentation:

```yaml
    - reflex>=0.9.7,<0.10
    - xy==0.0.5
```

- [ ] **Step 6: Confirm the existing suite is still green**

```bash
conda run -n helao python run_unit_tests.py
```

Expected: PASS. Installing two pip packages must not disturb the sample-model unit test.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/notes/2026-08-01-xy-api-probe.md helao_dev_linux-64.yml helao_dev_win-64.yml
git commit -m "chore: pin reflex and xy, record verified API surface"
```


## Task 1: RingBuffer and RowBuffer

**Files:**
- Create: `helao/core/servers/reflex/__init__.py`
- Create: `helao/core/servers/reflex/ringbuffer.py`
- Test: `helao/core/tests/test_reflex_ringbuffer.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RingBuffer(columns: list[str], capacity: int = 1_000_000)` with `.append(cols: dict[str, Sequence]) -> None`, `.snapshot(n: int | None = None) -> dict[str, np.ndarray]`, `.ensure_columns(names: Iterable[str]) -> None`, `.clear() -> None`, `.columns -> list[str]`, `.length -> int`, `.capacity -> int`.
  - `RowBuffer(maxlen: int = 200)` with `.append(row: dict) -> None`, `.rows() -> list[dict]`, `.latest() -> dict | None`, `.clear() -> None`, `.__len__()`.

**Design notes for the implementer:**
- `RingBuffer` is **numeric only**, `float64`. Timestamps are stored as epoch seconds (a float), never as `datetime` objects — the plot facade formats the axis. This avoids numpy datetime dtype friction entirely.
- Columns can be added after construction via `ensure_columns`; existing rows get `nan` for the new column. HELAO action servers do not always send every key in the first message.
- A column present in `append` but not in the buffer is added automatically. A column in the buffer but missing from `append` gets `nan` for those rows.
- All appended columns must be the same length; a mismatch raises `ValueError`.
- `RowBuffer` is a separate, deliberately dumb structure for string/mixed-type table data (e.g. the GP simulator's `orchestrator` and `last_acquisition` columns), which has no place in a float64 ring.

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_ringbuffer.py
"""Unit tests for the Reflex UI stack's numeric ring buffer and row buffer."""

import numpy as np
import pytest

from helao.core.servers.reflex.ringbuffer import RingBuffer, RowBuffer


def test_append_then_snapshot_returns_what_went_in():
    buf = RingBuffer(["epoch", "value"], capacity=10)
    buf.append({"epoch": [1.0, 2.0], "value": [10.0, 20.0]})
    snap = buf.snapshot()
    assert list(snap.keys()) == ["epoch", "value"]
    np.testing.assert_allclose(snap["epoch"], [1.0, 2.0])
    np.testing.assert_allclose(snap["value"], [10.0, 20.0])
    assert buf.length == 2


def test_rollover_drops_oldest_rows():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0, 3.0, 4.0, 5.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["v"], [3.0, 4.0, 5.0])
    assert buf.length == 3


def test_snapshot_n_returns_only_the_last_n_rows():
    buf = RingBuffer(["v"], capacity=100)
    buf.append({"v": list(range(10))})
    np.testing.assert_allclose(buf.snapshot(3)["v"], [7.0, 8.0, 9.0])


def test_snapshot_n_larger_than_length_returns_everything():
    buf = RingBuffer(["v"], capacity=100)
    buf.append({"v": [1.0, 2.0]})
    np.testing.assert_allclose(buf.snapshot(50)["v"], [1.0, 2.0])


def test_new_column_backfills_existing_rows_with_nan():
    buf = RingBuffer(["a"], capacity=10)
    buf.append({"a": [1.0, 2.0]})
    buf.append({"a": [3.0], "b": [30.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [1.0, 2.0, 3.0])
    assert np.isnan(snap["b"][0]) and np.isnan(snap["b"][1])
    np.testing.assert_allclose(snap["b"][2:], [30.0])


def test_missing_column_in_append_fills_nan():
    buf = RingBuffer(["a", "b"], capacity=10)
    buf.append({"a": [1.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [1.0])
    assert np.isnan(snap["b"][0])


def test_incremental_appends_wrap_and_keep_the_newest_rows():
    """The split-write path: no single append exceeds capacity here."""
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0]})
    buf.append({"v": [3.0, 4.0]})
    np.testing.assert_allclose(buf.snapshot()["v"], [2.0, 3.0, 4.0])


def test_snapshot_window_spanning_the_wrap_point():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0]})
    buf.append({"v": [3.0, 4.0]})
    np.testing.assert_allclose(buf.snapshot(2)["v"], [3.0, 4.0])


def test_repeated_small_appends_wrapping_more_than_once():
    buf = RingBuffer(["v"], capacity=3)
    for i in range(10):
        buf.append({"v": [float(i)]})
    np.testing.assert_allclose(buf.snapshot()["v"], [7.0, 8.0, 9.0])
    assert buf.length == 3


def test_multi_column_stays_aligned_across_a_wrap():
    buf = RingBuffer(["a", "b"], capacity=3)
    buf.append({"a": [1.0, 2.0], "b": [10.0, 20.0]})
    buf.append({"a": [3.0, 4.0], "b": [30.0, 40.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [2.0, 3.0, 4.0])
    np.testing.assert_allclose(snap["b"], [20.0, 30.0, 40.0])


def test_column_added_after_a_wrap_aligns_with_existing_rows():
    buf = RingBuffer(["a"], capacity=3)
    buf.append({"a": [1.0, 2.0]})
    buf.append({"a": [3.0, 4.0]})  # now wrapped, _start != 0
    buf.append({"a": [5.0], "b": [50.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [3.0, 4.0, 5.0])
    assert np.isnan(snap["b"][0]) and np.isnan(snap["b"][1])
    np.testing.assert_allclose(snap["b"][2:], [50.0])


def test_a_rejected_append_leaves_the_column_set_untouched():
    """Validation precedes mutation: no phantom column from a failed append."""
    buf = RingBuffer(["v"], capacity=5)
    with pytest.raises(ValueError):
        buf.append({"v": [1.0], "bad": ["not a number"]})
    assert buf.columns == ["v"]
    assert buf.length == 0


def test_a_rejected_ragged_append_leaves_the_column_set_untouched():
    buf = RingBuffer(["v"], capacity=5)
    with pytest.raises(ValueError):
        buf.append({"v": [1.0, 2.0], "other": [1.0]})
    assert buf.columns == ["v"]
    assert buf.length == 0


def test_rowbuffer_returns_copies_so_callers_cannot_corrupt_it():
    rows = RowBuffer(maxlen=2)
    rows.append({"i": 1})
    rows.rows()[0]["i"] = 999
    latest = rows.latest()
    assert latest is not None  # narrows Optional for pyright; no ignore needed
    latest["i"] = 999
    assert rows.rows() == [{"i": 1}]


def test_ragged_append_raises():
    buf = RingBuffer(["a", "b"], capacity=10)
    with pytest.raises(ValueError):
        buf.append({"a": [1.0, 2.0], "b": [1.0]})


def test_append_longer_than_capacity_keeps_the_tail():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": list(range(100))})
    np.testing.assert_allclose(buf.snapshot()["v"], [97.0, 98.0, 99.0])


def test_empty_snapshot_returns_empty_arrays_not_none():
    buf = RingBuffer(["v"], capacity=10)
    snap = buf.snapshot()
    assert snap["v"].shape == (0,)


def test_clear_resets_length_but_keeps_columns():
    buf = RingBuffer(["v"], capacity=10)
    buf.append({"v": [1.0]})
    buf.clear()
    assert buf.length == 0
    assert buf.columns == ["v"]


def test_non_numeric_value_raises():
    buf = RingBuffer(["v"], capacity=10)
    with pytest.raises((ValueError, TypeError)):
        buf.append({"v": ["not a number"]})


def test_rowbuffer_keeps_last_maxlen_rows_in_order():
    rows = RowBuffer(maxlen=2)
    rows.append({"i": 1})
    rows.append({"i": 2})
    rows.append({"i": 3})
    assert rows.rows() == [{"i": 2}, {"i": 3}]
    assert rows.latest() == {"i": 3}
    assert len(rows) == 2


def test_rowbuffer_latest_is_none_when_empty():
    assert RowBuffer().latest() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_ringbuffer.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'helao.core.servers.reflex'`.

- [ ] **Step 3: Write the implementation**

```python
# helao/core/servers/reflex/__init__.py
"""Reflex UI stack for HELAO.

Parallel to the Bokeh stack under ``helao/core/servers/vis.py`` and
``vis_subscriber.py``; the two coexist and a station opts in per config entry
via the ``reflex:`` key. See
``docs/superpowers/specs/2026-08-01-reflex-ui-design.md``.
"""
```

```python
# helao/core/servers/reflex/ringbuffer.py
"""Fixed-capacity buffers backing the Reflex UI stack's live plots.

:class:`RingBuffer` is a columnar float64 ring for plot data. Timestamps are
stored as epoch seconds, never as ``datetime`` objects, so the whole buffer is
one homogeneous numeric array and the plot facade owns axis formatting.

:class:`RowBuffer` is the deliberately dumb companion for mixed-type tabular
data (strings, UUIDs, labels) that has no place in a float64 ring.

Neither class performs IO or imports Reflex, so both are testable in isolation.
"""

__all__ = ["RingBuffer", "RowBuffer"]

import collections
from typing import Iterable, Optional, Sequence

import numpy as np


class RingBuffer:
    """Columnar float64 ring buffer with a fixed row capacity.

    Columns may be added after construction; existing rows are backfilled with
    ``nan``. A column known to the buffer but absent from an ``append`` call
    likewise receives ``nan`` for the appended rows, because HELAO action
    servers do not always publish every key in every message.

    Attributes:
        capacity: Maximum number of retained rows. Older rows are dropped.
    """

    def __init__(self, columns: Sequence[str], capacity: int = 1_000_000):
        """Allocate the ring.

        Args:
            columns: Initial column names.
            capacity: Maximum retained rows; must be positive.

        Raises:
            ValueError: If ``capacity`` is not positive.
        """
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self.capacity = int(capacity)
        self._cols: dict[str, np.ndarray] = {}
        self._length = 0
        self._start = 0
        for name in columns:
            self._cols[name] = np.full(self.capacity, np.nan, dtype=np.float64)

    @property
    def columns(self) -> list:
        """Column names in insertion order."""
        return list(self._cols)

    @property
    def length(self) -> int:
        """Number of rows currently retained."""
        return self._length

    def ensure_columns(self, names: Iterable[str]) -> None:
        """Add any missing columns, backfilling existing rows with ``nan``.

        Args:
            names: Column names that must exist after this call.
        """
        for name in names:
            if name not in self._cols:
                self._cols[name] = np.full(self.capacity, np.nan, dtype=np.float64)

    def append(self, cols: dict) -> None:
        """Append rows, dropping the oldest once capacity is exceeded.

        Args:
            cols: Mapping of column name to an equal-length sequence of values.
                Unknown columns are created. Known columns absent from ``cols``
                receive ``nan``.

        Raises:
            ValueError: If the sequences are not all the same length, or a
                value is not coercible to float64. Validation happens before
                any state is touched, so a rejected append leaves the buffer
                exactly as it was — including its column set.
        """
        if not cols:
            return
        lengths = {len(v) for v in cols.values()}
        if len(lengths) != 1:
            raise ValueError(
                f"ragged append: columns have differing lengths {
                    {k: len(v) for k, v in cols.items()}
                }"
            )
        n = lengths.pop()
        if n == 0:
            return

        # Validate and coerce everything BEFORE touching any state. A partial
        # append is worse than a rejected one: without this ordering, a bad
        # value leaves its column registered in the schema forever even though
        # no row was written.
        incoming = {}
        for name, values in cols.items():
            try:
                incoming[name] = np.asarray(values, dtype=np.float64)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"column '{name}' is not numeric: {exc}") from exc

        self.ensure_columns(incoming)

        block = {
            name: incoming.get(name, np.full(n, np.nan, dtype=np.float64))
            for name in self._cols
        }

        # An append larger than capacity can only keep its own tail.
        if n >= self.capacity:
            for name, arr in block.items():
                self._cols[name][:] = arr[-self.capacity :]
            self._length = self.capacity
            self._start = 0
            return

        write_at = (self._start + self._length) % self.capacity
        first = min(n, self.capacity - write_at)
        for name, arr in block.items():
            dest = self._cols[name]
            dest[write_at : write_at + first] = arr[:first]
            if first < n:
                dest[: n - first] = arr[first:]

        overflow = self._length + n - self.capacity
        if overflow > 0:
            self._start = (self._start + overflow) % self.capacity
            self._length = self.capacity
        else:
            self._length += n

    def snapshot(self, n: Optional[int] = None) -> dict:
        """Return the most recent rows as contiguous arrays, oldest first.

        Args:
            n: Number of trailing rows to return. ``None`` returns everything
                retained. Values larger than :attr:`length` return everything.

        Returns:
            ``{column_name: np.ndarray}``. Arrays are copies, safe to hand to
            the plot facade or a Reflex state var.
        """
        take = self._length if n is None else max(0, min(int(n), self._length))
        out = {}
        begin = (self._start + self._length - take) % self.capacity
        for name, dest in self._cols.items():
            if take == 0:
                out[name] = np.empty(0, dtype=np.float64)
            elif begin + take <= self.capacity:
                out[name] = dest[begin : begin + take].copy()
            else:
                head = self.capacity - begin
                out[name] = np.concatenate(
                    (dest[begin:], dest[: take - head])
                )
        return out

    def clear(self) -> None:
        """Drop all rows, keeping the column set."""
        self._length = 0
        self._start = 0
        for arr in self._cols.values():
            arr[:] = np.nan


class RowBuffer:
    """Bounded FIFO of dict rows for mixed-type tabular display.

    Used for table widgets whose columns include strings (server names, sample
    labels, UUIDs) and therefore cannot live in :class:`RingBuffer`.
    """

    def __init__(self, maxlen: int = 200):
        """Allocate the deque.

        Args:
            maxlen: Maximum retained rows.
        """
        self._rows = collections.deque(maxlen=maxlen)

    def append(self, row: dict) -> None:
        """Append one row, dropping the oldest when full."""
        self._rows.append(dict(row))

    def rows(self) -> list:
        """Return copies of the retained rows, oldest first.

        Copies, so a caller mutating a returned row cannot corrupt the buffer —
        matching :meth:`append`, which copies on the way in.
        """
        return [dict(r) for r in self._rows]

    def latest(self):
        """Return a copy of the most recent row, or ``None`` when empty."""
        return dict(self._rows[-1]) if self._rows else None

    def clear(self) -> None:
        """Drop all rows."""
        self._rows.clear()

    def __len__(self) -> int:
        """Number of retained rows."""
        return len(self._rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_ringbuffer.py -v
```

Expected: 21 passed.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/ringbuffer.py helao/core/servers/reflex/__init__.py helao/core/tests/test_reflex_ringbuffer.py
git add helao/core/servers/reflex/__init__.py helao/core/servers/reflex/ringbuffer.py helao/core/tests/test_reflex_ringbuffer.py
git commit -m "feat(reflex): add RingBuffer and RowBuffer for live plot data"
```

---

## Task 2: WsIngest and IngestRegistry

**Files:**
- Create: `helao/core/servers/reflex/ingest.py`
- Test: `helao/core/tests/test_reflex_ingest.py`

**Interfaces:**
- Consumes: `RingBuffer`, `RowBuffer` from Task 1.
- Produces:
  - `normalize(messages: list[dict]) -> tuple[dict[str, list[float]], list[dict]]` — module-level pure function turning HELAO WebSocket payloads into `(numeric_columns, mixed_rows)`.
  - `IngestStatus` dataclass with fields `state: str` (one of `"connecting"`, `"live"`, `"reconnecting"`), `last_epoch: float`, `message_count: int`, `error: str | None`.
  - `WsIngest(host: str, port: int, ws_path: str, *, capacity: int = 1_000_000, row_maxlen: int = 200)` with `.buffer: RingBuffer`, `.rows: RowBuffer`, `.raw: collections.deque`, `.status: IngestStatus`, `.start() -> None`, `async .stop() -> None`.
  - `IngestRegistry(world_cfg: dict)` with `.start() -> None`, `async .stop() -> None`, `.get(server_key: str, ws_path: str) -> WsIngest | None`, `.targets() -> list[tuple[str, str]]`.
  - `set_registry(reg)` / `get_registry()` module-level accessors for the process-wide singleton.

**Design notes for the implementer:**
- A HELAO WebSocket payload is `{datalab: (dataval, epochsec)}`. `normalize` unwraps that shape:
  - `sim_dict` payloads are flattened one level (`{"sim_dict": ({"a": 1, "b": 2}, epoch)}` becomes columns `a` and `b`).
  - A list value extends the column; a scalar appends one element.
  - Every message contributes exactly one `epoch` row value: the maximum `epochsec` seen in that message. This mirrors the existing Bokeh `add_points` behavior in `co2_vis.py` and `wssim_live_vis.py`.
  - Values that will not coerce to float go into the mixed-row dict instead of the numeric columns.
- `WsIngest` wraps the **existing** `helao.helpers.ws_utils.WsSubscriber`, which already reconnects with capped exponential backoff (`ws_utils.py:115-143`). Do not reimplement reconnection. `WsIngest` only tracks the status it can observe: it flips to `"reconnecting"` when no message has arrived for more than `stale_after` seconds (default 10.0) after having been `"live"`.
- `WsIngest.raw` is a bounded deque of the untransformed message batches, for panels whose payloads do not fit the numeric-column model (the GP simulator's per-plate histogram arrays).
- `IngestRegistry` builds one `WsIngest` per `(server_key, ws_path)` found by scanning the config for `live_vis` (→ `ws_live`) and `action_vis` (→ `ws_data`) keys, exactly the keys `mount_visualizers` uses today (`vis_subscriber.py:157-172`).

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_ingest.py
"""Tests for the Reflex UI stack's WebSocket ingest layer."""

import asyncio
import pickle

import numpy as np
import pyzstd
import pytest
import websockets

from helao.core.servers.reflex.ingest import (
    IngestRegistry,
    WsIngest,
    normalize,
)


def test_normalize_unwraps_value_epoch_tuples():
    cols, rows = normalize([{"co2_ppm": (410.0, 100.0)}])
    assert cols["co2_ppm"] == [410.0]
    assert cols["epoch"] == [100.0]


def test_normalize_flattens_sim_dict():
    cols, _ = normalize([{"sim_dict": ({"series_0": 1.0, "series_1": 2.0}, 5.0)}])
    assert cols["series_0"] == [1.0]
    assert cols["series_1"] == [2.0]
    assert cols["epoch"] == [5.0]


def test_normalize_extends_on_list_values():
    cols, _ = normalize([{"v": ([1.0, 2.0, 3.0], 7.0)}])
    assert cols["v"] == [1.0, 2.0, 3.0]


def test_normalize_uses_max_epoch_per_message():
    cols, _ = normalize([{"a": (1.0, 10.0), "b": (2.0, 30.0)}])
    assert cols["epoch"] == [30.0]


def test_normalize_routes_non_numeric_values_to_rows():
    cols, rows = normalize([{"orchestrator": ("ORCH", 1.0), "v": (2.0, 1.0)}])
    assert "orchestrator" not in cols
    assert rows == [{"orchestrator": "ORCH"}]
    assert cols["v"] == [2.0]


def test_normalize_handles_empty_input():
    cols, rows = normalize([])
    assert cols == {}
    assert rows == []


def test_normalize_ignores_malformed_entries():
    cols, _ = normalize([{"bad": "not a tuple", "good": (1.0, 2.0)}])
    assert cols["good"] == [1.0]
    assert "bad" not in cols


def test_normalize_keeps_intermittent_columns_aligned_with_epoch():
    """The defect this guards: a key absent from a message must consume a row.

    Without a per-message fill, `v`'s second value lands on the second message
    that *contains* `v` rather than the third row, and every later sample plots
    against the wrong timestamp.
    """
    import math

    cols, _ = normalize(
        [
            {"v": (1.0, 1.0)},
            {"a": (10.0, 2.0)},
            {"v": (2.0, 3.0), "a": (20.0, 3.0)},
        ]
    )
    assert cols["epoch"] == [1.0, 2.0, 3.0]
    assert cols["v"][0] == 1.0 and math.isnan(cols["v"][1]) and cols["v"][2] == 2.0
    assert math.isnan(cols["a"][0]) and cols["a"][1] == 10.0 and cols["a"][2] == 20.0


def test_normalize_every_column_has_equal_length():
    """RingBuffer.append rejects a ragged block, so this is a hard invariant."""
    cols, _ = normalize(
        [{"v": (1.0, 1.0)}, {"a": (10.0, 2.0)}, {"v": (2.0, 3.0)}]
    )
    assert len({len(c) for c in cols.values()}) == 1


def test_normalize_repeats_the_epoch_across_a_burst():
    """A burst of N samples shares one timestamp; all N rows need it.

    Leaving the trailing rows with a nan epoch would put them at no x position
    at all, since epoch is the plot's x axis.
    """
    cols, _ = normalize([{"burst": ([1.0, 2.0, 3.0], 5.0)}])
    assert cols["burst"] == [1.0, 2.0, 3.0]
    assert cols["epoch"] == [5.0, 5.0, 5.0]


def test_normalize_pads_a_scalar_alongside_a_burst():
    import math

    cols, _ = normalize([{"burst": ([1.0, 2.0, 3.0], 5.0), "one": (9.0, 5.0)}])
    assert cols["one"][0] == 9.0
    assert all(math.isnan(x) for x in cols["one"][1:])
    assert cols["epoch"] == [5.0, 5.0, 5.0]


def test_normalize_a_row_only_message_still_consumes_a_row():
    """A non-numeric-only message advances epoch, so numeric columns must too."""
    import math

    cols, rows = normalize(
        [{"v": (1.0, 1.0)}, {"label": ("abc", 2.0)}, {"v": (3.0, 3.0)}]
    )
    assert cols["epoch"] == [1.0, 2.0, 3.0]
    assert cols["v"][0] == 1.0 and math.isnan(cols["v"][1]) and cols["v"][2] == 3.0
    assert rows == [{"label": "abc"}]


def test_normalize_skips_a_non_dict_message():
    cols, _ = normalize(["not a dict", {"v": (1.0, 1.0)}])
    assert cols["v"] == [1.0]


def test_normalize_skips_a_wrong_arity_payload():
    cols, _ = normalize([{"bad": (1.0, 2.0, 3.0), "good": (4.0, 5.0)}])
    assert "bad" not in cols
    assert cols["good"] == [4.0]


def test_normalize_treats_epoch_zero_as_a_real_timestamp():
    """Truthiness would drop epoch 0.0 while still admitting its values."""
    cols, _ = normalize([{"v": (1.0, 0.0)}])
    assert cols["epoch"] == [0.0]
    assert cols["v"] == [1.0]


@pytest.mark.asyncio
async def test_wsingest_fills_buffer_from_a_live_server():
    async def handler(ws):
        for i in range(5):
            payload = {"v": (float(i), 100.0 + i)}
            await ws.send(pyzstd.compress(pickle.dumps(payload)))
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            for _ in range(200):
                if ing.buffer.length >= 5:
                    break
                await asyncio.sleep(0.02)
            snap = ing.buffer.snapshot()
            np.testing.assert_allclose(snap["v"], [0.0, 1.0, 2.0, 3.0, 4.0])
            assert ing.status.state == "live"
            assert ing.status.message_count >= 5
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_wsingest_recovers_after_the_server_restarts():
    sent = {"n": 0}

    async def handler(ws):
        sent["n"] += 1
        await ws.send(pyzstd.compress(pickle.dumps({"v": (float(sent["n"]), 1.0)})))
        await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            # WsSubscriber backs off 1s after a drop, so allow several seconds
            # for a second connection to land.
            for _ in range(400):
                if ing.buffer.length >= 2:
                    break
                await asyncio.sleep(0.02)
            assert ing.buffer.length >= 2, "subscriber did not reconnect"
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_stop_propagates_a_cancellation_of_stop_itself():
    """Tearing down our own tasks is not a failure; being cancelled is.

    Guards a subtle wrong fix: discriminating on ``task.cancelled()`` cannot
    work here, because ``stop()`` cancels the tasks itself before awaiting them,
    so that flag reads ``True`` no matter who cancelled the caller.
    """
    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.start()

    async def stubborn():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)  # slow to finish cancelling
            raise

    ing._task.cancel()
    ing._task = asyncio.create_task(stubborn())
    await asyncio.sleep(0.05)

    stopper = asyncio.create_task(ing.stop())
    await asyncio.sleep(0.05)  # let stop() reach its await
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert ing._task is None and ing._wss is None


@pytest.mark.asyncio
async def test_wsingest_stop_is_idempotent():
    ing = WsIngest("127.0.0.1", 1, "")
    ing.start()
    await ing.stop()
    await ing.stop()


def test_registry_discovers_targets_from_vis_config_keys():
    cfg = {
        "servers": {
            "SIM": {"host": "127.0.0.1", "port": 8002, "live_vis": "wssim_panel"},
            "OER": {"host": "127.0.0.1", "port": 8003, "action_vis": "oersim_panel"},
            "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        }
    }
    reg = IngestRegistry(cfg)
    assert sorted(reg.targets()) == [("OER", "ws_data"), ("SIM", "ws_live")]


def test_registry_accepts_a_list_of_vis_modules_without_duplicating_targets():
    cfg = {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "live_vis": ["wssim_panel", "gpsim_panel"],
            }
        }
    }
    assert IngestRegistry(cfg).targets() == [("SIM", "ws_live")]


def test_registry_skips_servers_missing_host_or_port():
    cfg = {"servers": {"BAD": {"live_vis": "wssim_panel"}}}
    assert IngestRegistry(cfg).targets() == []


def test_registry_get_returns_none_for_unknown_target():
    reg = IngestRegistry({"servers": {}})
    assert reg.get("NOPE", "ws_live") is None
```

Add `pytest-asyncio` if it is not already a dependency:

```bash
conda run -n helao python -c "import pytest_asyncio; print('present')"
```

If that fails, add `pytest-asyncio` to both env files' `pip:` lists and install it, then include the env files in this task's commit. Also confirm the repo's pytest config sets `asyncio_mode`; if it does not, add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `pyproject.toml`, or decorate with `@pytest.mark.asyncio` as written above (the tests above already carry the marker, so strict mode works either way).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_ingest.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'helao.core.servers.reflex.ingest'`.

- [ ] **Step 3: Write the implementation**

```python
# helao/core/servers/reflex/ingest.py
"""Process-wide WebSocket ingest for the Reflex UI stack.

The Bokeh visualizers open one :class:`~helao.helpers.ws_utils.WsSubscriber`
per browser session per action server, so N open tabs against M servers hold
N x M connections and N x M independent rolling buffers. This module inverts
that: one :class:`WsIngest` per ``(server_key, ws_path)`` for the whole
process, writing into a shared :class:`~helao.core.servers.reflex.ringbuffer.RingBuffer`
that every browser session reads.

The second consequence matters as much as the first. Ingest runs at WebSocket
speed while rendering runs on a per-session timer, so a fast data stream no
longer drags the render loop with it — the coupling that
``VisSubscriber.IOloop_data`` has today, where every batch schedules a document
callback.
"""

__all__ = [
    "IngestStatus",
    "WsIngest",
    "IngestRegistry",
    "normalize",
    "set_registry",
    "get_registry",
]

import asyncio
import collections
import time
from dataclasses import dataclass, field
from typing import Optional

from helao.core.servers.reflex.ringbuffer import RingBuffer, RowBuffer
from helao.helpers import helao_logging as logging
from helao.helpers.ws_utils import WsSubscriber

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Config key -> WebSocket path. Mirrors the mapping the Bokeh
#: ``live_visualizer`` / ``action_visualizer`` apps use via
#: :func:`helao.core.servers.vis_subscriber.mount_visualizers`.
VIS_KEY_TO_WS_PATH = {"live_vis": "ws_live", "action_vis": "ws_data"}


def normalize(messages: list) -> tuple:
    """Turn HELAO WebSocket payloads into numeric columns and mixed rows.

    A payload is ``{datalab: (dataval, epochsec)}``. ``sim_dict`` payloads are
    flattened one level. List values extend a column; scalars append one
    element.

    Row alignment is the whole job here. Every column advances by the same
    number of rows per message — the longest value list in that message, or one
    — with ``nan`` filling any column that message did not carry, and the
    message's epoch repeated across all of its rows. Without that invariant an
    intermittently-published key drifts: its Nth value lands on the Nth message
    *containing* it rather than the Nth row, and the data silently plots against
    the wrong timestamps.

    Values that will not coerce to ``float`` (server names, sample labels,
    status strings) are collected into per-message row dicts instead, because
    :class:`RingBuffer` is float64-only.

    Args:
        messages: Batches drained from a :class:`WsSubscriber`.

    Returns:
        ``(numeric_columns, mixed_rows)``. Every list in ``numeric_columns`` has
        the same length and is positionally aligned with ``epoch``.
        ``mixed_rows`` is one dict per message that carried at least one
        non-numeric value. Malformed entries are skipped.
    """
    cols: dict = {}
    rows: list = []
    emitted = 0  # rows emitted so far, so a new column can be backfilled
    for message in messages:
        if not isinstance(message, dict):
            continue
        latest_epoch = None
        row: dict = {}
        pending: dict = {}
        for datalab, payload in message.items():
            if not isinstance(payload, (tuple, list)) or len(payload) != 2:
                continue
            dataval, epochsec = payload
            try:
                seen = float(epochsec)
                latest_epoch = seen if latest_epoch is None else max(latest_epoch, seen)
            except (TypeError, ValueError):
                pass
            if datalab == "sim_dict" and isinstance(dataval, dict):
                for k, v in dataval.items():
                    pending.setdefault(k, []).append(v)
                continue
            if isinstance(dataval, (list, tuple)):
                pending.setdefault(datalab, []).extend(dataval)
            else:
                pending.setdefault(datalab, []).append(dataval)

        numeric: dict = {}
        for name, values in pending.items():
            try:
                numeric[name] = [float(v) for v in values]
            except (TypeError, ValueError):
                row[name] = values[-1] if len(values) == 1 else values
        if row:
            rows.append(row)
        if not numeric and latest_epoch is None:
            continue

        # Every column advances by the same number of rows for this message.
        # Deferring the fill to a single tail-pad at the end of the batch would
        # silently misalign any key that publishes intermittently: its Nth value
        # would land on the Nth message *containing that key*, not the Nth row.
        row_count = max((len(v) for v in numeric.values()), default=1) or 1

        for name in numeric:
            if name not in cols:
                cols[name] = [float("nan")] * emitted
        if latest_epoch is not None and "epoch" not in cols:
            cols["epoch"] = [float("nan")] * emitted

        for name, column in cols.items():
            if name == "epoch":
                # Every row from one message shares that message's timestamp,
                # so a burst of N samples repeats the epoch N times rather than
                # leaving N-1 rows with no time to plot against.
                stamp = float("nan") if latest_epoch is None else latest_epoch
                column.extend([stamp] * row_count)
            else:
                values = numeric.get(name, [])
                column.extend(values)
                column.extend([float("nan")] * (row_count - len(values)))
        emitted += row_count

    return cols, rows


@dataclass
class IngestStatus:
    """Observable connection state for one ingest target.

    Attributes:
        state: ``"connecting"`` before the first message, ``"live"`` while
            messages arrive, ``"reconnecting"`` once the stream goes stale.
        last_epoch: Wall-clock time of the most recent message batch.
        message_count: Total messages ingested since start.
        error: Most recent error string, or ``None``.
    """

    state: str = "connecting"
    last_epoch: float = 0.0
    message_count: int = 0
    error: Optional[str] = field(default=None)


class WsIngest:
    """One process-wide subscriber feeding a ring buffer for one endpoint.

    Reconnection is not implemented here:
    :class:`~helao.helpers.ws_utils.WsSubscriber` already reconnects
    indefinitely with capped exponential backoff. This class owns the drain
    loop, normalization, and the observable :class:`IngestStatus`.

    Attributes:
        buffer: Numeric ring buffer of everything normalized from the stream.
        rows: Mixed-type rows (strings, labels) from the same stream.
        raw: Bounded deque of untransformed message batches, for panels whose
            payloads do not fit the numeric-column model.
        status: Current :class:`IngestStatus`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        ws_path: str,
        *,
        capacity: int = 1_000_000,
        row_maxlen: int = 200,
        raw_maxlen: int = 50,
        drain_interval: float = 0.05,
        stale_after: float = 10.0,
    ):
        """Configure the ingest target without opening a connection.

        Args:
            host: Action server hostname.
            port: Action server port.
            ws_path: ``ws_live`` or ``ws_data``.
            capacity: Ring buffer row capacity.
            row_maxlen: Retained mixed-type rows.
            raw_maxlen: Retained raw message batches.
            drain_interval: Seconds between subscriber drains.
            stale_after: Seconds without a message before the status flips to
                ``"reconnecting"``.
        """
        self.host = host
        self.port = port
        self.ws_path = ws_path
        self.url = f"ws://{host}:{port}/{ws_path}"
        self.buffer = RingBuffer([], capacity=capacity)
        self.rows = RowBuffer(maxlen=row_maxlen)
        self.raw = collections.deque(maxlen=raw_maxlen)
        self.status = IngestStatus()
        self._drain_interval = drain_interval
        self._stale_after = stale_after
        self._wss: Optional[WsSubscriber] = None
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Open the subscriber and launch the drain loop. Idempotent."""
        if self._task is not None:
            return
        self._wss = WsSubscriber(self.host, self.port, self.ws_path)
        self._task = asyncio.create_task(self._drain_loop())
        LOGGER.info(f"reflex ingest subscribing to {self.url}")

    async def stop(self) -> None:
        """Cancel the drain loop and the underlying subscriber. Idempotent.

        ``gather(..., return_exceptions=True)`` returns each task's own
        ``CancelledError`` as a result instead of raising it, so the teardown
        this method exists to perform does not itself look like a failure. An
        outer cancellation -- something cancelling *this* coroutine while it is
        suspended, e.g. ``asyncio.wait_for(ingest.stop(), timeout=...)`` --
        still raises at the ``await`` and propagates, which is what the caller
        asked for. The ``finally`` clears the handles either way, so teardown
        completes on both paths.

        Inspecting ``task.cancelled()`` to tell the two cases apart does not
        work: this method always cancels the tasks itself first, so by the time
        the flag is readable it is ``True`` regardless of who cancelled the
        caller.
        """
        tasks = [
            task
            for task in (self._task, getattr(self._wss, "subscriber_task", None))
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._task = None
            self._wss = None

    async def _drain_loop(self) -> None:
        """Drain the subscriber, normalize, and append. Runs until cancelled."""
        while True:
            try:
                messages = await self._wss.read_messages()
                if messages:
                    self.raw.append(messages)
                    cols, rows = normalize(messages)
                    if cols:
                        self.buffer.append(cols)
                    for row in rows:
                        self.rows.append(row)
                    self.status.state = "live"
                    self.status.last_epoch = time.time()
                    self.status.message_count += len(messages)
                    self.status.error = None
                elif (
                    self.status.state == "live"
                    and time.time() - self.status.last_epoch > self._stale_after
                ):
                    self.status.state = "reconnecting"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # normalization/append failures
                self.status.error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(f"reflex ingest error on {self.url}: {exc}")
            await asyncio.sleep(self._drain_interval)


class IngestRegistry:
    """Process-wide map of ``(server_key, ws_path)`` to a single :class:`WsIngest`.

    Targets are discovered from the same ``live_vis`` / ``action_vis`` config
    keys the Bokeh stack uses, so a config that already declares visualizers
    needs no new keys to feed the Reflex stack.
    """

    def __init__(self, world_cfg: dict):
        """Discover targets from ``world_cfg`` without connecting.

        Args:
            world_cfg: The loaded HELAO world config.
        """
        self.world_cfg = world_cfg or {}
        self._ingests: dict = {}
        self._targets: list = []
        for server_key, server_cfg in (self.world_cfg.get("servers") or {}).items():
            if not isinstance(server_cfg, dict):
                continue
            host = server_cfg.get("host")
            port = server_cfg.get("port")
            if host is None or port is None:
                continue
            for vis_key, ws_path in VIS_KEY_TO_WS_PATH.items():
                if not server_cfg.get(vis_key):
                    continue
                target = (server_key, ws_path)
                if target not in self._targets:
                    self._targets.append(target)

    def targets(self) -> list:
        """Return the discovered ``(server_key, ws_path)`` pairs."""
        return list(self._targets)

    def start(self) -> None:
        """Create and start one :class:`WsIngest` per target. Idempotent."""
        servers = self.world_cfg.get("servers") or {}
        for server_key, ws_path in self._targets:
            if (server_key, ws_path) in self._ingests:
                continue
            cfg = servers[server_key]
            ingest = WsIngest(cfg["host"], cfg["port"], ws_path)
            ingest.start()
            self._ingests[(server_key, ws_path)] = ingest

    async def stop(self) -> None:
        """Stop every ingest and clear the map."""
        for ingest in list(self._ingests.values()):
            await ingest.stop()
        self._ingests.clear()

    def get(self, server_key: str, ws_path: str):
        """Return the ingest for a target, or ``None`` if not started."""
        return self._ingests.get((server_key, ws_path))


_REGISTRY: Optional[IngestRegistry] = None


def set_registry(registry) -> None:
    """Install the process-wide registry. Called once from ``app.py``."""
    global _REGISTRY
    _REGISTRY = registry


def get_registry():
    """Return the process-wide registry, or ``None`` before startup."""
    return _REGISTRY
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_ingest.py -v
```

Expected: 23 passed. The reconnect test spends about a second in the `WsSubscriber` backoff before its second connection lands; that wait is the point of the test, not incidental.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/ingest.py helao/core/tests/test_reflex_ingest.py
git add helao/core/servers/reflex/ingest.py helao/core/tests/test_reflex_ingest.py
git commit -m "feat(reflex): add process-wide WebSocket ingest with ring buffers"
```

If `pytest-asyncio` had to be added, include the two env files and `pyproject.toml` in this commit.

---

## Task 3: Config validation for the `reflex:` key

**Files:**
- Modify: `helao/helpers/config_loader.py:200-221`
- Modify: `launch.py:542`, `launch.py:915-918`
- Create: `helao/core/servers/reflex/discovery.py`
- Modify: `helao/core/servers/vis_subscriber.py:60-88`
- Test: `helao/core/tests/test_reflex_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ServerConfig.reflex: Optional[str]`.
  - `PIDD.codeKeys == ("fast", "bokeh", "reflex")`.
  - `helao.core.servers.reflex.discovery.deployment_search_order() -> list[str]` and `resolve_panel_module(module_name: str)` returning the imported module.
  - `helao.core.servers.reflex.discovery.reserved_addresses(server_cfg: dict) -> list[str]` returning `["host:port"]` for `fast`/`bokeh` servers and `["host:port", "host:port+1"]` for `reflex` servers.

**Design notes for the implementer:**
- A Reflex server occupies **two** ports: `port` serves the static frontend, `port + 1` is the Reflex backend. `validateConfig` must therefore reject a config where another server's port collides with a Reflex server's `port + 1`. That is what `reserved_addresses` is for.
- `_deployment_search_order` in `vis_subscriber.py:60-88` is moved verbatim into `discovery.py` and re-exported, so the Bokeh and Reflex paths cannot drift. `vis_subscriber.py` keeps a module-level alias so nothing that imports it breaks.

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_config.py
"""Tests for `reflex:` config validation and shared module discovery."""

import pytest

from helao.helpers.config_loader import ServerConfig


def _pidd():
    """Return a stand-in carrying only the attributes validateConfig reads."""

    class _P:
        reqKeys = ("host", "port", "group")
        codeKeys = ("fast", "bokeh", "reflex")

    return _P()


def test_serverconfig_accepts_a_reflex_key():
    cfg = ServerConfig(host="127.0.0.1", port=5010, group="visualizer", reflex="helao_ui")
    assert cfg.reflex == "helao_ui"
    assert cfg.fast is None and cfg.bokeh is None


def test_serverconfig_reflex_defaults_to_none():
    assert ServerConfig(host="h", port=1, group="action").reflex is None


def test_pidd_codekeys_include_reflex():
    import inspect

    from launch import Pidd

    src = inspect.getsource(Pidd.__init__)
    assert '"reflex"' in src or "'reflex'" in src


def test_validate_rejects_two_code_keys_including_reflex():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
                "bokeh": "live_visualizer",
            }
        }
    }
    assert validateConfig(_pidd(), conf, ".") is False


def test_validate_accepts_a_reflex_only_server():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
            }
        }
    }
    assert validateConfig(_pidd(), conf, ".") is True


def test_validate_rejects_a_server_colliding_with_the_reflex_backend_port():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 5011,
                "group": "action",
                "fast": "ws_simulator",
            },
        }
    }
    assert validateConfig(_pidd(), conf, ".") is False


def test_reserved_addresses_claims_two_ports_for_reflex():
    from helao.core.servers.reflex.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"}
    ) == ["127.0.0.1:5010", "127.0.0.1:5011"]


def test_reserved_addresses_claims_one_port_for_bokeh():
    from helao.core.servers.reflex.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5002, "bokeh": "live_visualizer"}
    ) == ["127.0.0.1:5002"]


def test_discovery_search_order_puts_configured_deployment_first():
    from helao.helpers import config_loader
    from helao.core.servers.reflex.discovery import deployment_search_order

    saved = config_loader.CONFIG
    try:
        config_loader.CONFIG = {"deployment": "test"}
        order = deployment_search_order()
        assert order[0] == "test"
        assert "hte" in order
    finally:
        config_loader.CONFIG = saved


def test_vis_subscriber_reuses_the_shared_search_order():
    from helao.core.servers import vis_subscriber
    from helao.core.servers.reflex import discovery

    assert vis_subscriber._deployment_search_order is discovery.deployment_search_order


def test_resolve_panel_module_raises_a_clear_error_for_an_unknown_module():
    from helao.core.servers.reflex.discovery import resolve_panel_module

    with pytest.raises(ModuleNotFoundError) as exc:
        resolve_panel_module("no_such_panel_module")
    assert "no_such_panel_module" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_config.py -v
```

Expected: failures on `reflex` not being a `ServerConfig` field and on the missing `discovery` module.

- [ ] **Step 3a: Add the `reflex` field to `ServerConfig`**

In `helao/helpers/config_loader.py`, change the `ServerConfig` docstring attribute list and fields:

```python
        fast: Module name under ``servers/<group>/`` for FastAPI servers.
        bokeh: Module name under ``servers/<group>/`` for Bokeh servers.
        reflex: Reflex app module name for the Reflex UI stack. A Reflex
            server occupies two ports: ``port`` serves the static frontend and
            ``port + 1`` is the Reflex backend.
```

```python
    fast: Optional[str] = None
    bokeh: Optional[str] = None
    reflex: Optional[str] = None
```

- [ ] **Step 3b: Create the shared discovery module**

```python
# helao/core/servers/reflex/discovery.py
"""Deployment module resolution shared by the Bokeh and Reflex UI stacks.

``vis_subscriber`` originally owned the deployment search order. It lives here
now so both stacks resolve deployment modules identically and cannot drift;
``vis_subscriber`` imports it back under its original private name.
"""

__all__ = [
    "deployment_search_order",
    "resolve_panel_module",
    "reserved_addresses",
    "PANEL_SUBPACKAGE",
]

import os
from functools import lru_cache
from importlib import import_module
from importlib import util as importlib_util

from helao.helpers import config_loader

#: Subpackage under ``helao/deploy/<deployment>/servers/`` holding Reflex panels.
PANEL_SUBPACKAGE = "reflex"


def deployment_search_order() -> list:
    """Return the deployment names to search when resolving a UI module.

    The configured deployment (``CONFIG["deployment"]``) is tried first so a
    deployment can override a shared module, then ``hte`` as the canonical home
    of the generic visualizers, then any remaining deployment that ships a
    ``servers/visualizer`` package (sorted for determinism).

    Returns:
        list: Ordered, de-duplicated deployment directory names.
    """
    order = []
    cfg = config_loader.CONFIG or {}
    current = cfg.get("deployment")
    if current:
        order.append(current)
    if "hte" not in order:
        order.append("hte")
    deploy_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "deploy",
    )
    if os.path.isdir(deploy_root):
        for name in sorted(os.listdir(deploy_root)):
            if name in order:
                continue
            if os.path.isdir(os.path.join(deploy_root, name, "servers", "visualizer")):
                order.append(name)
    return order


@lru_cache(maxsize=None)
def resolve_panel_module(module_name: str):
    """Import a Reflex panel module by short name, searching deployments.

    Args:
        module_name: Short module name from a server's ``live_vis`` /
            ``action_vis`` config key (e.g. ``"wssim_panel"``).

    Returns:
        The imported module.

    Raises:
        ModuleNotFoundError: If no deployment provides ``module_name``.
    """
    tried = []
    for deployment in deployment_search_order():
        modpath = (
            f"helao.deploy.{deployment}.servers.{PANEL_SUBPACKAGE}.{module_name}"
        )
        tried.append(modpath)
        try:
            spec = importlib_util.find_spec(modpath)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            continue
        return import_module(modpath)
    raise ModuleNotFoundError(
        f"could not locate Reflex panel module '{module_name}' in any "
        f"deployment; tried: {tried}"
    )


def reserved_addresses(server_cfg: dict) -> list:
    """Return every ``host:port`` a server entry occupies.

    A Reflex server occupies two consecutive ports (static frontend, then
    backend), so uniqueness checks must account for both.

    Args:
        server_cfg: One entry of the config's ``servers:`` mapping.

    Returns:
        list: ``"host:port"`` strings claimed by this server.
    """
    host = server_cfg.get("host")
    port = server_cfg.get("port")
    if host is None or port is None:
        return []
    addrs = [f"{host}:{port}"]
    if server_cfg.get("reflex"):
        addrs.append(f"{host}:{int(port) + 1}")
    return addrs
```

- [ ] **Step 3c: Point `vis_subscriber` at the shared implementation**

In `helao/core/servers/vis_subscriber.py`, delete the entire `_deployment_search_order` function body (lines 60-88) and replace it with an import alias placed immediately after the existing `from helao.helpers import config_loader` import:

```python
from helao.core.servers.reflex.discovery import (
    deployment_search_order as _deployment_search_order,
)
```

Leave every call site untouched — `import_vis_class` already calls `_deployment_search_order()`.

- [ ] **Step 3d: Teach `launch.py` about the `reflex` code key**

At `launch.py:542`:

```python
        self.codeKeys = ("fast", "bokeh", "reflex")
```

At `launch.py:915-918`, replace the address-uniqueness block:

```python
    serverAddrs = []
    for d in confDict["servers"].values():
        serverAddrs.extend(reserved_addresses(d))
    if len(serverAddrs) != len(set(serverAddrs)):
        LAUNCH_LOGGER.info("Server host:port locations are not unique.")
        return False
```

Add the import near the other `helao` imports at the top of `launch.py`:

```python
from helao.core.servers.reflex.discovery import reserved_addresses
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_config.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Confirm nothing regressed in the Bokeh path**

```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python -m pytest helao/hexagon/tests/test_vis_gate_config.py helao/hexagon/tests/test_hte_vis_import.py -v
conda run -n helao python -m pytest helao/core/tests/test_launch_pid_verify.py -v
```

Expected: all PASS. If `test_launch_pid_verify.py` asserts on `codeKeys`, update its expectation to the three-tuple — that is a correct consequence of this change, not a regression.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/helpers/config_loader.py launch.py helao/core/servers/reflex/discovery.py helao/core/servers/vis_subscriber.py helao/core/tests/test_reflex_config.py
git add helao/helpers/config_loader.py launch.py helao/core/servers/reflex/discovery.py helao/core/servers/vis_subscriber.py helao/core/tests/test_reflex_config.py
git commit -m "feat(reflex): add reflex config key and share deployment discovery"
```

---

## Task 4: The xy Reflex binding and plot facade

xy ships no Reflex adapter, so HELAO writes one (spec Decision 7). The binding and the facade are one deliverable in two files — a facade with no binding renders nothing, and a binding with no facade has no callers — so they land together.

**Files:**
- Create: `helao/core/servers/reflex/xy_component.py`
- Create: `helao/core/servers/reflex/plots.py`
- Test: `helao/core/tests/test_reflex_xy_component.py`
- Test: `helao/core/tests/test_reflex_plots.py`

**Interfaces:**
- Consumes: the verified xy API recorded in `docs/superpowers/notes/2026-08-01-xy-api-probe.md` (Task 0), and `RingBuffer` (Task 1).
- Produces:
  - `xy_component.XYChart` — an `rx.NoSSRComponent` with props `spec: rx.Var[dict]`, `buffer_url: rx.Var[str]`, `height: rx.Var[str]`, and event `on_select`.
  - `xy_component.xy_chart(**props) -> XYChart` — the create helper.
  - `xy_component.BufferStore` — process-wide `panel_id -> (version, list[memoryview])` map, with `put(panel_id, version, buffers)`, `get(panel_id, version)`, `drop(panel_id)`.
  - `xy_component.encode_buffers(buffers) -> bytes` — xy-native frame encoding via `xy.channel.encode_frame_parts`.
  - `xy_component.make_buffer_router() -> fastapi.APIRouter` — serves `GET /xy/buffers/{panel_id}`.
  - `xy_component.copy_client_asset(dest_dir) -> str` — copies xy's shipped ESM into the Reflex assets directory.
  - `plots.ChartPayload` — frozen dataclass `(spec: dict, buffer_url: str)`.
  - `plots.time_series`, `plots.spectra`, `plots.scatter_map`, `plots.histogram` — each `(arrays..., panel_id, version, **opts) -> ChartPayload`. Called from a panel's `pull`.
  - `plots.chart(spec_var, url_var, *, height=320, on_select=None) -> rx.Component` — called from a panel's `build`.
  - `plots.PlotBackendError`, `plots.STORE`.

**The two-call split matters.** A panel's `build` runs once, when the page is composed; its `pull` runs on every render tick. So the facade is split: `build` calls `plots.chart(...)` to bind the component to two Reflex state vars, and `pull` calls `plots.time_series(...)` to compute a fresh `ChartPayload` and assign it into those vars. Data flows through state; the component is constructed once. Getting this backwards — calling `time_series` in `build` — produces a chart that renders once and never updates.

**Design notes for the implementer:**

- `plots.py` is the only module importing `xy`'s charting API; `xy_component.py` is the only module importing `xy.widget` / `xy.channel`. Nothing else in the repo may import `xy` at all — Task 6 has a test enforcing this.
- **The ESM contract, verified from the shipped bundle.** `xy/static/index.js` exports `render({model, el}) -> cleanup`, `renderStandalone(el, spec, buffers)`, `decodeFrame`, and `MARK_KINDS`. `render` drives everything through an anywidget-style `model` requiring exactly six members: `get(name)`, `send(msg)`, `on(event, cb)`, `off(event, cb)` (optional), and it listens for `"change:spec"`, `"change:buffers"`, and `"msg:custom"`. The React shim implements that surface — it is a stub object, not a dependency on anywidget.
- **Streaming append is a first-class path in the bundle**, not something to emulate: set `spec.append = {seq, affected}`, swap `buffers`, and fire `change:spec` / `change:buffers`. The bundle calls `_applyAppend` and updates in place instead of re-rendering. The shim must therefore fire both change events and must not tear down the view on data updates.
- **Bulk data does not travel through Reflex state** (spec Decision 8). `spec` is small JSON and rides a Reflex var; column buffers are fetched by the browser from `GET /xy/buffers/{panel_id}?v={version}`, encoded with xy's own `encode_frame_parts` and decoded in the browser with the bundle's exported `decodeFrame`. No HELAO-invented wire format.
- The buffer route is mounted through `rx.App(api_transformer=...)` — Reflex 0.9.7 exposes no public `app.api` before build, and `_api` is private. Task 6 does the wiring; this task supplies the router.
- `BufferStore` keyed by `(panel_id, version)` returns 404 for an unknown panel or a stale version. A refetch racing a panel teardown must leave the last good frame on screen rather than blanking it.

- [ ] **Step 1: Write the failing binding tests**

```python
# helao/core/tests/test_reflex_xy_component.py
"""Tests for the hand-written xy Reflex binding.

xy 0.0.5 ships no `xy.reflex`, so HELAO supplies the binding. These tests cover
the Python half — buffer storage, xy-native frame encoding, the HTTP route, and
asset copying — plus the JavaScript controller, executed under Node.

Nothing here can exercise WebGL; rendering is proven by the browser check at the
end of the plan. But the controller holds the shim logic that can actually be
wrong, so it is run rather than string-matched.
"""

import json
import os
import shutil
import subprocess
import tempfile

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helao.core.servers.reflex import xy_component as xc


def _bufs():
    return [
        memoryview(np.arange(4, dtype=np.float64).tobytes()),
        memoryview(np.arange(4, dtype=np.float32).tobytes()),
    ]


def test_encode_buffers_roundtrips_through_xy_channel():
    import xy.channel

    payload = xc.encode_buffers(_bufs())
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) > 0
    # Frames carry xy's own magic, so the browser decodes them with the
    # bundle's exported decodeFrame rather than anything HELAO invented.
    assert payload[: len(xy.channel.FRAME_MAGIC)] == bytes(xy.channel.FRAME_MAGIC)


def test_encode_buffers_handles_an_empty_list():
    assert isinstance(xc.encode_buffers([]), (bytes, bytearray))


def test_store_returns_what_was_put():
    store = xc.BufferStore()
    bufs = _bufs()
    store.put("panel-a", 3, bufs)
    assert store.get("panel-a", 3) is not None


def test_store_returns_none_for_a_stale_version():
    store = xc.BufferStore()
    store.put("panel-a", 3, _bufs())
    assert store.get("panel-a", 2) is None


def test_store_returns_none_for_an_unknown_panel():
    assert xc.BufferStore().get("nope", 1) is None


def test_store_put_replaces_the_previous_version():
    store = xc.BufferStore()
    store.put("panel-a", 1, _bufs())
    store.put("panel-a", 2, _bufs())
    assert store.get("panel-a", 1) is None
    assert store.get("panel-a", 2) is not None


def test_store_drop_removes_the_panel():
    store = xc.BufferStore()
    store.put("panel-a", 1, _bufs())
    store.drop("panel-a")
    assert store.get("panel-a", 1) is None


def _client(store):
    api = FastAPI()
    api.include_router(xc.make_buffer_router(store))
    return TestClient(api)


def test_route_serves_octet_stream_for_a_live_panel():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    resp = _client(store).get("/xy/buffers/panel-a?v=7")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert len(resp.content) > 0


def test_route_404s_on_an_unknown_panel():
    assert _client(xc.BufferStore()).get("/xy/buffers/ghost?v=1").status_code == 404


def test_route_404s_on_a_stale_version():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    assert _client(store).get("/xy/buffers/panel-a?v=6").status_code == 404


def test_route_requires_the_version_query_param():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    assert _client(store).get("/xy/buffers/panel-a").status_code == 422


def test_copy_client_asset_places_the_esm(tmp_path):
    dest = xc.copy_client_asset(str(tmp_path))
    assert dest.endswith(xc.CLIENT_ASSET_NAME)
    written = tmp_path / xc.CLIENT_ASSET_NAME
    assert written.exists()
    # The real bundle is ~400 KB; a truncated copy is a silent disaster.
    assert written.stat().st_size > 100_000


def test_copy_client_asset_is_idempotent(tmp_path):
    first = xc.copy_client_asset(str(tmp_path))
    second = xc.copy_client_asset(str(tmp_path))
    assert first == second


def test_xy_chart_builds_a_component():
    comp = xc.xy_chart(spec={}, buffer_url="/xy/buffers/x?v=0", height="320px")
    assert comp is not None


def test_xy_chart_is_client_only():
    """A WebGL canvas cannot server-side render."""
    import reflex as rx

    assert issubclass(xc.XYChart, rx.NoSSRComponent)


def test_shim_declares_the_six_model_members_the_bundle_requires():
    """The bundle's render({model, el}) drives everything through these.

    A substring check only proves the tokens are present, so it is a smoke test,
    not a guarantee -- the behavioral tests below are what actually constrain the
    controller.
    """
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    for member in ("get", "send", "on", "off", "change:spec", "change:buffers"):
        assert member in code, f"shim is missing '{member}'"


def test_shim_references_the_bundles_exported_entry_points():
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    assert "render" in code
    assert "decodeFrame" in code


# --- Behavioral tests for the shim controller -------------------------------
#
# The controller holds every piece of shim logic that can be wrong, with no JSX
# and no React, precisely so a JS runtime can execute it here. Substring
# assertions previously let a stale-closure bug ship: `refetch` captured the
# mount-time URL, so a chart painted once and then silently froze. These run the
# real code instead.

_JS_RUNTIME = shutil.which("node")

_HARNESS = """
%(controller)s

const calls = [];
globalThis.fetch = async (url) => {
  calls.push(url);
  if (url === "/fail") return { ok: false };
  return { ok: true, arrayBuffer: async () => new ArrayBuffer(8) };
};

const events = [];
const st = createController({ spec: {v: 1}, onSelect: null });
st.model.on("change:spec", () => events.push("spec"));
st.model.on("change:buffers", () => events.push("buffers"));

const out = {};
(async () => {
  // Queued before the bundle is ready, then flushed on markReady.
  await st.refetch("/xy/buffers/p?v=1");
  out.queuedWhileNotReady = calls.length === 0 && st.pending === true;
  st.markReady();
  await new Promise((r) => setTimeout(r, 0));
  out.flushedPendingUrl = calls[0];

  // The bug this guards: a later call must use the URL it is given.
  await st.refetch("/xy/buffers/p?v=2");
  await st.refetch("/xy/buffers/p?v=3");
  out.lastFetched = calls[calls.length - 1];
  out.allUrls = calls.slice();

  // Both change events fire per successful refetch (the in-place append path).
  out.events = events.slice();

  // A failed fetch keeps the previous frame rather than blanking it.
  const before = st.buffers;
  await st.refetch("/fail");
  out.keptFrameOnFailure = st.buffers === before;

  console.log(JSON.stringify(out));
})();
"""


def _run_controller_harness():
    """Execute the shim controller under Node and return its result dict."""
    controller = xc._SHIM_CONTROLLER_JS
    script = _HARNESS % {"controller": controller}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "harness.mjs")
        with open(path, "w") as fh:
            fh.write(script)
        proc = subprocess.run(
            [_JS_RUNTIME, path], capture_output=True, text=True, timeout=60
        )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_refetch_uses_the_url_it_is_given_not_a_captured_one():
    """The regression guard: a captured URL freezes the chart after one paint.

    `version` changes every render tick and BufferStore keeps only the newest
    version, so a stale URL 404s, the !ok guard holds the previous frame, and
    updates stop silently.
    """
    out = _run_controller_harness()
    assert out["lastFetched"] == "/xy/buffers/p?v=3"
    assert "/xy/buffers/p?v=2" in out["allUrls"]


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_queues_a_refetch_until_the_bundle_is_ready():
    out = _run_controller_harness()
    assert out["queuedWhileNotReady"] is True
    assert out["flushedPendingUrl"] == "/xy/buffers/p?v=1"


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_fires_both_change_events_per_successful_refetch():
    """The bundle's in-place append path listens for each event separately."""
    out = _run_controller_harness()
    assert out["events"].count("spec") == 3
    assert out["events"].count("buffers") == 3


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_keeps_the_last_good_frame_when_a_fetch_fails():
    out = _run_controller_harness()
    assert out["keptFrameOnFailure"] is True
```

- [ ] **Step 2: Run the binding tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_xy_component.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.core.servers.reflex.xy_component'`.

- [ ] **Step 3: Write the binding**

```python
# helao/core/servers/reflex/xy_component.py
"""The Reflex binding for xy that xy itself does not yet ship.

``xy`` 0.0.5 has no ``xy.reflex`` module — its own source calls the Reflex
adapter planned work. What it does ship is everything that adapter would have
wrapped: a versioned ESM render client inside the wheel (no CDN, which is what
airgapped lab stations need), a split payload of small JSON spec plus raw
column buffers, and a defined binary frame protocol. This module is the ~100
lines of glue between those and Reflex.

Two design points are load-bearing:

* **Bulk data never enters Reflex state.** Reflex syncs state as JSON over its
  WebSocket; pushing megabyte float arrays through it would forfeit exactly the
  performance xy exists to provide. The small spec rides a state var carrying a
  version token; the browser fetches column buffers from :func:`make_buffer_router`
  and decodes them with the bundle's own ``decodeFrame``.
* **Updates append, they do not re-render.** The bundle exposes an explicit
  append path — bump ``spec.append.seq``, swap buffers, fire the change events —
  and updates the view in place. The shim fires both events and never tears the
  view down on data change.

Delete this module when xy ships its own adapter: :mod:`plots` is the only
consumer.
"""

__all__ = [
    "XYChart",
    "xy_chart",
    "BufferStore",
    "encode_buffers",
    "make_buffer_router",
    "copy_client_asset",
    "CLIENT_ASSET_NAME",
    "BUFFER_ROUTE_PREFIX",
]

import os
import pathlib
import shutil
import threading

import reflex as rx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import xy.channel
import xy.widget

#: Filename the xy ESM client is published under in the Reflex assets dir.
#: Reflex serves ``assets/`` from the site root, so the browser sees "/<name>".
CLIENT_ASSET_NAME = "xy-client.js"

#: URL prefix for the column-buffer route.
BUFFER_ROUTE_PREFIX = "/xy/buffers"


def copy_client_asset(dest_dir: str) -> str:
    """Copy xy's bundled ESM client into the Reflex assets directory.

    The bundle is a generated artifact that ships inside published wheels. A
    source-checkout install lacks it, and xy's own error names the fix
    (``npm ci && node js/build.mjs``).

    Args:
        dest_dir: Reflex ``assets/`` directory.

    Returns:
        str: Path of the written asset.

    Raises:
        FileNotFoundError: If the wheel carries no bundled client.
    """
    source = pathlib.Path(xy.widget.__file__).parent / "static" / "index.js"
    if not source.is_file():
        raise FileNotFoundError(
            f"xy's bundled ESM client is missing at '{source}'. A published "
            "wheel ships it prebuilt; a source checkout must build it once "
            "with `npm ci && node js/build.mjs`."
        )
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, CLIENT_ASSET_NAME)
    shutil.copyfile(source, dest)
    return dest


def encode_buffers(buffers) -> bytes:
    """Encode column buffers using xy's own frame protocol.

    Using ``xy.channel`` rather than an ad-hoc format means the browser decodes
    with the bundle's exported ``decodeFrame`` and the two halves cannot drift.

    Args:
        buffers: The ``list[memoryview]`` from ``Figure.build_payload_split``.

    Returns:
        bytes: One encoded frame carrying every column.
    """
    # encode_frame_parts takes a JSON-able metadata mapping plus the buffer
    # list, and returns scatter/gather parts rather than one blob.
    parts = xy.channel.encode_frame_parts({}, list(buffers))
    return b"".join(bytes(part) for part in parts)


class BufferStore:
    """Process-wide ``panel_id -> (version, buffers)`` map behind the HTTP route.

    Only the newest version of a panel is retained: the browser refetches when
    its version token changes, so an older frame can never be usefully served.
    A stale or unknown request yields ``None`` (404 at the route), and the
    component keeps its last good frame rather than blanking — a refetch racing
    a panel teardown must not clear a live chart.
    """

    def __init__(self):
        """Create an empty store."""
        self._lock = threading.Lock()
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store the newest frame for ``panel_id``, replacing any previous one."""
        with self._lock:
            self._frames[panel_id] = (int(version), encode_buffers(buffers))

    def get(self, panel_id: str, version: int):
        """Return the encoded frame, or ``None`` if unknown or stale."""
        with self._lock:
            entry = self._frames.get(panel_id)
        if entry is None or entry[0] != int(version):
            return None
        return entry[1]

    def drop(self, panel_id: str) -> None:
        """Forget a panel, e.g. when its session ends."""
        with self._lock:
            self._frames.pop(panel_id, None)


def make_buffer_router(store: BufferStore) -> APIRouter:
    """Build the router serving column buffers for ``store``.

    Mounted on the Reflex backend through ``rx.App(api_transformer=...)``;
    Reflex 0.9.7 exposes no public ``app.api`` before build.

    Args:
        store: The :class:`BufferStore` to serve from.

    Returns:
        APIRouter: Router exposing ``GET /xy/buffers/{panel_id}?v=<version>``.
    """
    router = APIRouter()

    @router.get(f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}")
    async def get_buffers(panel_id: str, v: int = Query(...)):
        """Serve one encoded frame as an opaque byte stream."""
        payload = store.get(panel_id, v)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"no buffers for panel '{panel_id}' at version {v}",
            )
        return Response(content=payload, media_type="application/octet-stream")

    return router


#: The React shim. The bundle's ``render({model, el})`` expects an
#: anywidget-style model, so this supplies a stub with exactly the six members
#: it touches — no anywidget dependency, just the same shape.
#: The controller: every piece of shim logic that can be wrong, with no JSX and
#: no React, so it can be evaluated directly by a JS runtime in the test suite.
#: The bundle's ``render({model, el})`` only ever touches the six members
#: assembled here, so this is a plain stub — not an anywidget dependency.
_SHIM_CONTROLLER_JS = """
export function createController(options) {
  const st = {
    spec: options.spec,
    buffers: null,
    handlers: {},
    ready: false,
    pending: false,
    pendingUrl: null,
    decodeFrame: null,
    cleanup: null,
    onSelect: options.onSelect,
    lastUrl: null,
  };

  st.model = {
    get: (name) => (name === "spec" ? st.spec : st.buffers),
    send: (msg) => {
      if (msg && msg.type === "select" && st.onSelect) st.onSelect(msg);
    },
    on: (event, cb) => {
      (st.handlers[event] = st.handlers[event] || []).push(cb);
    },
    off: (event, cb) => {
      st.handlers[event] = (st.handlers[event] || []).filter((h) => h !== cb);
    },
  };

  st.emit = (event) => (st.handlers[event] || []).forEach((cb) => cb());

  // The URL is a parameter, never a closure capture. Capturing it would bind
  // the mount-time value forever: `version` changes every tick, BufferStore
  // keeps only the newest version, so a stale URL 404s, the !ok guard holds the
  // first frame, and the chart silently freezes after one paint.
  st.refetch = async (url) => {
    if (!st.ready) {
      st.pending = true;
      st.pendingUrl = url;
      return;
    }
    if (!url) return;
    st.lastUrl = url;
    try {
      const resp = await fetch(url);
      if (!resp.ok) return;  // keep the last good frame
      const raw = await resp.arrayBuffer();
      st.buffers = st.decodeFrame ? st.decodeFrame(raw) : raw;
      // Both events: the bundle's in-place append path listens for each.
      st.emit("change:spec");
      st.emit("change:buffers");
    } catch (e) {
      // Network hiccup: keep the last good frame rather than blanking.
    }
  };

  st.markReady = () => {
    st.ready = true;
    if (st.pending) {
      st.pending = false;
      const url = st.pendingUrl;
      st.pendingUrl = null;
      st.refetch(url);
    }
  };

  return st;
}
"""

#: The React wrapper. Deliberately thin — it wires props and lifecycle to the
#: controller above and holds no logic of its own.
_SHIM_COMPONENT_JS = """
import { useEffect, useRef } from "react";

export function XYChart({ spec, bufferUrl, height, onSelect }) {
  const hostRef = useRef(null);
  const ctrlRef = useRef(null);
  if (ctrlRef.current === null) {
    ctrlRef.current = createController({ spec: spec, onSelect: onSelect });
  }

  useEffect(() => {
    let disposed = false;
    const st = ctrlRef.current;

    import(/* webpackIgnore: true */ "/xy-client.js").then((mod) => {
      if (disposed || !hostRef.current) return;
      st.decodeFrame = mod.decodeFrame;
      st.cleanup = mod.render({ model: st.model, el: hostRef.current });
      st.markReady();
    });

    return () => {
      disposed = true;
      if (st.cleanup) st.cleanup();
      st.ready = false;
    };
  }, []);

  // Data updates take the bundle's in-place append path, not a remount. The
  // URL is passed as an argument so this always fetches the current version.
  useEffect(() => {
    const st = ctrlRef.current;
    st.spec = spec;
    st.onSelect = onSelect;
    st.refetch(bufferUrl);
  }, [spec, bufferUrl, onSelect]);

  return <div ref={hostRef} style={{ width: "100%", height: height }} />;
}
"""

#: What the component emits: the controller first, then the wrapper that uses it.
_SHIM_JS = _SHIM_CONTROLLER_JS + _SHIM_COMPONENT_JS


class XYChart(rx.NoSSRComponent):
    """A live xy chart driven by Reflex state.

    Client-only: the bundle renders to a WebGL2 canvas, which cannot be
    server-side rendered.

    Attributes:
        spec: Data-less chart spec from ``Figure.build_payload_split``,
            carrying an ``append.seq`` version token.
        buffer_url: Route the browser fetches column buffers from.
        height: CSS height for the chart host element.
    """

    tag = "XYChart"
    library = None  # emitted inline by _get_custom_code, not an npm package

    spec: rx.Var[dict]
    buffer_url: rx.Var[str]
    height: rx.Var[str]

    on_select: rx.EventHandler[lambda payload: [payload]]

    def _get_custom_code(self) -> str:
        """Emit the React shim that bridges Reflex to xy's ESM bundle."""
        return _SHIM_JS


def xy_chart(**props) -> XYChart:
    """Create an :class:`XYChart`.

    Args:
        **props: ``spec``, ``buffer_url``, ``height``, ``on_select``.

    Returns:
        XYChart: The component.
    """
    return XYChart.create(**props)
```

- [ ] **Step 4: Run the binding tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_xy_component.py -v
```

Expected: 21 passed (4 skip if no `node` is on PATH).

If `test_encode_buffers_roundtrips_through_xy_channel` fails on the magic-bytes assertion, read `xy.channel.encode_frame_parts`'s signature and adjust the call — the intent (encode with xy's protocol, not a HELAO one) does not change. If `XYChart` construction fails on `library = None`, consult the Task 0 API note for how Reflex 0.9.7 wants a custom-code-only component declared.

- [ ] **Step 5: Write the failing facade tests**

```python
# helao/core/tests/test_reflex_plots.py
"""Tests for the xy plot facade.

These assert the facade's contract — accepts arrays, tolerates empties,
validates shapes, isolates xy — not xy's rendering, which is xy's concern.
"""

import numpy as np
import pytest

from helao.core.servers.reflex import plots


def test_time_series_returns_a_chart_payload():
    t = np.linspace(0.0, 10.0, 100)
    out = plots.time_series(t, {"a": np.sin(t)}, x_label="t", y_label="v")
    assert isinstance(out, plots.ChartPayload)
    assert isinstance(out.spec, dict)
    assert out.buffer_url.startswith("/xy/buffers/")


def test_time_series_tolerates_empty_arrays():
    assert plots.time_series(np.empty(0), {"a": np.empty(0)}) is not None


def test_time_series_accepts_multiple_series():
    t = np.linspace(0.0, 1.0, 10)
    assert plots.time_series(t, {"a": t, "b": t * 2, "c": t * 3}) is not None


def test_time_series_rejects_a_series_of_the_wrong_length():
    with pytest.raises(ValueError):
        plots.time_series(np.zeros(10), {"a": np.zeros(9)})


def test_time_series_drops_all_nan_series_without_raising():
    t = np.linspace(0.0, 1.0, 10)
    assert plots.time_series(t, {"a": np.full(10, np.nan), "b": t}) is not None


def test_spectra_returns_a_chart_payload():
    w = np.linspace(400.0, 800.0, 512)
    out = plots.spectra(w, {"t0": np.ones(512), "t1": np.ones(512) * 2})
    assert isinstance(out, plots.ChartPayload)


def test_spectra_tolerates_no_traces():
    assert plots.spectra(np.empty(0), {}) is not None


def test_scatter_map_returns_a_chart_payload():
    assert isinstance(
        plots.scatter_map(np.arange(10.0), np.arange(10.0)), plots.ChartPayload
    )


def test_scatter_map_accepts_values_for_coloring():
    assert plots.scatter_map(
        np.arange(10.0), np.arange(10.0), values=np.arange(10.0)
    ) is not None


def test_scatter_map_tolerates_empty_input():
    assert plots.scatter_map(np.empty(0), np.empty(0)) is not None


def test_scatter_map_rejects_mismatched_x_and_y():
    with pytest.raises(ValueError):
        plots.scatter_map(np.zeros(5), np.zeros(4))


def test_scatter_map_rejects_mismatched_values():
    with pytest.raises(ValueError):
        plots.scatter_map(np.zeros(5), np.zeros(5), values=np.zeros(4))


def test_histogram_uses_xys_native_hist_mark():
    """xy 0.0.5 has `hist`; faking histograms with step lines is not needed."""
    comp = plots.histogram(
        {"pred": np.random.default_rng(0).normal(0.45, 0.05, 1000)},
        bins=50,
        value_range=(0.2, 0.7),
    )
    assert comp is not None


def test_histogram_tolerates_an_empty_series():
    assert plots.histogram({"pred": np.empty(0)}, bins=10) is not None


def test_histogram_tolerates_no_series():
    assert plots.histogram({}, bins=10) is not None


def test_version_bump_changes_the_buffer_url_but_not_the_panel_id():
    """The browser refetches on version change; panel identity must be stable."""
    t = np.linspace(0.0, 1.0, 5)
    a = plots.time_series(t, {"a": t}, panel_id="p1", version=1)
    b = plots.time_series(t, {"a": t}, panel_id="p1", version=2)
    assert a.buffer_url != b.buffer_url
    assert "p1" in a.buffer_url and "p1" in b.buffer_url


def test_publishing_parks_buffers_the_route_can_serve():
    t = np.linspace(0.0, 1.0, 5)
    plots.time_series(t, {"a": t}, panel_id="p-store", version=9)
    assert plots.STORE.get("p-store", 9) is not None
    assert plots.STORE.get("p-store", 8) is None


def test_chart_binds_to_state_vars_and_returns_a_component():
    """build() binds once; pull() then drives it through these vars."""
    import reflex as rx

    class _S(rx.State):
        chart_spec: dict = {}
        chart_url: str = ""

    assert plots.chart(_S.chart_spec, _S.chart_url, height=300) is not None


def test_facade_exposes_exactly_the_documented_surface():
    for name in ("time_series", "spectra", "scatter_map", "histogram", "chart"):
        assert callable(getattr(plots, name))
```

- [ ] **Step 6: Run the facade tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_plots.py -v
```

Expected an import failure naming `plots`. The exact exception depends on when you run it: `ModuleNotFoundError` if the `reflex/` package does not exist yet, `ImportError: cannot import name 'plots'` once earlier tasks have created the package. Either is the expected red.

- [ ] **Step 7: Write the facade**

Read `docs/superpowers/notes/2026-08-01-xy-api-probe.md` first and use its recorded mark signatures. xy composes declaratively — `xy.chart(*children, **props)` with marks and axes as children — so each facade function assembles a child list.

```python
# helao/core/servers/reflex/plots.py
"""The HELAO plot facade over the ``xy`` charting library.

This is the only module in the repository that imports xy's charting API.
Every chart in the Reflex UI stack is built through one of the four functions
here, so an alpha-stage upstream change is confined to a single file.

Functions take plain numpy arrays, never buffers, so they are testable with
synthetic data and no ingest layer present. Each builds an ``xy`` figure,
splits it into a small JSON spec plus raw column buffers, parks the buffers in
the process-wide store, and returns the Reflex component bound to both.
"""

__all__ = [
    "PlotBackendError",
    "STORE",
    "ChartPayload",
    "chart",
    "time_series",
    "spectra",
    "scatter_map",
    "histogram",
]

from dataclasses import dataclass

import numpy as np

from helao.core.servers.reflex.xy_component import (
    BUFFER_ROUTE_PREFIX,
    BufferStore,
    xy_chart,
)


class PlotBackendError(RuntimeError):
    """Raised when the xy backend is missing or unusable."""


try:
    import xy
except Exception as exc:  # pragma: no cover - import-time environment failure
    raise PlotBackendError(
        "the xy charting backend is unavailable; the Reflex UI stack cannot "
        f"start. Install it with `pip install xy==0.0.5`. Underlying error: {exc}"
    ) from exc

#: Process-wide store the buffer route serves from. Task 6 hands the router
#: built over this store to ``rx.App(api_transformer=...)``.
STORE = BufferStore()

#: Reused across series so panel colors stay stable between renders.
PALETTE = (
    "#d62728",
    "#1f77b4",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
)


def _as_float_array(values) -> np.ndarray:
    """Coerce ``values`` to a 1-D float64 array."""
    return np.asarray(values, dtype=np.float64).ravel()


def _finite_pairs(x: np.ndarray, y: np.ndarray) -> tuple:
    """Drop index positions where either array is not finite."""
    if x.size == 0 or y.size == 0:
        return x, y
    keep = np.isfinite(x) & np.isfinite(y)
    return x[keep], y[keep]


@dataclass(frozen=True)
class ChartPayload:
    """What a panel assigns into state to drive a chart.

    Attributes:
        spec: Small data-less chart spec. Rides a Reflex var.
        buffer_url: Route the browser fetches column buffers from.
    """

    spec: dict
    buffer_url: str


def _publish(figure, panel_id: str, version: int) -> ChartPayload:
    """Split a figure, park its buffers, and return the state payload.

    Args:
        figure: The assembled ``xy`` figure.
        panel_id: Stable identity for this panel across re-renders.
        version: Monotonic token; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign this into the panel's state vars.
    """
    # xy.chart(...) returns a Chart component; the data-less Figure that
    # carries build_payload_split is produced lazily by .figure().
    spec, buffers = figure.figure().build_payload_split()
    STORE.put(panel_id, version, buffers)
    return ChartPayload(
        spec=spec,
        buffer_url=f"{BUFFER_ROUTE_PREFIX}/{panel_id}?v={version}",
    )


def chart(spec_var, url_var, *, height: int = 320, on_select=None):
    """Bind a chart component to two Reflex state vars.

    Called once from a panel's ``build``. The panel's ``pull`` then assigns
    fresh :class:`ChartPayload` values into ``spec_var`` and ``url_var``, and
    the browser follows.

    Args:
        spec_var: Reflex var holding :attr:`ChartPayload.spec`.
        url_var: Reflex var holding :attr:`ChartPayload.buffer_url`.
        height: Chart height in pixels.
        on_select: Optional Reflex event handler for selection.

    Returns:
        An ``rx.Component``.
    """
    return xy_chart(
        spec=spec_var,
        buffer_url=url_var,
        height=f"{height}px",
        on_select=on_select,
    )


def _axes(x_label: str, y_label: str, x_is_epoch: bool) -> list:
    """Build the axis child components.

    Substitute the exact axis call recorded in the Task 0 API note. Epoch
    seconds are formatted ``HH:MM:SS`` to match the ``DatetimeTickFormatter``
    the Bokeh visualizers use.
    """
    x_kwargs: dict = {"label": x_label}
    if x_is_epoch:
        # xy axis builders take type_/format; there is no scale/tick_format.
        x_kwargs["type_"] = "time"
        x_kwargs["format"] = "%H:%M:%S"
    return [xy.x_axis(**x_kwargs), xy.y_axis(label=y_label)]


def time_series(
    x,
    series: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    x_is_epoch: bool = True,
    panel_id: str = "plot",
    version: int = 0,
):
    """Render one or more line traces against a shared x axis.

    Args:
        x: Shared x values. Epoch seconds when ``x_is_epoch`` is ``True``.
        series: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        x_is_epoch: Format the x axis as ``HH:MM:SS``.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        An empty ``x`` yields a valid empty chart.

    Raises:
        ValueError: If a series length does not match ``len(x)``.
    """
    xs = _as_float_array(x)
    marks = []
    for idx, (label, values) in enumerate(series.items()):
        ys = _as_float_array(values)
        if xs.size and ys.size != xs.size:
            raise ValueError(
                f"series '{label}' has length {ys.size}, expected {xs.size}"
            )
        fx, fy = _finite_pairs(xs, ys)
        if fx.size == 0:
            continue
        marks.append(
            xy.line(x=fx, y=fy, name=label, color=PALETTE[idx % len(PALETTE)])
        )
    figure = xy.chart(*marks, *_axes(x_label, y_label, x_is_epoch))
    return _publish(figure, panel_id, version)


def spectra(
    x,
    traces: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "spectra",
    version: int = 0,
):
    """Render many traces sharing one linear x axis (wavelength, energy).

    Same shape as :func:`time_series` but without epoch formatting, kept
    separate so spectrometer panels read clearly and so the two can diverge
    (trace limits, downsampling) without disturbing each other.

    Args:
        x: Shared x values.
        traces: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
    """
    return time_series(
        x,
        traces,
        x_label=x_label,
        y_label=y_label,
        x_is_epoch=False,
        panel_id=panel_id,
        version=version,
    )


def scatter_map(
    x,
    y,
    *,
    values=None,
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "scatter",
    version: int = 0,
):
    """Render a 2-D point cloud, optionally colored and selectable.

    Backs plate maps and any other spatial sample view.

    Args:
        x: Point x coordinates.
        y: Point y coordinates.
        values: Optional per-point scalar driving color.
        x_label: X axis label.
        y_label: Y axis label.
        height: Chart height in pixels.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.

    Raises:
        ValueError: If ``x`` and ``y`` differ in length, or ``values`` does not
            match them.
    """
    xs = _as_float_array(x)
    ys = _as_float_array(y)
    if xs.size != ys.size:
        raise ValueError(f"x has length {xs.size} but y has length {ys.size}")
    mark_kwargs: dict = {"x": xs, "y": ys}
    if values is not None:
        vs = _as_float_array(values)
        if vs.size != xs.size:
            raise ValueError(f"values has length {vs.size}, expected {xs.size}")
        mark_kwargs["color"] = vs
    else:
        mark_kwargs["color"] = PALETTE[0]
    marks = [xy.scatter(**mark_kwargs)] if xs.size else []
    figure = xy.chart(*marks, *_axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)


def histogram(
    values_by_label: dict,
    *,
    bins: int = 100,
    value_range=None,
    x_label: str = "",
    y_label: str = "density",
    panel_id: str = "histogram",
    version: int = 0,
):
    """Render one or more density histograms using xy's native ``hist`` mark.

    Args:
        values_by_label: Mapping of legend label to raw sample values.
        bins: Number of histogram bins.
        value_range: Optional ``(low, high)`` range.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        Empty or all-non-finite series are skipped.
    """
    marks = []
    for idx, (label, values) in enumerate(values_by_label.items()):
        arr = _as_float_array(values)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        kwargs = {
            "values": arr,
            "bins": bins,
            "name": f"{label} n={arr.size:d}",
            "color": PALETTE[idx % len(PALETTE)],
            "density": True,
        }
        if value_range is not None:
            kwargs["range"] = value_range
        marks.append(xy.hist(**kwargs))
    figure = xy.chart(*marks, *_axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)
```

- [ ] **Step 8: Run the facade tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_plots.py -v
```

Expected: 19 passed. If a test fails inside `xy.line`, `xy.scatter`, `xy.hist`, `xy.x_axis`, or `xy.chart`, the Task 0 API note's recorded signature was not transcribed correctly — fix the call, not the test. Record any signature correction back into the API note in the same commit, since Task 7 reads it.

- [ ] **Step 9: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/xy_component.py helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_xy_component.py helao/core/tests/test_reflex_plots.py
git add helao/core/servers/reflex/xy_component.py helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_xy_component.py helao/core/tests/test_reflex_plots.py
git commit -m "feat(reflex): add the xy Reflex binding and plot facade"
```

## Task 5: Panel state base classes

**Files:**
- Create: `helao/core/servers/reflex/state.py`
- Test: added to `helao/core/tests/test_reflex_panels.py` (created here, extended in Task 7)

**Interfaces:**
- Consumes: `get_registry` from Task 2.
- Produces:
  - `VisPanelState(rx.State)` with vars `server_key: str`, `ws_path: str`, `window_points: int`, `update_rate: float`, `connection: str`, `error: str`, and events `set_window_points(value: str)`, `set_update_rate(value: str)`, `render_loop()`.
  - `LiveVisState(VisPanelState)` — `ws_path = "ws_live"`, `update_rate = 0.5`.
  - `ActionVisState(VisPanelState)` — `ws_path = "ws_data"`, `update_rate = 0.25`.
  - `make_panel_state(module_name: str, server_key: str, base: type, ws_path: str) -> type` — mints and caches a uniquely-named subclass.

**Design notes for the implementer:**
- Reflex requires `State` subclasses to exist as importable classes; you cannot bind one to a runtime value by instantiating it. `make_panel_state` therefore mints a subclass per `(module_name, server_key)` with `type()`, baking `server_key` and `ws_path` in as class defaults. Results are cached so a re-render does not mint a duplicate class (Reflex raises on duplicate State names).
- `set_window_points` and `set_update_rate` reproduce the clamping in `VisSubscriber.callback_input_max_points` (`vis_subscriber.py:311-349`): parse as int, fall back to 500 on garbage, clamp to `[2, 10000]`. Keep that behavior — operators are used to it.
- Subclasses override `pull()`, which reads the ingest buffer and assigns the panel's own state vars. The base `render_loop` handles cadence, connection status, and error capture, so a panel never writes a loop.

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_panels.py
"""Tests for Reflex panel state plumbing and the test-deployment panels."""

import pytest

from helao.core.servers.reflex.state import (
    ActionVisState,
    LiveVisState,
    VisPanelState,
    make_panel_state,
)


def test_live_and_action_bases_carry_the_right_ws_path():
    assert LiveVisState.ws_path_default == "ws_live"
    assert ActionVisState.ws_path_default == "ws_data"


def test_make_panel_state_bakes_in_the_server_key():
    cls = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    assert cls.server_key_default == "SIM"
    assert cls.ws_path_default == "ws_live"


def test_make_panel_state_names_classes_uniquely():
    a = make_panel_state("wssim_panel", "SIM_A", LiveVisState, "ws_live")
    b = make_panel_state("wssim_panel", "SIM_B", LiveVisState, "ws_live")
    assert a.__name__ != b.__name__


def test_make_panel_state_is_cached_so_rerender_reuses_the_class():
    a = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    b = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    assert a is b


def test_clamp_window_points_matches_the_bokeh_behavior():
    assert VisPanelState.clamp_window_points("1", 500) == 2
    assert VisPanelState.clamp_window_points("999999", 500) == 10000
    assert VisPanelState.clamp_window_points("garbage", 700) == 700
    assert VisPanelState.clamp_window_points("garbage", None) == 500
    assert VisPanelState.clamp_window_points("1234", 500) == 1234


def test_parse_update_rate_falls_back_to_half_a_second():
    assert VisPanelState.parse_update_rate("0.25") == 0.25
    assert VisPanelState.parse_update_rate("nope") == 0.5


def test_parse_update_rate_clamps_to_a_sane_floor():
    assert VisPanelState.parse_update_rate("0") >= 0.01
    assert VisPanelState.parse_update_rate("-5") >= 0.01
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_panels.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.core.servers.reflex.state'`.

- [ ] **Step 3: Write the implementation**

```python
# helao/core/servers/reflex/state.py
"""Reflex state bases for HELAO visualizer panels.

These are the Reflex analogues of
:class:`~helao.core.servers.vis_subscriber.LiveVisualizer` and
:class:`~helao.core.servers.vis_subscriber.ActionVisualizer`. The base owns
render cadence, connection status, and error capture; a panel subclass supplies
only :meth:`VisPanelState.pull`, which reads the shared ingest buffer and
assigns the panel's own state vars.

Reflex requires ``State`` subclasses to be real classes, so a panel cannot be
bound to a runtime ``server_key`` by instantiation. :func:`make_panel_state`
mints one cached subclass per ``(module_name, server_key)`` instead.
"""

__all__ = [
    "VisPanelState",
    "LiveVisState",
    "ActionVisState",
    "make_panel_state",
]

import asyncio

import reflex as rx

from helao.core.servers.reflex.ingest import get_registry
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Window bounds carried over from ``VisSubscriber.callback_input_max_points``
#: so operators see the same clamping they are used to.
MIN_WINDOW_POINTS = 2
MAX_WINDOW_POINTS = 10000
DEFAULT_WINDOW_POINTS = 500
MIN_UPDATE_RATE = 0.01
DEFAULT_UPDATE_RATE = 0.5


class VisPanelState(rx.State):
    """Base state for a visualizer panel bound to one ingest target.

    Attributes:
        server_key: Action server this panel reads.
        ws_path: ``ws_live`` or ``ws_data``.
        window_points: Trailing rows pulled from the ring buffer per render.
        update_rate: Seconds between renders.
        connection: Mirror of the ingest status: ``connecting``, ``live``,
            ``reconnecting``, or ``unavailable``.
        error: Most recent error string, empty when healthy.
        running: Whether the render loop is active.
    """

    server_key: str = ""
    ws_path: str = "ws_live"
    window_points: int = DEFAULT_WINDOW_POINTS
    update_rate: float = DEFAULT_UPDATE_RATE
    connection: str = "connecting"
    error: str = ""
    running: bool = False

    # Class-level defaults readable without instantiating a State. Reflex
    # manages the vars above per session; these mirror the bound values so
    # app-build code and tests can introspect them.
    server_key_default: str = ""
    ws_path_default: str = "ws_live"

    @staticmethod
    def clamp_window_points(value, fallback=None) -> int:
        """Parse and clamp a window size the way the Bokeh input did.

        Args:
            value: Raw text from the input widget.
            fallback: Value to use when ``value`` will not parse. ``None``
                means :data:`DEFAULT_WINDOW_POINTS`.

        Returns:
            An int in ``[MIN_WINDOW_POINTS, MAX_WINDOW_POINTS]``.
        """
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = DEFAULT_WINDOW_POINTS if fallback is None else int(fallback)
        return max(MIN_WINDOW_POINTS, min(MAX_WINDOW_POINTS, parsed))

    @staticmethod
    def parse_update_rate(value) -> float:
        """Parse a render interval, defaulting and flooring like the Bokeh input.

        Args:
            value: Raw text from the input widget.

        Returns:
            A float of at least :data:`MIN_UPDATE_RATE`.
        """
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = DEFAULT_UPDATE_RATE
        return max(MIN_UPDATE_RATE, parsed)

    @rx.event
    def on_window_points(self, value: str):
        """Handle the window-size input."""
        self.window_points = self.clamp_window_points(value, self.window_points)

    @rx.event
    def on_update_rate(self, value: str):
        """Handle the render-interval input."""
        self.update_rate = self.parse_update_rate(value)

    def ingest(self):
        """Return this panel's :class:`WsIngest`, or ``None`` if unavailable."""
        registry = get_registry()
        if registry is None:
            return None
        return registry.get(self.server_key or self.server_key_default, self.ws_path)

    def pull(self, ingest) -> None:
        """Copy data from ``ingest`` into this panel's state vars.

        Args:
            ingest: The panel's :class:`WsIngest`.

        Raises:
            NotImplementedError: Panels must implement this.
        """
        raise NotImplementedError

    @rx.event(background=True)
    async def render_loop(self):
        """Poll the ingest buffer at ``update_rate`` until the session ends.

        Ingest runs independently at WebSocket speed; this loop only samples it.
        That decoupling is the point — a fast stream cannot drag the render
        cadence with it the way ``VisSubscriber.IOloop_data`` does.
        """
        async with self:
            if self.running:
                return
            self.running = True
        try:
            while True:
                async with self:
                    if not self.running:
                        return
                    ingest = self.ingest()
                    if ingest is None:
                        self.connection = "unavailable"
                        self.error = (
                            f"no ingest for '{self.server_key or self.server_key_default}' "
                            f"({self.ws_path}); is it declared in the config?"
                        )
                    else:
                        self.connection = ingest.status.state
                        self.error = ingest.status.error or ""
                        try:
                            self.pull(ingest)
                        except Exception as exc:
                            self.error = f"{type(exc).__name__}: {exc}"
                            LOGGER.warning(
                                f"reflex panel pull failed for "
                                f"{self.server_key_default}: {exc}"
                            )
                    interval = self.update_rate
                await asyncio.sleep(interval)
        finally:
            async with self:
                self.running = False

    @rx.event
    def stop_loop(self):
        """Ask the render loop to exit on its next tick."""
        self.running = False


class LiveVisState(VisPanelState):
    """Panel state for continuous sensor telemetry (``ws_live``)."""

    ws_path: str = "ws_live"
    ws_path_default: str = "ws_live"
    update_rate: float = 0.5


class ActionVisState(VisPanelState):
    """Panel state for per-action measurement packages (``ws_data``)."""

    ws_path: str = "ws_data"
    ws_path_default: str = "ws_data"
    update_rate: float = 0.25


_STATE_CACHE: dict = {}


def make_panel_state(module_name: str, server_key: str, base: type, ws_path: str):
    """Mint (or return the cached) State subclass bound to one ingest target.

    Reflex rejects duplicate State class names, so results are cached by
    ``(module_name, server_key)`` and a re-render reuses the same class.

    Args:
        module_name: Panel module short name, e.g. ``"wssim_panel"``.
        server_key: Action server this panel reads.
        base: The :class:`VisPanelState` subclass to extend.
        ws_path: ``ws_live`` or ``ws_data``.

    Returns:
        type: A ``base`` subclass with ``server_key`` and ``ws_path`` bound.
    """
    cache_key = (module_name, server_key, base.__name__)
    if cache_key in _STATE_CACHE:
        return _STATE_CACHE[cache_key]
    safe = "".join(c if c.isalnum() else "_" for c in f"{module_name}_{server_key}")
    cls = type(
        f"{safe}_State",
        (base,),
        {
            "server_key": server_key,
            "ws_path": ws_path,
            "server_key_default": server_key,
            "ws_path_default": ws_path,
            "__doc__": (
                f"Generated panel state binding '{module_name}' to server "
                f"'{server_key}' on '{ws_path}'."
            ),
        },
    )
    _STATE_CACHE[cache_key] = cls
    return cls
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_panels.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/state.py helao/core/tests/test_reflex_panels.py
git add helao/core/servers/reflex/state.py helao/core/tests/test_reflex_panels.py
git commit -m "feat(reflex): add visualizer panel state bases and per-target state factory"
```

---

## Task 6: The app — routes composed from config

**Files:**
- Create: `helao/core/servers/reflex/app.py`
- Create: `helao/core/servers/reflex/_app/rxconfig.py`
- Create: `helao/core/servers/reflex/_app/helao_ui/__init__.py`
- Create: `helao/core/servers/reflex/_app/helao_ui/helao_ui.py`
- Test: extend `helao/core/tests/test_reflex_config.py`

**Interfaces:**
- Consumes: `IngestRegistry`/`set_registry` (Task 2), `resolve_panel_module` (Task 3), `make_panel_state` (Task 5).
- Produces:
  - `panel_targets(world_cfg: dict) -> list[PanelTarget]` where `PanelTarget` is a dataclass of `(server_key, module_name, ws_path)`.
  - `route_map(world_cfg: dict, pages: list[str]) -> dict[str, list[PanelTarget]]`.
  - `build_app(world_cfg: dict, server_key: str) -> rx.App`.
  - `app` — module-level `rx.App` built from `config_loader.CONFIG`, imported by the Reflex entrypoint.

**Design notes for the implementer:**
- The **panel module contract** each deployment panel must satisfy:
  - `WS_PATH: str` — `"ws_live"` or `"ws_data"`.
  - `STATE_BASE: type` — `LiveVisState` or `ActionVisState`.
  - `build(server_key: str, state_cls: type) -> rx.Component`.
- `/live` collects every `live_vis` panel, `/action` every `action_vis` panel. `/` renders a route index. `/operator` and `/browser` render a stub stating which spec will fill them — the navigation shell is complete, the content is not, and the page says so rather than 404ing.
- A panel module that fails to import must **not** take the whole app down. Catch, log, and render an error card in that panel's slot.

- [ ] **Step 1: Write the failing tests (append to `test_reflex_config.py`)**

```python
# appended to helao/core/tests/test_reflex_config.py


def _vis_cfg():
    return {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "live_vis": "wssim_panel",
            },
            "OER": {
                "host": "127.0.0.1",
                "port": 8003,
                "group": "action",
                "action_vis": "oersim_panel",
            },
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
                "params": {"pages": ["live", "action"]},
            },
        }
    }


def test_panel_targets_finds_both_vis_kinds():
    from helao.core.servers.reflex.app import panel_targets

    targets = panel_targets(_vis_cfg())
    assert {(t.server_key, t.module_name, t.ws_path) for t in targets} == {
        ("SIM", "wssim_panel", "ws_live"),
        ("OER", "oersim_panel", "ws_data"),
    }


def test_panel_targets_expands_a_list_of_modules():
    cfg = {
        "servers": {
            "SIM": {
                "host": "h",
                "port": 1,
                "live_vis": ["wssim_panel", "gpsim_panel"],
            }
        }
    }
    from helao.core.servers.reflex.app import panel_targets

    assert len(panel_targets(cfg)) == 2


def test_panel_targets_honors_limit_vis():
    from helao.core.servers.reflex.app import panel_targets

    targets = panel_targets(_vis_cfg(), limit_vis=["SIM"])
    assert [t.server_key for t in targets] == ["SIM"]


def test_route_map_splits_live_and_action():
    from helao.core.servers.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live", "action"])
    assert [t.server_key for t in routes["/live"]] == ["SIM"]
    assert [t.server_key for t in routes["/action"]] == ["OER"]


def test_route_map_always_includes_the_shell_routes():
    from helao.core.servers.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live"])
    for path in ("/", "/live", "/operator", "/browser"):
        assert path in routes


def test_route_map_omits_a_page_not_requested_but_keeps_it_reachable_as_empty():
    from helao.core.servers.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live"])
    assert routes["/action"] == []


def test_only_plots_module_imports_xy():
"""Only the facade and the binding may touch the alpha xy API."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.rglob("*.py"):
        if "/.git/" in str(path) or "site-packages" in str(path):
            continue
        if path.name in (
            "plots.py",
            "xy_component.py",
            "test_reflex_plots.py",
            "test_reflex_xy_component.py",
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^\s*(import xy\b|from xy\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"xy imported outside facade/binding: {offenders}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_config.py -v
```

Expected: the new tests fail with `ModuleNotFoundError: ...reflex.app`; the Task 3 tests still pass.

- [ ] **Step 3: Write the app module**

```python
# helao/core/servers/reflex/app.py
"""The single multi-page Reflex app for one HELAO orchestration group.

One process, one frontend build, and one route per page — rather than the
Bokeh stack's one server process and port per config entry. Panels are
discovered from the same ``live_vis`` / ``action_vis`` config keys the Bokeh
visualizers use, so a config that already declares visualizers needs no new
keys.

A panel module must expose:

* ``WS_PATH`` — ``"ws_live"`` or ``"ws_data"``
* ``STATE_BASE`` — :class:`LiveVisState` or :class:`ActionVisState`
* ``build(server_key, state_cls) -> rx.Component``
"""

__all__ = ["PanelTarget", "panel_targets", "route_map", "build_app", "app"]

from dataclasses import dataclass

import reflex as rx
from fastapi import FastAPI

from helao.core.servers.reflex.discovery import resolve_panel_module
from helao.core.servers.reflex.ingest import (
    VIS_KEY_TO_WS_PATH,
    IngestRegistry,
    set_registry,
)
from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import make_panel_state
from helao.core.servers.reflex.xy_component import make_buffer_router
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Routes always registered so the navigation shell is complete even when a
#: page has no content yet.
SHELL_ROUTES = ("/", "/live", "/action", "/operator", "/browser")

#: Page name -> the config key whose panels belong on it.
PAGE_TO_VIS_KEY = {"live": "live_vis", "action": "action_vis"}


@dataclass(frozen=True)
class PanelTarget:
    """One panel to render: a module bound to a server and a WebSocket path.

    Attributes:
        server_key: Action server the panel reads.
        module_name: Panel module short name.
        ws_path: ``ws_live`` or ``ws_data``.
        vis_key: The config key that produced this target.
    """

    server_key: str
    module_name: str
    ws_path: str
    vis_key: str


def panel_targets(world_cfg: dict, limit_vis=None) -> list:
    """Discover every panel declared by the config's action servers.

    Args:
        world_cfg: The loaded HELAO world config.
        limit_vis: Optional allow-list of server keys, mirroring the Bokeh
            visualizers' ``limit_vis`` server param.

    Returns:
        list: :class:`PanelTarget` entries, config order preserved.
    """
    targets = []
    for server_key, server_cfg in (world_cfg.get("servers") or {}).items():
        if not isinstance(server_cfg, dict):
            continue
        if limit_vis and server_key not in limit_vis:
            continue
        for vis_key, ws_path in VIS_KEY_TO_WS_PATH.items():
            module_names = server_cfg.get(vis_key)
            if not module_names:
                continue
            if isinstance(module_names, str):
                module_names = [module_names]
            for module_name in module_names:
                targets.append(
                    PanelTarget(server_key, module_name, ws_path, vis_key)
                )
    return targets


def route_map(world_cfg: dict, pages, limit_vis=None) -> dict:
    """Group panel targets into routes.

    Every entry of :data:`SHELL_ROUTES` is present in the result, with an empty
    list where a page was not requested or has no panels — a requested-but-empty
    page still renders and says so, rather than 404ing.

    Args:
        world_cfg: The loaded HELAO world config.
        pages: Page names from the Reflex server's ``params.pages``.
        limit_vis: Optional allow-list of server keys.

    Returns:
        dict: ``{route_path: [PanelTarget, ...]}``.
    """
    wanted = set(pages or [])
    all_targets = panel_targets(world_cfg, limit_vis=limit_vis)
    routes = {path: [] for path in SHELL_ROUTES}
    for page, vis_key in PAGE_TO_VIS_KEY.items():
        if page not in wanted:
            continue
        routes[f"/{page}"] = [t for t in all_targets if t.vis_key == vis_key]
    return routes


def _error_card(title: str, detail: str):
    """Render a visible failure instead of a blank slot."""
    return rx.card(
        rx.vstack(
            rx.heading(title, size="3", color_scheme="red"),
            rx.text(detail, size="2"),
            align="start",
            spacing="2",
        ),
        width="100%",
    )


def _render_panel(target: PanelTarget):
    """Build one panel, degrading to an error card if its module misbehaves.

    A broken panel module must not take down the whole page, so import and
    build failures are caught here and rendered in place.
    """
    try:
        module = resolve_panel_module(target.module_name)
    except ModuleNotFoundError as exc:
        LOGGER.warning(f"reflex panel module missing: {exc}")
        return _error_card(f"{target.server_key}: panel module not found", str(exc))
    try:
        state_cls = make_panel_state(
            target.module_name,
            target.server_key,
            module.STATE_BASE,
            module.WS_PATH,
        )
        return module.build(target.server_key, state_cls)
    except Exception as exc:
        LOGGER.warning(f"reflex panel build failed for {target.server_key}: {exc}")
        return _error_card(
            f"{target.server_key}: panel failed to build",
            f"{type(exc).__name__}: {exc}",
        )


def _nav():
    """Render the shared navigation bar."""
    return rx.hstack(
        rx.heading("HELAO", size="5"),
        rx.spacer(),
        rx.link("Live", href="/live"),
        rx.link("Action", href="/action"),
        rx.link("Operator", href="/operator"),
        rx.link("Browser", href="/browser"),
        width="100%",
        padding="0.75em 1em",
        align="center",
        spacing="4",
    )


def _page(title: str, body):
    """Wrap page content in the shared shell."""
    return rx.vstack(
        _nav(),
        rx.divider(),
        rx.heading(title, size="6", padding_x="1em"),
        body,
        width="100%",
        spacing="3",
        padding_bottom="2em",
    )


def _panel_page(title: str, targets: list, empty_note: str):
    """Render a page of panels, or an explanatory note when there are none."""
    if not targets:
        return _page(title, rx.text(empty_note, padding_x="1em"))
    return _page(
        title,
        rx.vstack(
            *[_render_panel(t) for t in targets],
            width="100%",
            spacing="4",
            padding_x="1em",
        ),
    )


def _index_page(routes: dict):
    """Render the route index."""
    return _page(
        "Routes",
        rx.vstack(
            *[
                rx.hstack(
                    rx.link(path, href=path),
                    rx.text(f"{len(targets)} panel(s)", size="2"),
                    spacing="3",
                )
                for path, targets in routes.items()
                if path != "/"
            ],
            align="start",
            spacing="2",
            padding_x="1em",
        ),
    )


def _stub_page(title: str, spec_note: str):
    """Render a placeholder route that states what will fill it."""
    return _page(title, rx.text(spec_note, padding_x="1em"))


def build_app(world_cfg: dict, server_key: str):
    """Build the Reflex app for one orchestration group.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry.

    Returns:
        rx.App: The configured app, with ingest registered on its lifespan.
    """
    server_cfg = (world_cfg.get("servers") or {}).get(server_key) or {}
    params = server_cfg.get("params") or {}
    pages = params.get("pages") or ["live", "action"]
    limit_vis = params.get("limit_vis") or []
    routes = route_map(world_cfg, pages, limit_vis=limit_vis)

    registry = IngestRegistry(world_cfg)
    set_registry(registry)

    # The buffer route carries bulk column data out-of-band, so megabyte float
    # arrays never traverse Reflex's JSON state channel. `api_transformer` is
    # the public seam for this: Reflex 0.9.7 exposes no `app.api` before build
    # and `_api` is private.
    backend = FastAPI()
    backend.include_router(make_buffer_router(plots.STORE))

    application = rx.App(api_transformer=backend)

    application.add_page(lambda: _index_page(routes), route="/", title="HELAO")
    application.add_page(
        lambda: _panel_page(
            "Live visualizers",
            routes["/live"],
            "No server in this config declares a `live_vis` panel.",
        ),
        route="/live",
        title="HELAO live",
    )
    application.add_page(
        lambda: _panel_page(
            "Action visualizers",
            routes["/action"],
            "No server in this config declares an `action_vis` panel.",
        ),
        route="/action",
        title="HELAO action",
    )
    application.add_page(
        lambda: _stub_page(
            "Operator",
            "The Reflex operator is not implemented yet. Use the Bokeh "
            "standalone operator; a follow-up spec covers this page.",
        ),
        route="/operator",
        title="HELAO operator",
    )
    application.add_page(
        lambda: _stub_page(
            "Data browser",
            "The Reflex data browser is not implemented yet. Use the Bokeh "
            "data_browser; a follow-up spec covers this page.",
        ),
        route="/browser",
        title="HELAO browser",
    )

    async def _start_ingest():
        registry.start()
        LOGGER.info(f"reflex ingest started for targets: {registry.targets()}")

    application.register_lifespan_task(_start_ingest)
    return application


def _build_from_global_config():
    """Build the app from the installed global config, if there is one."""
    cfg = config_loader.CONFIG
    if not cfg:
        return rx.App()
    import os

    key = os.environ.get("HELAO_REFLEX_SERVER_KEY", "")
    if not key:
        for candidate, entry in (cfg.get("servers") or {}).items():
            if isinstance(entry, dict) and entry.get("reflex"):
                key = candidate
                break
    return build_app(cfg, key)


#: Module-level app imported by the Reflex CLI entrypoint.
app = _build_from_global_config()
```

- [ ] **Step 4: Write the Reflex project scaffold**

```python
# helao/core/servers/reflex/_app/rxconfig.py
"""Reflex project config for the HELAO UI app.

The ``reflex`` CLI requires a project directory containing ``rxconfig.py`` and
a same-named app package. ``reflex_launcher.py`` runs the CLI from this
directory; the app itself lives in ``helao.core.servers.reflex.app`` so it is
importable and testable as ordinary repository code.

Ports come from the environment because they are per-config, not per-project:
``reflex_launcher.py`` sets them from the server entry.
"""

import os

import reflex as rx

config = rx.Config(
    app_name="helao_ui",
    frontend_port=int(os.environ.get("HELAO_REFLEX_FRONTEND_PORT", "5010")),
    backend_port=int(os.environ.get("HELAO_REFLEX_BACKEND_PORT", "5011")),
    api_url=os.environ.get("HELAO_REFLEX_API_URL", "http://127.0.0.1:5011"),
)
```

```python
# helao/core/servers/reflex/_app/helao_ui/__init__.py
"""Reflex app package for the HELAO UI."""
```

```python
# helao/core/servers/reflex/_app/helao_ui/helao_ui.py
"""Reflex CLI entrypoint.

Re-exports the app built from the HELAO global config. All real logic lives in
``helao.core.servers.reflex.app``; keeping this file a one-liner means the app
stays importable and testable outside the Reflex CLI.
"""

from helao.core.servers.reflex.app import app  # noqa: F401
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_config.py -v
```

Expected: 18 passed (11 from Task 3, 7 new).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/app.py helao/core/servers/reflex/_app/rxconfig.py helao/core/servers/reflex/_app/helao_ui/__init__.py helao/core/servers/reflex/_app/helao_ui/helao_ui.py helao/core/tests/test_reflex_config.py
git add helao/core/servers/reflex/app.py helao/core/servers/reflex/_app helao/core/tests/test_reflex_config.py
git commit -m "feat(reflex): build multi-page app with routes composed from config"
```

---

## Task 7: The `test` deployment panels

**Files:**
- Create: `helao/deploy/test/servers/reflex/__init__.py`
- Create: `helao/deploy/test/servers/reflex/wssim_panel.py`
- Create: `helao/deploy/test/servers/reflex/oersim_panel.py`
- Create: `helao/deploy/test/servers/reflex/gpsim_panel.py`
- Test: extend `helao/core/tests/test_reflex_panels.py`

**Interfaces:**
- Consumes: `LiveVisState` / `ActionVisState` / `make_panel_state` (Task 5), `plots` (Task 4), `WsIngest` (Task 2).
- Produces: three modules, each exposing `WS_PATH`, `STATE_BASE`, and `build(server_key, state_cls)`.

**Design notes for the implementer:**

- **The two-call split from Task 4 governs every panel.** `build` runs once when the page is composed and calls `plots.chart(state_cls.chart_spec, state_cls.chart_url, ...)` to bind the component to state. `pull` runs on every render tick and calls a facade function (`plots.time_series`, `plots.histogram`, …) to produce a fresh `ChartPayload`, then assigns `.spec` and `.buffer_url` into those vars. Calling a facade function from `build` yields a chart that paints once and then never moves.
- Every panel needs a **stable `panel_id`** and a **monotonic `version`**. `panel_id` is `f"{module}-{server_key}"` — constant for the panel's life, because a shifting id would orphan entries in the buffer store. `version` increments on each successful `pull`; the browser refetches only when it changes.
- `wssim_panel` ports `wssim_live_vis.py`: six `series_<i>` columns against `epoch`, plus a latest-value table. Reads the numeric ring buffer.
- `oersim_panel` ports `oersim_vis.py`, an `ActionVisualizer` on `ws_data`.
- `gpsim_panel` ports `gpsim_live_vis.py` and is the awkward one: its payload carries per-plate arrays (`pred_avail`, `gt_acquired`) that do not fit a flat numeric column, and string columns (`orchestrator`, `last_acquisition`) that cannot live in a float64 ring. It reads `ingest.raw` (untransformed batches) and `ingest.rows` (mixed-type rows) instead. This is exactly why `WsIngest` keeps both. Binning is xy's job — pass raw samples to `plots.histogram`, which uses xy's native `hist` mark.
- Each panel's `pull` runs on the render timer with the state lock held, so keep it cheap.

- [ ] **Step 1: Write the failing tests (append to `test_reflex_panels.py`)**

```python
# appended to helao/core/tests/test_reflex_panels.py


PANEL_MODULES = ["wssim_panel", "oersim_panel", "gpsim_panel"]


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_module_satisfies_the_contract(name):
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    assert mod.WS_PATH in ("ws_live", "ws_data")
    assert issubclass(mod.STATE_BASE, VisPanelState)
    assert callable(mod.build)


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_builds_a_component_without_an_ingest_layer(name):
    """A panel must render before any data arrives."""
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    state_cls = make_panel_state(name, "TESTKEY", mod.STATE_BASE, mod.WS_PATH)
    assert mod.build("TESTKEY", state_cls) is not None


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_state_declares_the_chart_binding_vars(name):
    """build() binds these; pull() drives them. Both halves are required."""
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    assert hasattr(mod.STATE_BASE, "chart_spec")
    assert hasattr(mod.STATE_BASE, "chart_url")


def test_wssim_extract_reads_series_columns_from_the_buffer():
    import numpy as np

    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.buffer.append(
        {"epoch": [1.0, 2.0], "series_0": [10.0, 11.0], "series_1": [20.0, 21.0]}
    )
    cols = wssim_panel.extract(ing, window=10)
    np.testing.assert_allclose(cols["epoch"], [1.0, 2.0])
    np.testing.assert_allclose(cols["series"]["series_0"], [10.0, 11.0])
    assert "series_1" in cols["series"]


def test_wssim_extract_skips_the_epoch_column_in_the_series_set():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.buffer.append({"epoch": [1.0], "series_0": [5.0]})
    assert "epoch" not in wssim_panel.extract(ing, window=10)["series"]


def test_wssim_extract_on_an_empty_buffer_returns_empty_not_none():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    cols = wssim_panel.extract(ing, window=10)
    assert cols["epoch"].size == 0
    assert cols["series"] == {}


def test_panel_id_is_stable_across_calls():
    from helao.deploy.test.servers.reflex import wssim_panel

    assert wssim_panel.panel_id("SIM") == wssim_panel.panel_id("SIM")
    assert wssim_panel.panel_id("SIM") != wssim_panel.panel_id("OTHER")


def test_gpsim_histograms_are_extracted_from_raw_batches():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.raw.append(
        [
            {
                "plate_id": ([4001], 100.0),
                "pred_avail": ([[0.3, 0.4, 0.5]], 100.0),
                "gt_acquired": ([[0.35, 0.45]], 100.0),
            }
        ]
    )
    hists = gpsim_panel.extract_histograms(ing)
    assert "4001 predicted" in hists
    assert "4001 acquired" in hists
    assert len(hists["4001 predicted"]) == 3


def test_gpsim_histograms_on_an_empty_raw_deque_is_empty():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    assert gpsim_panel.extract_histograms(WsIngest("127.0.0.1", 1, "ws_live")) == {}


def test_gpsim_passes_raw_samples_to_the_facade_not_prebinned_data():
    """xy has a native hist mark; binning in Python would be redundant work."""
    import inspect

    from helao.deploy.test.servers.reflex import gpsim_panel

    src = inspect.getsource(gpsim_panel)
    assert "plots.histogram" in src
    assert "np.histogram" not in src
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_panels.py -v
```

Expected: the new tests fail with `ModuleNotFoundError` on `helao.deploy.test.servers.reflex`; the Task 5 tests still pass.

- [ ] **Step 3: Write the panels**

```python
# helao/deploy/test/servers/reflex/__init__.py
"""Reflex UI panels for the `test` deployment simulators."""
```

```python
# helao/deploy/test/servers/reflex/wssim_panel.py
"""Reflex panel for the websocket simulator's live datastream.

Reflex port of ``servers/visualizer/wssim_live_vis.py``: the ``series_<i>``
columns plotted against time, plus a latest-value table. The two coexist; a
station picks one through its config.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState

WS_PATH = "ws_live"

#: Column excluded from the plotted series set: it is the x axis.
X_COLUMN = "epoch"


def panel_id(server_key: str) -> str:
    """Stable buffer-store identity for this panel.

    Must not vary across renders: a shifting id would orphan store entries.
    """
    return f"wssim-{server_key}"


def extract(ingest, window: int) -> dict:
    """Pull the x column and every other numeric column from the ring buffer.

    Args:
        ingest: The panel's :class:`WsIngest`.
        window: Number of trailing rows to read.

    Returns:
        dict: ``{"epoch": np.ndarray, "series": {name: np.ndarray}}``.
    """
    snap = ingest.buffer.snapshot(window)
    return {
        "epoch": snap.get(X_COLUMN, np.empty(0)),
        "series": {k: v for k, v in snap.items() if k != X_COLUMN},
    }


class _State(LiveVisState):
    """Chart binding vars plus the latest-value table."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Recompute the chart payload and the latest-value table."""
        cols = extract(ingest, self.window_points)
        self.version += 1
        payload = plots.time_series(
            cols["epoch"],
            cols["series"],
            x_label="Time (HH:MM:SS)",
            y_label="value",
            panel_id=panel_id(self.server_key_default),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.table_rows = [
            [name, f"{values[-1]:.6g}"]
            for name, values in cols["series"].items()
            if values.size
        ]


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Live: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.window_points),
                    on_blur=state_cls.on_window_points,
                    placeholder="window points",
                    width="10em",
                ),
                rx.input(
                    default_value=str(state_cls.update_rate),
                    on_blur=state_cls.on_update_rate,
                    placeholder="update sec",
                    width="8em",
                ),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, color_scheme="red"),
            ),
            plots.chart(state_cls.chart_spec, state_cls.chart_url, height=320),
            rx.data_table(
                data=state_cls.table_rows,
                columns=["name", "value"],
                pagination=False,
                search=False,
                sort=False,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
```

```python
# helao/deploy/test/servers/reflex/oersim_panel.py
"""Reflex panel for the OER simulator's per-action data stream.

Reflex port of ``servers/visualizer/oersim_vis.py``. Subscribes to ``ws_data``
and renders the action-scoped measurement traces.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState

WS_PATH = "ws_data"

X_COLUMN = "epoch"


def panel_id(server_key: str) -> str:
    """Stable buffer-store identity for this panel."""
    return f"oersim-{server_key}"


def extract(ingest, window: int) -> dict:
    """Read the trailing window from the ring buffer.

    Args:
        ingest: The panel's :class:`WsIngest`.
        window: Number of trailing rows.

    Returns:
        dict: ``{"x": np.ndarray, "series": {name: np.ndarray}}``.
    """
    snap = ingest.buffer.snapshot(window)
    return {
        "x": snap.get(X_COLUMN, np.empty(0)),
        "series": {k: v for k, v in snap.items() if k != X_COLUMN},
    }


class _State(ActionVisState):
    """Chart binding vars for the OER simulator."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0

    def pull(self, ingest) -> None:
        """Recompute the chart payload from the trailing window."""
        cols = extract(ingest, self.window_points)
        self.version += 1
        payload = plots.time_series(
            cols["x"],
            cols["series"],
            x_label="Time (HH:MM:SS)",
            y_label="value",
            panel_id=panel_id(self.server_key_default),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Action: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.window_points),
                    on_blur=state_cls.on_window_points,
                    placeholder="window points",
                    width="10em",
                ),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, color_scheme="red"),
            ),
            plots.chart(state_cls.chart_spec, state_cls.chart_url, height=320),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
```

```python
# helao/deploy/test/servers/reflex/gpsim_panel.py
"""Reflex panel for the GP simulator's live acquisition stream.

Reflex port of ``servers/visualizer/gpsim_live_vis.py``. This payload does not
fit the flat numeric-column model — it carries per-plate sample arrays
(``pred_avail``, ``gt_acquired``) and string columns (``orchestrator``,
``last_acquisition``) — so this panel reads the ingest layer's raw message
deque and its mixed-type row buffer rather than the numeric ring.

Binning is xy's job: raw samples go straight to :func:`plots.histogram`, which
uses xy's native ``hist`` mark.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract_histograms", "panel_id"]

import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState

WS_PATH = "ws_live"

#: Histogram range and bin count carried over from gpsim_live_vis.py.
HIST_BINS = 100
HIST_RANGE = (0.2, 0.7)

#: Table columns, matching the Bokeh DataTable.
TABLE_COLUMNS = [
    "plate_id",
    "step",
    "frac_acquired",
    "last_acquisition",
    "orchestrator",
]


def panel_id(server_key: str) -> str:
    """Stable buffer-store identity for this panel."""
    return f"gpsim-{server_key}"


def extract_histograms(ingest) -> dict:
    """Pull per-plate sample arrays out of the most recent raw batch.

    Args:
        ingest: The panel's :class:`WsIngest`.

    Returns:
        dict: ``{"<plate_id> predicted": [...], "<plate_id> acquired": [...]}``.
            Empty when no usable batch has arrived.
    """
    if not ingest.raw:
        return {}
    out: dict = {}
    for message in ingest.raw[-1]:
        if not isinstance(message, dict):
            continue
        plates = message.get("plate_id")
        pred = message.get("pred_avail")
        acq = message.get("gt_acquired")
        if not (plates and pred and acq):
            continue
        plate_ids, pred_vals, acq_vals = plates[0], pred[0], acq[0]
        for i, plate in enumerate(plate_ids):
            if i < len(pred_vals):
                out[f"{plate} predicted"] = list(pred_vals[i])
            if i < len(acq_vals):
                out[f"{plate} acquired"] = list(acq_vals[i])
    return out


class _State(LiveVisState):
    """Chart binding vars plus the acquisitions table."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Recompute the histogram payload and the last 20 acquisition rows."""
        self.version += 1
        payload = plots.histogram(
            extract_histograms(ingest),
            bins=HIST_BINS,
            value_range=HIST_RANGE,
            x_label="Eta (V vs O2/H2O)",
            y_label="density",
            panel_id=panel_id(self.server_key_default),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.table_rows = [
            [str(row.get(col, "")) for col in TABLE_COLUMNS]
            for row in ingest.rows.rows()[-20:]
        ]


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"GP simulator: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.update_rate),
                    on_blur=state_cls.on_update_rate,
                    placeholder="update sec",
                    width="8em",
                ),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, color_scheme="red"),
            ),
            plots.chart(state_cls.chart_spec, state_cls.chart_url, height=320),
            rx.heading("Last 20 acquisitions across all orchestrators", size="3"),
            rx.data_table(
                data=state_cls.table_rows,
                columns=TABLE_COLUMNS,
                pagination=False,
                search=False,
                sort=False,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_panels.py -v
```

Expected: 22 passed (7 from Task 5, 15 new — the three parametrized tests contribute three cases each).

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/test/servers/reflex/ helao/core/tests/test_reflex_panels.py
git add helao/deploy/test/servers/reflex helao/core/tests/test_reflex_panels.py
git commit -m "feat(reflex): add test deployment panels for wssim, oersim, and gpsim"
```

## Task 8: The launcher

**Files:**
- Create: `reflex_launcher.py`
- Modify: `launch.py:1129-1148`, `launch.py:1218-1240`
- Modify: `.gitignore`
- Test: `helao/core/tests/test_reflex_launcher.py`

**Interfaces:**
- Consumes: the app scaffold at `helao/core/servers/reflex/_app/` (Task 6).
- Produces:
  - `reflex_launcher.resolve_bundle(repo_root: str) -> str | None` — returns the exported frontend bundle directory, or `None`.
  - `reflex_launcher.backend_port(port: int) -> int` — returns `port + 1`.
  - `reflex_launcher.build_env(config_path, server_key, host, port, root) -> dict` — the child environment.
  - `launch.py` spawns `reflex_launcher.py` for `reflex` code-key servers.

**Design notes for the implementer:**
- A Reflex server runs **two** listeners: the static frontend on `port` (served by a small `uvicorn`+`StaticFiles` app inside `reflex_launcher.py`, so no Node is needed at runtime) and the Reflex backend on `port + 1` (`reflex run --backend-only`).
- Bundle location: `<repo_root>/.reflex-bundle/<app_name>/`. Gitignored. Built on a dev machine with `reflex export --frontend-only`.
- If the bundle is missing, the launcher logs an explicit error naming the expected path and the build command, then exits non-zero. It attempts a local build only when `REFLEX_ALLOW_LOCAL_BUILD=1` is set and a `bun` or `node` executable is on `PATH`. A lab station never trips this branch.
- Reuse `write_loaded_modules_snapshot` exactly as `bokeh_launcher.py:180-189` does, so the hot-reload watcher maps changed Python files to this server.

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_launcher.py
"""Unit tests for reflex_launcher's pure helpers."""

import os

import pytest

import reflex_launcher as rl


def test_backend_port_is_one_above_the_frontend_port():
    assert rl.backend_port(5010) == 5011


def test_resolve_bundle_returns_none_when_absent(tmp_path):
    assert rl.resolve_bundle(str(tmp_path)) is None


def test_resolve_bundle_finds_an_exported_bundle(tmp_path):
    bundle = tmp_path / ".reflex-bundle" / "helao_ui"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")
    assert rl.resolve_bundle(str(tmp_path)) == str(bundle)


def test_resolve_bundle_rejects_a_directory_without_index_html(tmp_path):
    (tmp_path / ".reflex-bundle" / "helao_ui").mkdir(parents=True)
    assert rl.resolve_bundle(str(tmp_path)) is None


def test_build_env_sets_the_ports_and_server_key():
    env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, "/tmp/root")
    assert env["HELAO_REFLEX_FRONTEND_PORT"] == "5010"
    assert env["HELAO_REFLEX_BACKEND_PORT"] == "5011"
    assert env["HELAO_REFLEX_API_URL"] == "http://127.0.0.1:5011"
    assert env["HELAO_REFLEX_SERVER_KEY"] == "UI"


def test_build_env_preserves_the_parent_environment():
    os.environ["HELAO_TEST_SENTINEL"] = "keepme"
    try:
        env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, "/tmp/root")
        assert env["HELAO_TEST_SENTINEL"] == "keepme"
    finally:
        del os.environ["HELAO_TEST_SENTINEL"]


def test_local_build_is_refused_without_the_opt_in(monkeypatch):
    monkeypatch.delenv("REFLEX_ALLOW_LOCAL_BUILD", raising=False)
    assert rl.may_build_locally() is False


def test_local_build_requires_a_js_runtime(monkeypatch):
    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: None)
    assert rl.may_build_locally() is False


def test_local_build_allowed_with_opt_in_and_runtime(monkeypatch):
    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: "/usr/bin/bun")
    assert rl.may_build_locally() is True


def test_assets_dir_sits_inside_the_reflex_project():
    """The ESM client must be inside the project so `reflex export` bundles it."""
    assert rl.ASSETS_DIR.startswith(rl.APP_DIR)
    assert rl.ASSETS_DIR.endswith("assets")


def test_launch_py_has_a_reflex_branch():
    import inspect

    import launch

    src = inspect.getsource(launch.launch_server_groups)
    assert 'codeKey == "reflex"' in src
    assert "reflex_launcher.py" in src
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_launcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'reflex_launcher'`.

- [ ] **Step 3: Write the launcher**

```python
# reflex_launcher.py
"""Launch the HELAO Reflex UI app for one config entry.

Sibling of ``bokeh_launcher.py``. A Reflex server occupies two consecutive
ports: the prebuilt static frontend is served on ``port`` by a small uvicorn +
StaticFiles app defined here, and the Reflex backend runs on ``port + 1``.
Serving the frontend ourselves means a lab station never needs Node or Bun at
runtime — only the dev machine that produced the bundle does.

Usage:
    python reflex_launcher.py <config_file> <server_key>

Build the frontend bundle on a development machine before deploying::

    cd helao/core/servers/reflex/_app
    reflex export --frontend-only
    # then place the export under <repo_root>/.reflex-bundle/helao_ui/
"""

__all__ = [
    "APP_NAME",
    "BUNDLE_DIRNAME",
    "backend_port",
    "resolve_bundle",
    "build_env",
    "may_build_locally",
]

import asyncio
import os
import shutil
import subprocess
import sys

#: Must match ``app_name`` in ``helao/core/servers/reflex/_app/rxconfig.py``.
APP_NAME = "helao_ui"

#: Gitignored directory under the repo root holding the exported frontend.
BUNDLE_DIRNAME = ".reflex-bundle"

#: Reflex project directory the CLI is invoked from.
APP_DIR = os.path.join("helao", "core", "servers", "reflex", "_app")

#: Reflex assets directory, served from the site root. xy's ESM client is
#: copied here before the frontend build so the bundle ships it and the browser
#: never reaches for a CDN.
ASSETS_DIR = os.path.join(APP_DIR, "assets")


def backend_port(port: int) -> int:
    """Return the Reflex backend port for a server whose frontend is on ``port``."""
    return int(port) + 1


def resolve_bundle(repo_root: str):
    """Locate the exported frontend bundle.

    Args:
        repo_root: HELAO repository root.

    Returns:
        The bundle directory, or ``None`` when no usable bundle is present. A
        directory without ``index.html`` is treated as absent — a half-written
        export must not be served.
    """
    candidate = os.path.join(repo_root, BUNDLE_DIRNAME, APP_NAME)
    if os.path.isdir(candidate) and os.path.isfile(
        os.path.join(candidate, "index.html")
    ):
        return candidate
    return None


def build_env(config_path: str, server_key: str, host: str, port: int, root):
    """Return the child environment for the Reflex backend process.

    Args:
        config_path: Config argument forwarded to the child.
        server_key: Config key of this Reflex server.
        host: Host the servers bind to.
        port: Frontend port; the backend uses ``port + 1``.
        root: HELAO output root, or ``None``.

    Returns:
        dict: A copy of the parent environment plus the HELAO Reflex vars.
    """
    env = dict(os.environ)
    env["HELAO_REFLEX_SERVER_KEY"] = server_key
    env["HELAO_REFLEX_CONFIG"] = str(config_path)
    env["HELAO_REFLEX_FRONTEND_PORT"] = str(port)
    env["HELAO_REFLEX_BACKEND_PORT"] = str(backend_port(port))
    env["HELAO_REFLEX_API_URL"] = f"http://{host}:{backend_port(port)}"
    if root:
        env["HELAO_REFLEX_ROOT"] = str(root)
    return env


def may_build_locally() -> bool:
    """Whether a local frontend build is permitted in this environment.

    Requires both the ``REFLEX_ALLOW_LOCAL_BUILD=1`` opt-in and a JavaScript
    runtime on ``PATH``. Lab stations set neither, so they fail loudly on a
    missing bundle instead of silently attempting a multi-minute network build.
    """
    if os.environ.get("REFLEX_ALLOW_LOCAL_BUILD") != "1":
        return False
    return bool(shutil.which("bun") or shutil.which("node"))


def _serve_frontend(bundle_dir: str, host: str, port: int):
    """Serve the exported static frontend. Blocks until interrupted."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    static_app = FastAPI()
    static_app.mount(
        "/", StaticFiles(directory=bundle_dir, html=True), name="frontend"
    )
    uvicorn.run(static_app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    if sys.platform == "win32":
        # Match bokeh_launcher.py: a selector loop, so a co-located ZMQ RPC
        # socket works without the Proactor loop's missing add_reader family.
        asyncio.set_event_loop(asyncio.SelectorEventLoop())

    from helao.helpers import config_loader
    from helao.helpers import helao_logging as logging
    from helao.helpers.yml_tools import yml_load

    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    confArg = sys.argv[1]
    server_key = sys.argv[2]

    if config_loader.CONFIG is None:
        config_dict, _validated = config_loader.read_validated_config(confArg)
        config_loader.install_global_config(config_dict)
    CONFIG = config_loader.CONFIG

    server_config = CONFIG["servers"][server_key]
    root = CONFIG.get("root", None)
    log_root = os.path.join(root, "LOGS") if root else None
    email_config = (
        yml_load(CONFIG["alert_config_path"])
        if CONFIG.get("alert_config_path", False)
        else {}
    )
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=email_config,
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    LOGGER = logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")

    servHost = server_config["host"]
    servPort = server_config["port"]

    config_path = CONFIG["loaded_config_path"]
    CONFIG["deployment"] = server_config.get(
        "deployment",
        os.path.basename(os.path.dirname(os.path.dirname(config_path))),
    )

    bundle = resolve_bundle(helao_repo_root)
    if bundle is None:
        expected = os.path.join(helao_repo_root, BUNDLE_DIRNAME, APP_NAME)
        if not may_build_locally():
            LOGGER.error(
                f"no Reflex frontend bundle at '{expected}'. Build one on a "
                f"development machine with:\n"
                f"    cd {APP_DIR} && reflex export --frontend-only\n"
                f"then copy the export to that path. To build here instead, set "
                f"REFLEX_ALLOW_LOCAL_BUILD=1 and install bun or node."
            )
            sys.exit(1)
        LOGGER.warning(f"no bundle at '{expected}'; building locally (dev only)")
        from helao.core.servers.reflex.xy_component import copy_client_asset

        asset = copy_client_asset(os.path.join(helao_repo_root, ASSETS_DIR))
        LOGGER.info(f"copied xy ESM client to {asset}")
        subprocess.run(
            ["reflex", "export", "--frontend-only"],
            cwd=os.path.join(helao_repo_root, APP_DIR),
            env=build_env(confArg, server_key, servHost, servPort, root),
            check=True,
        )
        bundle = resolve_bundle(helao_repo_root)
        if bundle is None:
            LOGGER.error("local build completed but produced no usable bundle")
            sys.exit(1)

    LOGGER.info(f"serving Reflex frontend bundle from {bundle}")

    # Import the app before snapshotting so the loaded-modules map includes the
    # panel modules resolved from config strings. Same reason bokeh_launcher
    # refreshes its snapshot after mount_visualizers.
    from helao.core.servers.reflex import app as _reflex_app  # noqa: F401

    if root is not None:
        from helao.helpers.loaded_modules import write_loaded_modules_snapshot

        snap_path = write_loaded_modules_snapshot(
            os.path.join(root, "STATES"), server_key
        )
        if snap_path is not None:
            LOGGER.info(f"wrote loaded-modules snapshot: {snap_path}")
        else:
            LOGGER.warning("failed to write loaded-modules snapshot")

    LOGGER.info(f" ---- starting  {server_key} ----")

    backend = subprocess.Popen(
        [
            "reflex",
            "run",
            "--env",
            "prod",
            "--backend-only",
            "--backend-port",
            str(backend_port(servPort)),
        ],
        cwd=os.path.join(helao_repo_root, APP_DIR),
        env=build_env(confArg, server_key, servHost, servPort, root),
    )
    LOGGER.info(
        f"started {server_key}: frontend {servHost}:{servPort}, "
        f"backend {servHost}:{backend_port(servPort)}"
    )
    try:
        _serve_frontend(bundle, servHost, servPort)
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend.kill()
```

- [ ] **Step 4: Add the `reflex` branch to `launch.py`**

In `launch_server_groups`, immediately after the `elif codeKey == "bokeh":` block (`launch.py:1129-1143`), insert:

```python
                    elif codeKey == "reflex":
                        cmd = ["python", "-u", "reflex_launcher.py", confArg, server]
                        p = subprocess.Popen(
                            cmd,
                            cwd=helao_repo_root,
                            env=CONSOLE.child_env(),
                            **CONSOLE.spawn_kwargs(),
                        )
                        CONSOLE.register(server, p)
                        ppid = p.pid
```

`server_loaded_files` (`launch.py:1215`) needs **no logic change**: it queries `/loaded_modules` only when `"fast" in server_entry` and otherwise falls through to the `STATES/loaded_modules_<key>.json` snapshot. A Reflex server, like a Bokeh server, exposes no such route and writes that snapshot at startup, so it already takes the correct branch. Update only the docstring and the inline comment so the behavior is not mistaken for an oversight:

Docstring, second sentence — replace:

```
    FastAPI servers (``fast``) are queried live at ``/loaded_modules``; bokeh
    servers (``bokeh``) have no HTTP route, so their startup snapshot at
```

with:

```
    FastAPI servers (``fast``) are queried live at ``/loaded_modules``; bokeh
    and reflex servers have no such HTTP route, so their startup snapshot at
```

And the inline comment — replace `# bokeh server (visualizer/operator)` with `# bokeh or reflex server (visualizer/operator)`.

- [ ] **Step 4b: Confirm CTRL-r restart resolves for a Reflex server**

`restart_server` builds its command as `f"{codeKey}_launcher.py"` (`launch.py:1601`), so creating `reflex_launcher.py` at the repo root makes CTRL-r work for a `reflex:` server with no further change. That is convenient but implicit — verify it rather than assume:

```bash
conda run -n helao python -c "
import inspect, launch
src = inspect.getsource(launch.restart_server)
assert '{codeKey}_launcher.py' in src, 'restart_server no longer derives the launcher name'
import os
assert os.path.isfile('reflex_launcher.py'), 'reflex_launcher.py missing at repo root'
print('CTRL-r resolves reflex -> reflex_launcher.py: OK')
"
```

Expected: `CTRL-r resolves reflex -> reflex_launcher.py: OK`. If `restart_server` has since been changed to a hardcoded mapping, add `reflex` to it and say so in your report.

- [ ] **Step 5: Gitignore the bundle**

Append to `.gitignore`:

```
# Exported Reflex frontend bundle; built per-machine, shipped as a release
# artifact rather than tracked. See reflex_launcher.py.
.reflex-bundle/

# xy's ESM render client, copied out of the installed wheel at build time.
# Generated artifact, ~411 KB — never tracked.
helao/core/servers/reflex/_app/assets/xy-client.js

# Reflex's own build directory.
helao/core/servers/reflex/_app/.web/
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_launcher.py -v
conda run -n helao python -m pytest helao/core/tests/test_launch_pid_verify.py -v
```

Expected: 11 passed in the first, all pass in the second.

- [ ] **Step 7: Format and commit**

```bash
conda run -n helao black reflex_launcher.py launch.py helao/core/tests/test_reflex_launcher.py
git add reflex_launcher.py launch.py .gitignore helao/core/tests/test_reflex_launcher.py
git commit -m "feat(reflex): add reflex_launcher and wire the reflex code key into launch.py"
```

---

## Task 9: Config and end-to-end route smoke test

**Files:**
- Create: `helao/deploy/test/configs/goldenreflex.yml`
- Test: `helao/core/tests/test_reflex_routes_e2e.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a launchable config and a route-level smoke test.

**Design notes for the implementer:**
- `goldenreflex.yml` is `golden.yml` with the Bokeh visualizer entries replaced by one Reflex entry. The Bokeh standalone operator stays — this slice does not replace it, and keeping it proves coexistence in a single running group.
- The e2e test builds the app in-process and asserts every route is registered and renders. It does **not** shell out to `launch.py`; that would need a built frontend bundle, which CI does not have. Full-stack verification is the manual browser step.

- [ ] **Step 1: Write the config**

```yaml
# helao/deploy/test/configs/goldenreflex.yml
# Reflex UI stack over the `test` deployment simulators, proving coexistence:
# the Bokeh standalone operator and the Reflex visualizer app run in the same
# group. Reflex servers occupy two ports (frontend, then backend), so UI at
# 5010 also claims 5011.
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py
run_type: simulation
root: /home/dan/INST_hlo_reflex
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    params: {}
  OPERATOR:
    host: 127.0.0.1
    port: 5001
    group: operator
    bokeh: standalone_operator
    params:
      orch_key: ORCH
      doc_name: "Operator (bokeh, unchanged)"
      poll_interval: 5
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    live_vis: wssim_panel
    params: {}
  UI:
    host: 127.0.0.1
    port: 5010
    group: visualizer
    reflex: helao_ui
    params:
      pages:
        - live
        - action
```

- [ ] **Step 2: Write the failing e2e test**

```python
# helao/core/tests/test_reflex_routes_e2e.py
"""End-to-end checks that the Reflex app builds every route from a real config.

This builds the app in-process rather than launching it: a full launch needs an
exported frontend bundle, which is a developer-machine artifact. Browser-level
verification is the manual step in the plan.
"""

import pytest

from helao.helpers import config_loader


@pytest.fixture
def reflex_cfg():
    """Load goldenreflex.yml and install it as the global config."""
    saved = config_loader.CONFIG
    cfg, _ = config_loader.read_validated_config("goldenreflex")
    config_loader.install_global_config(cfg)
    yield config_loader.CONFIG
    config_loader.CONFIG = saved


def test_goldenreflex_config_is_valid(reflex_cfg):
    from launch import validateConfig

    class _P:
        reqKeys = ("host", "port", "group")
        codeKeys = ("fast", "bokeh", "reflex")

    assert validateConfig(_P(), reflex_cfg, ".") is True


def test_goldenreflex_keeps_the_bokeh_operator_alongside_reflex(reflex_cfg):
    servers = reflex_cfg["servers"]
    assert servers["OPERATOR"]["bokeh"] == "standalone_operator"
    assert servers["UI"]["reflex"] == "helao_ui"


def test_app_builds_and_registers_every_shell_route(reflex_cfg):
    from helao.core.servers.reflex.app import SHELL_ROUTES, build_app

    application = build_app(reflex_cfg, "UI")
    registered = set(application.unevaluated_pages or application.pages)
    for path in SHELL_ROUTES:
        normalized = path if path != "/" else "index"
        assert any(
            normalized.strip("/") in str(r).strip("/") for r in registered
        ), f"route {path} not registered; registered={registered}"


def test_route_map_puts_the_sim_panel_on_live(reflex_cfg):
    from helao.core.servers.reflex.app import route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    assert [t.server_key for t in routes["/live"]] == ["SIM"]
    assert [t.module_name for t in routes["/live"]] == ["wssim_panel"]


def test_ingest_registry_discovers_the_sim_target(reflex_cfg):
    from helao.core.servers.reflex.ingest import IngestRegistry

    assert IngestRegistry(reflex_cfg).targets() == [("SIM", "ws_live")]


def test_every_panel_on_every_route_renders(reflex_cfg):
    from helao.core.servers.reflex.app import _render_panel, route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    for path, targets in routes.items():
        for target in targets:
            assert _render_panel(target) is not None, f"{path}:{target.server_key}"
```

- [ ] **Step 3: Run the test to verify it fails, then passes**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_routes_e2e.py -v
```

If `test_app_builds_and_registers_every_shell_route` fails on the `unevaluated_pages`/`pages` attribute, consult the Task 0 API note for how the installed Reflex version exposes registered routes and fix the assertion to read that attribute. The intent — every shell route is registered — does not change.

Expected once correct: 6 passed.

- [ ] **Step 4: Run the whole new suite together**

```bash
conda run -n helao python run_tests.py --filter reflex
```

Expected: every `test_reflex_*.py` file reports PASS. Remember this runs one file per process by design.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/core/tests/test_reflex_routes_e2e.py
git add helao/deploy/test/configs/goldenreflex.yml helao/core/tests/test_reflex_routes_e2e.py
git commit -m "test(reflex): add goldenreflex config and route-level end-to-end checks"
```

---

## Task 10: Manual browser verification and documentation

**Files:**
- Modify: `CLAUDE.md`
- Test: manual

**Interfaces:**
- Consumes: everything above.
- Produces: a verified running stack and the documentation a future reader needs.

- [ ] **Step 1: Build the frontend bundle**

```bash
# Copy xy's ESM render client into the project assets first — the export must
# bundle it, or the browser has nothing to render with and no CDN to fall back on.
conda run -n helao python -c "from helao.core.servers.reflex.xy_component import copy_client_asset; print(copy_client_asset('helao/core/servers/reflex/_app/assets'))"

cd helao/core/servers/reflex/_app
conda run -n helao reflex init --loglevel info
conda run -n helao reflex export --frontend-only
```

Confirm the copied asset is ~411 KB and that `assets/xy-client.js` appears in the export output. A truncated or missing asset produces a page that loads and then renders no charts at all.

Move the export output to `<repo_root>/.reflex-bundle/helao_ui/` such that `index.html` sits directly in that directory. Record the exact export output path in the Task 0 API note under a new "## Bundle export" section, since it is version-dependent.

If `reflex init` requires network access to fetch npm dependencies and the machine is offline, **stop and report** — the bundle must be built somewhere with network access. That is the documented constraint, not a failure.

- [ ] **Step 2: Launch the group**

```bash
conda run -n helao python launch.py goldenreflex
```

Expected in the log: `ORCH`, `OPERATOR`, `SIM`, and `UI` all start; `UI` logs `frontend 127.0.0.1:5010, backend 127.0.0.1:5011`.

- [ ] **Step 3: Verify in a browser**

Open `http://127.0.0.1:5010/` and confirm each of these. Record the result of every line; a failure here is a task failure, not a note.

1. `/` lists all five routes with panel counts.
2. `/live` shows the `SIM` panel with a `live` badge.
3. The time-series chart draws and **updates** — watch it for 30 seconds and confirm new points arrive. This is the first and only end-to-end proof of the hand-written binding: spec through Reflex state, buffers through the HTTP route, in-place append in the bundle. If the chart paints once and then freezes, the append path is not firing — check that `pull` bumps `version` and that the browser is refetching (Network tab should show one `/xy/buffers/...` request per tick, each with a new `v=`).
4. Pan and zoom work on the chart.
5. The latest-value table updates alongside the chart.
6. Changing "window points" to `50` visibly shortens the trace.
7. Changing "update sec" to `2` visibly slows the refresh.
8. `/action` renders and states that no server declares an `action_vis` panel.
9. `/operator` and `/browser` render their stub text rather than 404ing.
10. The Bokeh operator at `http://127.0.0.1:5001/standalone_operator` still works — this is the coexistence check and it is the most important line in this list.

- [ ] **Step 4: Verify reconnection**

With the group running and `/live` open, restart the SIM server with `CTRL-r` (or kill and relaunch it). Confirm:

1. The panel badge flips to `reconnecting` within ~10 seconds.
2. It returns to `live` and the chart resumes once SIM is back — **without reloading the page**.

This is the behavior the Bokeh visualizers do not have, and it is the clearest single proof the new ingest layer is worth its complexity.

- [ ] **Step 5: Shut down cleanly**

Press `CTRL-x`. Confirm every process exits and no `python` process remains bound to 5010 or 5011:

```bash
ss -ltnp | grep -E ':(5010|5011)' || echo "ports clear"
```

Expected: `ports clear`.

- [ ] **Step 6: Document the stack in `CLAUDE.md`**

Under "Environment & common commands", after the `python run_tests.py` bullet, add:

```markdown
- Reflex UI stack (coexists with Bokeh; opt-in per config via the `reflex:` server key). A Reflex server occupies **two** consecutive ports: `port` serves the prebuilt static frontend, `port + 1` is the Reflex backend. Stations never need Node — build the bundle on a development machine and ship it:

  ```
  cd helao/core/servers/reflex/_app && reflex export --frontend-only
  # place the export at <repo_root>/.reflex-bundle/helao_ui/ (gitignored)
  ```

  `reflex_launcher.py` refuses to start without a bundle unless `REFLEX_ALLOW_LOCAL_BUILD=1` is set and bun/node is on `PATH`. Panels live in `helao/deploy/<deployment>/servers/reflex/` and are discovered through the same `live_vis:` / `action_vis:` config keys the Bokeh visualizers use. All charts go through `helao/core/servers/reflex/plots.py`, the only module importing the (alpha) `xy` library. Try it with `python launch.py goldenreflex`.
```

In the "Three-layer layout" section, extend the `helao/core/` bullet to mention `servers/reflex/` alongside the existing server classes, and extend the `helao/deploy/<deployment>/` bullet's directory list with `servers/reflex/`.

- [ ] **Step 7: Full suite regression**

```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python run_tests.py
```

Expected: `run_unit_tests.py` PASS. `run_tests.py` shows no new `FAIL` relative to the pre-branch baseline. Capture the baseline first if you do not have it:

```bash
git stash && conda run -n helao python run_tests.py > /tmp/claude-1000/-mnt-STORAGE-repos-helao-helao-async/451cc925-d50f-485b-a793-27138b66779d/scratchpad/baseline.txt; git stash pop
```

- [ ] **Step 8: Format and commit**

```bash
conda run -n helao black docs/superpowers/notes/2026-08-01-xy-api-probe.md 2>/dev/null || true
git add CLAUDE.md docs/superpowers/notes/2026-08-01-xy-api-probe.md
git commit -m "docs: document the Reflex UI stack and record bundle export path"
```

---

## Completion criteria

All of the following, no exceptions:

- [ ] `conda run -n helao python run_tests.py --filter reflex` reports PASS for all eight `test_reflex_*.py` files.
- [ ] `conda run -n helao python run_unit_tests.py` passes.
- [ ] `conda run -n helao python run_tests.py` shows no new failures against the pre-branch baseline.
- [ ] `python launch.py goldenreflex` brings up the group, and every one of Task 10 Step 3's ten browser checks passes — including check 10, the Bokeh operator still working.
- [ ] The reconnection check in Task 10 Step 4 passes.
- [ ] `grep -rn "^\s*\(import xy\|from xy\)" --include="*.py" .` returns only `helao/core/servers/reflex/plots.py` and `helao/core/servers/reflex/xy_component.py`.
- [ ] `docs/superpowers/notes/2026-08-01-xy-api-probe.md` contains real probe output with no unreplaced `<...>` placeholders.
- [ ] No private deployment is named in any tracked file added or modified by this plan.
- [ ] `black` has been run on every changed Python file.
- [ ] Work is committed on `feat/reflex-ui-stack`, not pushed, no PR opened.
