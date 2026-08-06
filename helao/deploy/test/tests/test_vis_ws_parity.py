"""P7b task 3: wire-consumer conformance for the `test` deployment's 3
`add_points` implementations, fed the decoded payload the real
`VisSubscriber.IOloop_data` would hand them, built from `harness/ws_frames`
(real encoder -> real WsSubscriber decoder, never a hand-built dict standing
in for the wire).

Two genuinely different behaviors are pinned here, not glossed over:

- `wssim_live_vis` (`LiveVisualizer`) initializes `data_dict = {k: [] for k in
  self.data_dict_keys}` then does an unconditional `data_dict[datalab].append`
  for every datalab in the message -- an unrecognized wire key is a
  `KeyError`, not a silent drop.
- `gpsim_live_vis` (`LiveVisualizer`) and `oersim_vis` (`ActionVisualizer`)
  both guard with `if datalab in self.data_dict_keys` (or an explicit `elif`
  chain with no `else`), so an unrecognized key is silently ignored.

A vacuity trap the plan calls out explicitly: a panel whose `add_points`
early-returns on an unrecognized *server key* (i.e. `self.connected` is
`False`) would pass any assertion trivially. Every test below asserts
`vis.connected` before touching `add_points`.

Run directly (`python -m pytest` on this file) -- deployment suites are not
part of `run_unit_tests.py`.
"""

import asyncio
import importlib

import pytest
from bokeh.document import Document

from harness import ws_frames as wf

SERV_KEY = "SIM"
SERVERS = {SERV_KEY: {"host": "127.0.0.1", "port": 8010}}


class _FakeVis:
    """The two attributes `VisSubscriber.__init__` reads, plus a document."""

    def __init__(self, doc, params=None):
        self.doc = doc
        self.server_cfg = {"params": params or {}}
        self.world_cfg = {"servers": SERVERS}


def _build(module, params=None):
    """Construct a visualizer and stop its ingest task before it opens a
    socket to a server that is not there (same recipe as
    helao/deploy/hte/tests/test_pstat_vis_axis_selectors.py)."""
    vis = module.C_vis(_FakeVis(Document(), params), SERV_KEY)
    vis.IOloop_data_run = False
    vis.IOtask.cancel()
    return vis


async def _decoded_live(numeric: dict, strings: dict | None = None) -> dict:
    """A ws_live message, round-tripped through the REAL base_api encoder and
    the REAL WsSubscriber decoder -- never a hand-built dict standing in for
    the wire."""
    payload = wf.build_live_payload(numeric=numeric, strings=strings or {})
    _, decoded = await wf.roundtrip("ws_live", "base_api", payload=payload)
    return decoded


async def _decoded_data(numeric: dict, strings: dict, action_name: str) -> object:
    """A ws_data message, round-tripped the same way, for the ActionVisualizer
    family."""
    payload = wf.build_data_payload(
        numeric=numeric, strings=strings, action_name=action_name
    )
    _, decoded = await wf.roundtrip("ws_data", "base_api", payload=payload)
    return decoded


def test_families_covered_are_non_empty():
    """Anti-vacuity guard: this file must actually exercise all 3 test-
    deployment add_points implementations found on disk."""
    modnames = ["wssim_live_vis", "gpsim_live_vis", "oersim_vis"]
    for name in modnames:
        mod = importlib.import_module(f"helao.deploy.test.servers.visualizer.{name}")
        assert hasattr(mod.C_vis, "add_points"), name
    assert len(modnames) == 3


def test_wssim_live_vis_ingests_recognized_numeric_series():
    module = importlib.import_module(
        "helao.deploy.test.servers.visualizer.wssim_live_vis"
    )

    async def _run():
        vis = _build(module)
        assert vis.connected
        before = len(vis.datasource.data["series_0"])
        # Bokeh's ColumnDataSource.stream requires every column update to be
        # the same length; real telemetry emits all 6 series per sample, so
        # feed all 6 rather than exercising a wire shape the panel never
        # actually receives.
        decoded = await _decoded_live({f"series_{i}": float(i) for i in range(6)})
        vis.add_points([decoded])
        assert len(vis.datasource.data["series_0"]) == before + 1
        assert vis.datasource.data["series_0"][-1] == 0.0

    asyncio.run(_run())


def test_wssim_live_vis_raises_on_unrecognized_datalab():
    """Measured, pinned characterization (a correction to the plan's implicit
    'never raises' assumption for the ws_live family): this panel's
    add_points has no guard for a datalab outside data_dict_keys."""
    module = importlib.import_module(
        "helao.deploy.test.servers.visualizer.wssim_live_vis"
    )

    async def _run():
        vis = _build(module)
        assert vis.connected
        decoded = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([decoded])

    asyncio.run(_run())


def test_gpsim_live_vis_tolerates_unrecognized_datalab():
    """Measured: gpsim_live_vis's if/elif chain has no else branch, so an
    unrecognized key is silently ignored rather than raising -- the opposite
    behavior from wssim_live_vis above, for the same wire shape."""
    module = importlib.import_module(
        "helao.deploy.test.servers.visualizer.gpsim_live_vis"
    )

    async def _run():
        vis = _build(module)
        assert vis.connected
        decoded = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        vis.add_points([decoded])  # must not raise

    asyncio.run(_run())


def test_gpsim_live_vis_ingests_recognized_numeric_row():
    """The full real payload shape gpsim_live_vis's add_points requires to
    produce any observable effect: plate_id/hist_dict must be present and
    aligned, or the histogram guard (`if "plate_id" in data_dict`) short-
    circuits and the table stream never runs -- a genuinely different
    'numeric row increases' contract from every other panel in this file."""
    module = importlib.import_module(
        "helao.deploy.test.servers.visualizer.gpsim_live_vis"
    )

    async def _run():
        vis = _build(module)
        assert vis.connected
        before = len(vis.datasource_table.data["plate_id"])
        payload = wf.build_live_payload(
            numeric={
                "plate_id": [0],
                "step": [1],
                "frac_acquired": [0.5],
                "last_acquisition": ["2026-08-05"],
                "orchestrator": ["orch1"],
                "pred_avail": [[0.3, 0.4, 0.5]],
                "gt_acquired": [[0.3, 0.4, 0.5]],
            },
            strings={},
        )
        _, decoded = await wf.roundtrip("ws_live", "base_api", payload=payload)
        vis.add_points([decoded])
        assert len(vis.datasource_table.data["plate_id"]) == before + 1
        assert vis.datasource_table.data["plate_id"][-1] == 0

    asyncio.run(_run())


def test_oersim_vis_ingests_recognized_numeric_columns_and_drops_string():
    """ActionVisualizer family: guarded by `if data_label in self.data_dict_keys`,
    so a non-numeric column outside that set (here: `composition`-shaped, via
    STRING_COLUMN) is silently dropped rather than raising -- matching the
    ws_data-family finding across all 4 hte ws_data panels too."""
    module = importlib.import_module("helao.deploy.test.servers.visualizer.oersim_vis")

    async def _run():
        vis = _build(module)
        assert vis.connected
        before = len(vis.datasource.data["t_s"])
        decoded = await _decoded_data(
            numeric={"t_s": [0.0, 1.0], "erhe_v": [0.1, 0.2]},
            strings={wf.STRING_COLUMN: [wf.STRING_VALUES[0]] * 2},
            action_name="measure_cp",
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data["t_s"]) == before + 2
        assert vis.datasource.data["erhe_v"][-2:] == [0.1, 0.2]
        assert wf.STRING_COLUMN not in vis.datasource.data

    asyncio.run(_run())


def test_oersim_vis_ignores_unrecognized_action_name():
    """The VALID_ACTION_NAME guard is real: an action_name outside
    ("measure_cp",) is filtered before any column is touched, so no row is
    added and nothing raises."""
    module = importlib.import_module("helao.deploy.test.servers.visualizer.oersim_vis")

    async def _run():
        vis = _build(module)
        assert vis.connected
        before = len(vis.datasource.data["t_s"])
        decoded = await _decoded_data(
            numeric={"t_s": [0.0], "erhe_v": [0.1]},
            strings={},
            action_name="not_measure_cp",
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data["t_s"]) == before

    asyncio.run(_run())


if __name__ == "__main__":
    test_families_covered_are_non_empty()
    test_wssim_live_vis_ingests_recognized_numeric_series()
    test_wssim_live_vis_raises_on_unrecognized_datalab()
    test_gpsim_live_vis_tolerates_unrecognized_datalab()
    test_gpsim_live_vis_ingests_recognized_numeric_row()
    test_oersim_vis_ingests_recognized_numeric_columns_and_drops_string()
    test_oersim_vis_ignores_unrecognized_action_name()
    print("ALL TEST_VIS_WS_PARITY TESTS PASS")
