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
| `helao/core/servers/reflex/plots.py` | The plot facade: `time_series`, `spectra`, `scatter_map`, `histogram`. The **only** module importing `xy`. |
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
2. The spec lists three facade functions. A fourth, `histogram`, is added — `gpsim_live_vis` renders `quad` histograms, and xy 0.0.5 has no bar/quad primitive, so `histogram` renders a step line over the bin edges. This is a small visual change from the Bokeh version and is intentional.
3. The spec's facade signatures take a buffer (`time_series(buf, ...)`). The facade takes plain numpy arrays instead, so it is testable with no ingest layer present.
4. Reflex frontend and backend run on two ports (`port` and `port + 1`). Reflex's production model separates them, and a single-port merge depends on API surface this plan will not assume.

---

## Task 0: Dependency gate — verify Reflex and xy actually deliver

This is a **hard gate**. If any check fails, stop and report — do not work around it, do not proceed to Task 1. The rest of the plan assumes these APIs exist.

**Files:**
- Create: `docs/superpowers/notes/2026-08-01-xy-api-probe.md`
- Modify: `helao_dev_linux-64.yml`, `helao_dev_win-64.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a recorded, verified API note that Tasks 5 and 7 read for exact xy and Reflex call signatures. Pinned versions in both env files.

- [ ] **Step 1: Install the two dependencies into the `helao` env**

```bash
conda run -n helao pip install 'reflex>=0.9.7,<0.10' 'xy==0.0.5'
```

Expected: both install without a resolver conflict against the existing env. If pip reports an incompatibility with an existing pin, **stop and report it** — do not force-install.

- [ ] **Step 2: Probe the API surface**

Write this to the scratchpad (not the repo) and run it:

```python
# /tmp/claude-1000/-mnt-STORAGE-repos-helao-helao-async/451cc925-d50f-485b-a793-27138b66779d/scratchpad/probe_xy.py
import inspect
import numpy as np

import reflex as rx
import xy

print("reflex", rx.__version__ if hasattr(rx, "__version__") else "?")
print("xy", getattr(xy, "__version__", "?"))

# 1. Chart primitives we depend on.
for name in ("line", "scatter", "plot"):
    print("xy has", name, ":", hasattr(xy, name))

# 2. The Reflex adapter.
try:
    import xy.reflex as xyrx
    print("xy.reflex OK, exports:", [n for n in dir(xyrx) if not n.startswith("_")])
except Exception as e:
    print("xy.reflex IMPORT FAILED:", type(e).__name__, e)

# 3. Build one figure and hand it to the adapter.
t = np.linspace(0.0, 10.0, 1000)
fig = xy.figure() if hasattr(xy, "figure") else None
print("xy.figure:", fig)
print("top-level xy exports:", [n for n in dir(xy) if not n.startswith("_")])

# 4. Reflex APIs this plan uses.
print("rx.App params:", list(inspect.signature(rx.App).parameters))
print("has register_lifespan_task:", hasattr(rx.App, "register_lifespan_task"))
print("has rx.data_table:", hasattr(rx, "data_table"))
print("has rx.State:", hasattr(rx, "State"))
```

```bash
conda run -n helao python /tmp/claude-1000/-mnt-STORAGE-repos-helao-helao-async/451cc925-d50f-485b-a793-27138b66779d/scratchpad/probe_xy.py
```

- [ ] **Step 3: Evaluate the gate**

The gate **passes** only if all of these hold:

1. `import xy` succeeds.
2. `import xy.reflex` succeeds and exports a component factory.
3. xy exposes a line primitive and a scatter primitive.
4. `rx.App` accepts a `state` or equivalent, and `rx.data_table` exists.

If 1–3 fail, **stop**: the spec's Decision 4 (thin facade) was chosen precisely so a failure here is contained, but the first slice cannot be built. Report which check failed and what xy 0.0.5 actually exports.

If 4 fails, **stop** and report — the Reflex version pin needs revisiting.

- [ ] **Step 4: Record the verified API**

Write `docs/superpowers/notes/2026-08-01-xy-api-probe.md` containing:

```markdown
# xy / Reflex API probe — 2026-08-01

Recorded from a live probe in the `helao` conda env (Python 3.14.6).
Tasks 5 and 7 use these exact signatures. Re-run the probe after any version bump.

## Versions
- reflex: <exact version printed>
- xy: <exact version printed>

## xy top-level exports
<paste the printed list>

## xy.reflex exports
<paste the printed list>

## Line chart — verified call
<paste the exact working call, copied from the probe run>

## Scatter chart — verified call
<paste the exact working call>

## Reflex APIs used
- rx.App parameters: <paste>
- rx.App.register_lifespan_task present: <yes/no>
- rx.data_table present: <yes/no>

## Known gaps at this version
- No bar/quad primitive. `plots.histogram` renders a step line over bin edges instead.
- <any other gap the probe surfaced>
```

Every `<...>` placeholder must be replaced with real probe output before committing. A committed note containing an unreplaced `<...>` is a task failure.

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
conda run -n helao black helao_dev_linux-64.yml helao_dev_win-64.yml 2>/dev/null || true
git add docs/superpowers/notes/2026-08-01-xy-api-probe.md helao_dev_linux-64.yml helao_dev_win-64.yml
git commit -m "chore: pin reflex and xy, record verified API surface"
```

(`black` does not format YAML; the `|| true` keeps the habit without failing the step.)

---

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
                value is not coercible to float64.
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

        self.ensure_columns(cols)

        block = {}
        for name in self._cols:
            if name in cols:
                try:
                    arr = np.asarray(cols[name], dtype=np.float64)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"column '{name}' is not numeric: {exc}"
                    ) from exc
            else:
                arr = np.full(n, np.nan, dtype=np.float64)
            block[name] = arr

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
        """Return retained rows, oldest first."""
        return list(self._rows)

    def latest(self):
        """Return the most recent row, or ``None`` when empty."""
        return self._rows[-1] if self._rows else None

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

Expected: 13 passed.

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
    element. Each message contributes exactly one ``epoch`` value — the maximum
    ``epochsec`` in that message — matching the behavior of the Bokeh
    visualizers' ``add_points``.

    Values that will not coerce to ``float`` (server names, sample labels,
    status strings) are collected into per-message row dicts instead, because
    :class:`RingBuffer` is float64-only.

    Args:
        messages: Batches drained from a :class:`WsSubscriber`.

    Returns:
        ``(numeric_columns, mixed_rows)``. ``numeric_columns`` maps column name
        to a list of floats; ``mixed_rows`` is one dict per message that carried
        at least one non-numeric value. Malformed entries are skipped.
    """
    cols: dict = {}
    rows: list = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        latest_epoch = 0.0
        row: dict = {}
        pending: dict = {}
        for datalab, payload in message.items():
            if not isinstance(payload, (tuple, list)) or len(payload) != 2:
                continue
            dataval, epochsec = payload
            try:
                latest_epoch = max(latest_epoch, float(epochsec))
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

        for name, values in pending.items():
            try:
                floats = [float(v) for v in values]
            except (TypeError, ValueError):
                row[name] = values[-1] if len(values) == 1 else values
                continue
            cols.setdefault(name, []).extend(floats)

        if latest_epoch:
            cols.setdefault("epoch", []).append(latest_epoch)
        if row:
            rows.append(row)

    # Pad shorter columns so RingBuffer.append sees a rectangular block. A
    # server that publishes some keys less often than others is normal.
    if cols:
        width = max(len(v) for v in cols.values())
        for name, values in cols.items():
            if len(values) < width:
                values.extend([float("nan")] * (width - len(values)))
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
        """Cancel the drain loop and the underlying subscriber. Idempotent."""
        for task in (self._task, getattr(self._wss, "subscriber_task", None)):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
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

Expected: 12 passed. The reconnect test takes several seconds — that is the `WsSubscriber` backoff and is expected.

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

## Task 4: The plot facade

**Files:**
- Create: `helao/core/servers/reflex/plots.py`
- Test: `helao/core/tests/test_reflex_plots.py`

**Interfaces:**
- Consumes: the verified xy call signatures recorded in `docs/superpowers/notes/2026-08-01-xy-api-probe.md` (Task 0).
- Produces:
  - `time_series(x, series, *, x_label="", y_label="", x_is_epoch=True, height=320) -> rx.Component`
  - `spectra(x, traces, *, x_label="", y_label="", height=320) -> rx.Component`
  - `scatter_map(x, y, *, values=None, on_select=None, x_label="", y_label="", height=420) -> rx.Component`
  - `histogram(values_by_label, *, bins=100, value_range=None, x_label="", y_label="density", height=320) -> rx.Component`
  - `PlotBackendError` raised at import time if xy is unusable.

**Design notes for the implementer:**
- This is the **only** module in the repo permitted to `import xy`. Grep-enforced by a test in Task 8.
- Arrays in, component out. The facade never touches a `RingBuffer`, so it is testable with synthetic numpy arrays and no ingest layer.
- `x_is_epoch=True` means the x array holds epoch seconds and the facade formats the axis as `HH:MM:SS`, matching the `DatetimeTickFormatter(minutes="%T", hours="%T")` the Bokeh visualizers use.
- `histogram` exists because xy 0.0.5 has no bar or quad primitive. It computes `np.histogram` and renders the result as a **step line** over the bin edges. Document that deviation in the module docstring.
- Every function must tolerate empty arrays and return a valid empty chart rather than raising — panels render before the first message arrives.
- Use the exact xy calls recorded in the Task 0 note. Where this plan writes `_xy_line(...)` / `_xy_scatter(...)`, substitute the verified call and keep it inside the private helper so there is still exactly one place to change.

- [ ] **Step 1: Write the failing tests**

```python
# helao/core/tests/test_reflex_plots.py
"""Tests for the xy plot facade.

These assert the facade's contract — accepts arrays, tolerates empties, and
isolates xy — not xy's rendering, which is xy's own concern.
"""

import numpy as np
import pytest

from helao.core.servers.reflex import plots


def test_time_series_returns_a_component():
    t = np.linspace(0.0, 10.0, 100)
    comp = plots.time_series(t, {"a": np.sin(t)}, x_label="t", y_label="v")
    assert comp is not None


def test_time_series_tolerates_empty_arrays():
    comp = plots.time_series(np.empty(0), {"a": np.empty(0)})
    assert comp is not None


def test_time_series_accepts_multiple_series():
    t = np.linspace(0.0, 1.0, 10)
    comp = plots.time_series(t, {"a": t, "b": t * 2, "c": t * 3})
    assert comp is not None


def test_time_series_rejects_a_series_of_the_wrong_length():
    with pytest.raises(ValueError):
        plots.time_series(np.zeros(10), {"a": np.zeros(9)})


def test_time_series_drops_all_nan_series_without_raising():
    t = np.linspace(0.0, 1.0, 10)
    comp = plots.time_series(t, {"a": np.full(10, np.nan), "b": t})
    assert comp is not None


def test_spectra_returns_a_component():
    w = np.linspace(400.0, 800.0, 512)
    comp = plots.spectra(w, {"t0": np.ones(512), "t1": np.ones(512) * 2})
    assert comp is not None


def test_spectra_tolerates_no_traces():
    assert plots.spectra(np.empty(0), {}) is not None


def test_scatter_map_returns_a_component():
    comp = plots.scatter_map(np.arange(10.0), np.arange(10.0))
    assert comp is not None


def test_scatter_map_accepts_values_for_coloring():
    comp = plots.scatter_map(
        np.arange(10.0), np.arange(10.0), values=np.arange(10.0)
    )
    assert comp is not None


def test_scatter_map_tolerates_empty_input():
    assert plots.scatter_map(np.empty(0), np.empty(0)) is not None


def test_scatter_map_rejects_mismatched_x_and_y():
    with pytest.raises(ValueError):
        plots.scatter_map(np.zeros(5), np.zeros(4))


def test_histogram_returns_a_component():
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


def test_facade_exposes_exactly_the_documented_surface():
    for name in (
        "time_series",
        "spectra",
        "scatter_map",
        "histogram",
        "histogram_steps",
    ):
        assert callable(getattr(plots, name))


def test_histogram_steps_traces_a_flat_top_per_bin():
    x, y = plots.histogram_steps(
        np.array([0.25, 0.25, 0.25]), bins=2, value_range=(0.0, 1.0)
    )
    # Two bins produce two flat segments: 4 x points, 4 y points.
    assert x.size == 4 and y.size == 4
    assert y[0] == y[1]  # first bin holds its value across its width


def test_histogram_steps_drops_non_finite_samples():
    x, y = plots.histogram_steps(
        np.array([np.nan, np.inf, 0.5]), bins=2, value_range=(0.0, 1.0)
    )
    assert x.size == 4 and np.all(np.isfinite(y))


def test_histogram_steps_on_empty_input_returns_empty_arrays():
    x, y = plots.histogram_steps(np.empty(0), bins=10)
    assert x.size == 0 and y.size == 0


def test_time_series_binds_reactively_when_given_a_state_var():
    """A panel binds vars, not arrays, so the chart updates as state changes."""
    import reflex as rx

    class _S(rx.State):
        epoch: list = []
        series: dict = {}

    assert plots.time_series(_S.epoch, _S.series, x_label="t") is not None


def test_scatter_map_binds_reactively_when_given_state_vars():
    import reflex as rx

    class _S2(rx.State):
        px: list = []
        py: list = []

    assert plots.scatter_map(_S2.px, _S2.py) is not None


def test_spectra_binds_reactively_when_given_state_vars():
    """gpsim bins in pull, then binds the step traces through spectra."""
    import reflex as rx

    class _S3(rx.State):
        hist_x: list = []
        hist_series: dict = {}

    assert plots.spectra(_S3.hist_x, _S3.hist_series) is not None


def test_reactive_path_skips_length_validation():
    """Vars carry no length at build time, so validation must not fire."""
    import reflex as rx

    class _S4(rx.State):
        epoch: list = []
        series: dict = {}

    # Would raise on the concrete path; must not on the reactive path.
    assert plots.time_series(_S4.epoch, _S4.series) is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_plots.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.core.servers.reflex.plots'`.

- [ ] **Step 3: Write the implementation**

Read `docs/superpowers/notes/2026-08-01-xy-api-probe.md` first and substitute the verified xy calls inside `_xy_line` and `_xy_scatter`. Everything else below is final.

```python
# helao/core/servers/reflex/plots.py
"""The HELAO plot facade over the ``xy`` charting library.

This is the only module in the repository that imports ``xy``. Every chart in
the Reflex UI stack is built through one of the four functions here, so the
alpha-stage xy API is confined to a single file: a breaking change upstream
touches this module and nothing else.

Functions take plain numpy arrays, never buffers, so they can be tested with
synthetic data and no ingest layer present.

Deviation worth knowing: xy 0.0.5 has no bar or quad primitive, so
:func:`histogram` computes ``np.histogram`` and renders a **step line** over
the bin edges. The Bokeh visualizers it replaces used filled ``quad`` glyphs.
"""

__all__ = [
    "PlotBackendError",
    "time_series",
    "spectra",
    "scatter_map",
    "histogram",
    "histogram_steps",
]

import numpy as np
import reflex as rx


class PlotBackendError(RuntimeError):
    """Raised when the xy backend is missing or unusable."""


try:
    import xy  # noqa: F401
    import xy.reflex as xyrx
except Exception as exc:  # pragma: no cover - import-time environment failure
    raise PlotBackendError(
        "the xy charting backend is unavailable; the Reflex UI stack cannot "
        f"start. Install it with `pip install xy==0.0.5`. Underlying error: {exc}"
    ) from exc

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


def _is_reactive(obj) -> bool:
    """Whether ``obj`` is a Reflex var rather than concrete data.

    A panel binds its chart to state vars so the chart re-renders when the
    render loop assigns new data. Those vars are opaque at build time — they
    carry no values yet — so every facade function has two paths: coerce and
    validate concrete arrays, or hand a var straight to the adapter untouched.
    """
    return isinstance(obj, rx.Var)


def _as_float_array(values) -> np.ndarray:
    """Coerce ``values`` to a 1-D float64 array."""
    return np.asarray(values, dtype=np.float64).ravel()


def _finite_pairs(x: np.ndarray, y: np.ndarray) -> tuple:
    """Drop index positions where either array is not finite."""
    if x.size == 0 or y.size == 0:
        return x, y
    keep = np.isfinite(x) & np.isfinite(y)
    return x[keep], y[keep]


def _xy_line(fig, x, y, *, label, color):
    """Draw one line on ``fig``.

    Substitute the exact call verified in
    ``docs/superpowers/notes/2026-08-01-xy-api-probe.md``. Keeping it in this
    one helper means an xy API change is a single-line edit.
    """
    fig.line(x, y, label=label, color=color)


def _xy_scatter(fig, x, y, *, label, color, values=None):
    """Draw one scatter series on ``fig``.

    Substitute the exact call verified in the Task 0 API note.
    """
    if values is not None:
        fig.scatter(x, y, c=values, label=label)
    else:
        fig.scatter(x, y, label=label, color=color)


def _new_figure(*, x_label: str, y_label: str, x_is_epoch: bool = False):
    """Create a bare xy figure with axis labels applied.

    Height is a component concern, not a figure concern; :func:`_component`
    applies it.
    """
    fig = xy.figure()
    fig.set_xlabel(x_label)
    fig.set_ylabel(y_label)
    if x_is_epoch:
        # Epoch seconds on the x axis, formatted HH:MM:SS to match the
        # DatetimeTickFormatter the Bokeh visualizers use.
        fig.set_xaxis_time_format("%H:%M:%S")
    return fig


def _component(fig, height: int):
    """Wrap an xy figure as a Reflex component."""
    return xyrx.chart(fig, height=f"{height}px", width="100%")


def _reactive_component(
    x,
    series,
    *,
    kind: str,
    x_label: str,
    y_label: str,
    height: int,
    x_is_epoch: bool = False,
    on_select=None,
):
    """Bind a chart to Reflex vars so it re-renders as state changes.

    Substitute the exact reactive call verified in
    ``docs/superpowers/notes/2026-08-01-xy-api-probe.md``. Both branches below
    are complete; pick the one the installed adapter supports and delete the
    other, recording the choice in the API note.

    Branch A — the adapter accepts vars directly (preferred)::

        return xyrx.chart(
            x=x, series=series, kind=kind,
            x_label=x_label, y_label=y_label, x_is_epoch=x_is_epoch,
            height=f"{height}px", width="100%", on_select=on_select,
        )

    Branch B — the adapter takes only a plain data spec. Pass a computed var
    from the panel instead: the panel adds a ``chart_spec`` ``rx.var`` that
    returns ``{"x": [...], "series": {...}, "kind": kind}``, and this function
    receives that single var as ``series`` with ``x`` set to ``None``::

        return xyrx.chart_from_spec(
            series, height=f"{height}px", width="100%", on_select=on_select,
        )

    Args:
        x: Reflex var (or ``None`` under Branch B) holding x values.
        series: Reflex var holding ``{label: [values]}``, or the full spec var
            under Branch B.
        kind: ``"line"``, ``"scatter"``, or ``"step"``.
        x_label: X axis label.
        y_label: Y axis label.
        height: Chart height in pixels.
        x_is_epoch: Format the x axis as ``HH:MM:SS``.
        on_select: Optional selection event handler.

    Returns:
        An ``rx.Component`` bound to the supplied vars.
    """
    return xyrx.chart(
        x=x,
        series=series,
        kind=kind,
        x_label=x_label,
        y_label=y_label,
        x_is_epoch=x_is_epoch,
        height=f"{height}px",
        width="100%",
        on_select=on_select,
    )


def time_series(
    x,
    series: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    x_is_epoch: bool = True,
    height: int = 320,
):
    """Render one or more traces against a shared x axis.

    Args:
        x: Shared x values. Epoch seconds when ``x_is_epoch`` is ``True``.
        series: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        x_is_epoch: Format the x axis as ``HH:MM:SS``.
        height: Chart height in pixels.

    Returns:
        An ``rx.Component``. An empty ``x`` yields a valid empty chart. When
        ``x`` or ``series`` is a Reflex var, the chart binds reactively and
        re-renders whenever the panel's render loop assigns new data.

    Raises:
        ValueError: If a concrete series length does not match ``len(x)``.
    """
    if _is_reactive(x) or _is_reactive(series):
        return _reactive_component(
            x, series, kind="line", x_label=x_label, y_label=y_label,
            x_is_epoch=x_is_epoch, height=height,
        )
    xs = _as_float_array(x)
    fig = _new_figure(x_label=x_label, y_label=y_label, x_is_epoch=x_is_epoch)
    for idx, (label, values) in enumerate(series.items()):
        ys = _as_float_array(values)
        if xs.size and ys.size != xs.size:
            raise ValueError(
                f"series '{label}' has length {ys.size}, expected {xs.size}"
            )
        fx, fy = _finite_pairs(xs, ys)
        if fx.size == 0:
            continue
        _xy_line(fig, fx, fy, label=label, color=PALETTE[idx % len(PALETTE)])
    return _component(fig, height)


def spectra(
    x,
    traces: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    height: int = 320,
):
    """Render many traces sharing one x axis (wavelength, energy, frequency).

    Identical in shape to :func:`time_series` but with a linear x axis and no
    epoch formatting, kept separate so spectrometer panels read clearly and so
    the two can diverge (downsampling, trace limits) without disturbing each
    other.

    Args:
        x: Shared x values.
        traces: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        height: Chart height in pixels.

    Returns:
        An ``rx.Component``.
    """
    return time_series(
        x,
        traces,
        x_label=x_label,
        y_label=y_label,
        x_is_epoch=False,
        height=height,
    )


def scatter_map(
    x,
    y,
    *,
    values=None,
    on_select=None,
    x_label: str = "",
    y_label: str = "",
    height: int = 420,
):
    """Render a 2-D point cloud, optionally colored and selectable.

    Backs plate maps and any other spatial sample view.

    Args:
        x: Point x coordinates.
        y: Point y coordinates.
        values: Optional per-point scalar driving color.
        on_select: Optional Reflex event handler for point selection.
        x_label: X axis label.
        y_label: Y axis label.
        height: Chart height in pixels.

    Returns:
        An ``rx.Component``.

    Raises:
        ValueError: If concrete ``x`` and ``y`` differ in length, or ``values``
            does not match them.
    """
    if _is_reactive(x) or _is_reactive(y):
        return _reactive_component(
            x, y, kind="scatter", x_label=x_label, y_label=y_label,
            height=height, on_select=on_select,
        )
    xs = _as_float_array(x)
    ys = _as_float_array(y)
    if xs.size != ys.size:
        raise ValueError(f"x has length {xs.size} but y has length {ys.size}")
    vs = None
    if values is not None:
        vs = _as_float_array(values)
        if vs.size != xs.size:
            raise ValueError(
                f"values has length {vs.size}, expected {xs.size}"
            )
    fig = _new_figure(x_label=x_label, y_label=y_label)
    if xs.size:
        _xy_scatter(fig, xs, ys, label="", color=PALETTE[0], values=vs)
    comp = _component(fig, height)
    if on_select is not None:
        comp = xyrx.chart(fig, height=f"{height}px", width="100%", on_select=on_select)
    return comp


def histogram_steps(values, *, bins: int = 100, value_range=None) -> tuple:
    """Bin ``values`` and return step-line coordinates.

    Public because reactive panels must bin in their ``pull`` — ``np.histogram``
    cannot run on an unevaluated Reflex var, so the panel binds the *binned*
    result rather than the raw samples.

    Args:
        values: Raw sample values. Non-finite entries are dropped.
        bins: Number of histogram bins.
        value_range: Optional ``(low, high)`` passed to ``np.histogram``.

    Returns:
        tuple: ``(step_x, step_y)`` float64 arrays tracing a density histogram
        as a step line. Both are empty when no finite samples remain.
    """
    arr = _as_float_array(values)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.empty(0), np.empty(0)
    counts, edges = np.histogram(arr, bins=bins, range=value_range, density=True)
    # Repeat each edge so the trace holds its value across the width of a bin.
    return np.repeat(edges, 2)[1:-1], np.repeat(counts, 2)


def histogram(
    values_by_label: dict,
    *,
    bins: int = 100,
    value_range=None,
    x_label: str = "",
    y_label: str = "density",
    height: int = 320,
):
    """Render one or more density histograms as step lines.

    xy 0.0.5 has no bar or quad primitive, so each histogram is computed with
    ``np.histogram(density=True)`` and drawn as a step line over the bin edges.
    This is a deliberate visual departure from the filled ``quad`` glyphs the
    Bokeh GP-simulator visualizer used.

    Args:
        values_by_label: Mapping of legend label to raw sample values.
        bins: Number of histogram bins.
        value_range: Optional ``(low, high)`` range passed to ``np.histogram``.
        x_label: X axis label.
        y_label: Y axis label.
        height: Chart height in pixels.

    Returns:
        An ``rx.Component``. Empty or all-non-finite series are skipped.

    Note:
        This is the **concrete-data** entry point only. ``np.histogram`` cannot
        run on an unevaluated Reflex var, so a live panel bins in its ``pull``
        with :func:`histogram_steps` and then binds the result through
        :func:`spectra` — a pre-binned step histogram is exactly a set of
        traces on a shared linear x axis. See ``gpsim_panel``.
    """
    fig = _new_figure(x_label=x_label, y_label=y_label)
    for idx, (label, values) in enumerate(values_by_label.items()):
        arr = _as_float_array(values)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        step_x, step_y = histogram_steps(arr, bins=bins, value_range=value_range)
        _xy_line(
            fig,
            step_x,
            step_y,
            label=f"{label} n={arr.size:d}",
            color=PALETTE[idx % len(PALETTE)],
        )
    return _component(fig, height)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_plots.py -v
```

Expected: 22 passed. If a test fails inside `_xy_line`, `_xy_scatter`, `_new_figure`, `_component`, or `_reactive_component`, the Task 0 note's recorded signature was not transcribed correctly — fix the helper, not the test. The four reactive tests are the ones that decide Branch A vs Branch B in `_reactive_component`; whichever branch makes them pass is the one to keep, and record that choice in the API note.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_plots.py
git add helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_plots.py
git commit -m "feat(reflex): add xy plot facade with time_series, spectra, scatter_map, histogram"
```

---

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
    """The facade is the single point of contact with the alpha xy API."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.rglob("*.py"):
        if "/.git/" in str(path) or "site-packages" in str(path):
            continue
        if path.name in ("plots.py", "test_reflex_plots.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^\s*(import xy\b|from xy\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"xy imported outside the facade: {offenders}"
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

from helao.core.servers.reflex.discovery import resolve_panel_module
from helao.core.servers.reflex.ingest import (
    VIS_KEY_TO_WS_PATH,
    IngestRegistry,
    set_registry,
)
from helao.core.servers.reflex.state import make_panel_state
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

    application = rx.App()

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
- Consumes: `LiveVisState`/`ActionVisState`/`make_panel_state` (Task 5), `plots` (Task 4), `WsIngest` (Task 2).
- Produces: three modules each exposing `WS_PATH`, `STATE_BASE`, and `build(server_key, state_cls)`.

**Design notes for the implementer:**
- `wssim_panel` is the straight port of `wssim_live_vis.py`: six `series_<i>` columns against `epoch`, plus a latest-value table. This one reads the numeric ring buffer.
- `oersim_panel` ports `oersim_vis.py` (an `ActionVisualizer` on `ws_data`).
- `gpsim_panel` ports `gpsim_live_vis.py` and is the awkward one: its payload carries per-plate arrays (`pred_avail`, `gt_acquired`) that do not fit a flat numeric column. It reads `ingest.raw` — the untransformed batches — and `ingest.rows` for the string table, and renders via `plots.histogram`. This is exactly why `WsIngest` keeps a raw deque.
- Each panel's `pull` must be cheap. It runs on the render timer with the state lock held.

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


def test_wssim_pull_reads_series_columns_from_the_buffer():
    import numpy as np

    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.buffer.append(
        {
            "epoch": [1.0, 2.0],
            "series_0": [10.0, 11.0],
            "series_1": [20.0, 21.0],
        }
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

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState

WS_PATH = "ws_live"

#: Column excluded from the plotted series set: it is the x axis.
X_COLUMN = "epoch"


def extract(ingest, window: int) -> dict:
    """Pull the x column and every other numeric column from the ring buffer.

    Args:
        ingest: The panel's :class:`WsIngest`.
        window: Number of trailing rows to read.

    Returns:
        dict: ``{"epoch": np.ndarray, "series": {name: np.ndarray}}``.
    """
    snap = ingest.buffer.snapshot(window)
    x = snap.get(X_COLUMN, np.empty(0))
    series = {k: v for k, v in snap.items() if k != X_COLUMN}
    return {"epoch": x, "series": series}


class _State(LiveVisState):
    """Panel-specific state: plot arrays and the latest-value table."""

    epoch: list = []
    series: dict = {}
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Copy the trailing window and latest values into state vars."""
        cols = extract(ingest, self.window_points)
        self.epoch = cols["epoch"].tolist()
        self.series = {k: v.tolist() for k, v in cols["series"].items()}
        self.table_rows = [
            [name, f"{values[-1]:.6g}"]
            for name, values in cols["series"].items()
            if values.size
        ]


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
            rx.cond(state_cls.error != "", rx.text(state_cls.error, color_scheme="red")),
            plots.time_series(
                state_cls.epoch,
                state_cls.series,
                x_label="Time (HH:MM:SS)",
                y_label="value",
            ),
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


STATE_BASE = _State
```

The chart binds to `state_cls.epoch` and `state_cls.series`, not to arrays: the facade's `_is_reactive` path (Task 4) hands the vars straight to the xy adapter so the chart re-renders each time `pull` assigns new data. If Task 4 settled on Branch B of `_reactive_component`, add a `chart_spec` computed var to `_State` and pass that instead:

```python
    @rx.var
    def chart_spec(self) -> dict:
        """Chart payload for adapters that take a single spec object."""
        return {"x": self.epoch, "series": self.series, "kind": "line"}
```

```python
# helao/deploy/test/servers/reflex/oersim_panel.py
"""Reflex panel for the OER simulator's per-action data stream.

Reflex port of ``servers/visualizer/oersim_vis.py``. Subscribes to ``ws_data``
and renders the action-scoped measurement scatter.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState

WS_PATH = "ws_data"

#: Columns the OER simulator publishes on ws_data. Mirrors oersim_vis.py.
X_COLUMN = "epoch"


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
    """Panel-specific state for the OER simulator."""

    x: list = []
    series: dict = {}

    def pull(self, ingest) -> None:
        """Copy the trailing window into state vars."""
        cols = extract(ingest, self.window_points)
        self.x = cols["x"].tolist()
        self.series = {k: v.tolist() for k, v in cols["series"].items()}


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
            rx.cond(state_cls.error != "", rx.text(state_cls.error, color_scheme="red")),
            plots.time_series(
                state_cls.x,
                state_cls.series,
                x_label="Time (HH:MM:SS)",
                y_label="value",
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
# helao/deploy/test/servers/reflex/gpsim_panel.py
"""Reflex panel for the GP simulator's live acquisition stream.

Reflex port of ``servers/visualizer/gpsim_live_vis.py``. This payload does not
fit the flat numeric-column model — it carries per-plate arrays
(``pred_avail``, ``gt_acquired``) and string columns (``orchestrator``,
``last_acquisition``) — so this panel reads the ingest layer's raw message
deque and row buffer rather than the numeric ring.

The Bokeh version drew filled ``quad`` histograms. xy 0.0.5 has no quad
primitive, so :func:`helao.core.servers.reflex.plots.histogram` renders step
lines instead. The information is the same; the fill is gone.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract_histograms"]

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
        plate_ids = plates[0]
        pred_vals = pred[0]
        acq_vals = acq[0]
        for i, plate_id in enumerate(plate_ids):
            if i < len(pred_vals):
                out[f"{plate_id} predicted"] = list(pred_vals[i])
            if i < len(acq_vals):
                out[f"{plate_id} acquired"] = list(acq_vals[i])
    return out


class _State(LiveVisState):
    """Panel-specific state: binned histogram traces and the acquisitions table.

    Binning happens here rather than in the chart because ``np.histogram``
    cannot run on an unevaluated Reflex var. Every series shares the same bins
    and range, so the result is a set of step traces on one linear x axis —
    which is exactly what :func:`plots.spectra` renders.
    """

    hist_x: list = []
    hist_series: dict = {}
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Bin the latest per-plate samples and refresh the acquisitions table."""
        shared_x: list = []
        series: dict = {}
        for label, values in extract_histograms(ingest).items():
            step_x, step_y = plots.histogram_steps(
                values, bins=HIST_BINS, value_range=HIST_RANGE
            )
            if step_y.size == 0:
                continue
            if not shared_x:
                shared_x = step_x.tolist()
            series[f"{label} n={len(values):d}"] = step_y.tolist()
        self.hist_x = shared_x
        self.hist_series = series
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
            rx.cond(state_cls.error != "", rx.text(state_cls.error, color_scheme="red")),
            plots.spectra(
                state_cls.hist_x,
                state_cls.hist_series,
                x_label="Eta (V vs O2/H2O)",
                y_label="density",
            ),
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

Note that `gpsim_panel` imports `plots` for `histogram_steps` in `pull` and `spectra` in `build` — it never calls `plots.histogram`, which exists for concrete-data callers and for the `hte` spectrometer panels a later spec will add.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_panels.py -v
```

Expected: 18 passed (7 from Task 5, 11 new — the two parametrized tests contribute three cases each).

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/test/servers/reflex/ helao/core/tests/test_reflex_panels.py
git add helao/deploy/test/servers/reflex helao/core/tests/test_reflex_panels.py
git commit -m "feat(reflex): add test deployment panels for wssim, oersim, and gpsim"
```

---

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

- [ ] **Step 5: Gitignore the bundle**

Append to `.gitignore`:

```
# Exported Reflex frontend bundle; built per-machine, shipped as a release
# artifact rather than tracked. See reflex_launcher.py.
.reflex-bundle/
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/core/tests/test_reflex_launcher.py -v
conda run -n helao python -m pytest helao/core/tests/test_launch_pid_verify.py -v
```

Expected: 10 passed in the first, all pass in the second.

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
cd helao/core/servers/reflex/_app
conda run -n helao reflex init --loglevel info
conda run -n helao reflex export --frontend-only
```

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
3. The time-series chart draws and **updates** — watch it for 30 seconds and confirm new points arrive.
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

- [ ] `conda run -n helao python run_tests.py --filter reflex` reports PASS for all seven `test_reflex_*.py` files.
- [ ] `conda run -n helao python run_unit_tests.py` passes.
- [ ] `conda run -n helao python run_tests.py` shows no new failures against the pre-branch baseline.
- [ ] `python launch.py goldenreflex` brings up the group, and every one of Task 10 Step 3's ten browser checks passes — including check 10, the Bokeh operator still working.
- [ ] The reconnection check in Task 10 Step 4 passes.
- [ ] `grep -rn "^\s*\(import xy\|from xy\)" --include="*.py" .` returns only `helao/core/servers/reflex/plots.py`.
- [ ] `docs/superpowers/notes/2026-08-01-xy-api-probe.md` contains real probe output with no unreplaced `<...>` placeholders.
- [ ] No private deployment is named in any tracked file added or modified by this plan.
- [ ] `black` has been run on every changed Python file.
- [ ] Work is committed on `feat/reflex-ui-stack`, not pushed, no PR opened.
