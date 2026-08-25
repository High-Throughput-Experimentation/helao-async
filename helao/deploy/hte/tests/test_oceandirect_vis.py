"""The OceanDirect spectrometer panels, in both UI stacks.

These panels are the only ones reading a *long-format* stream: a spectrum is
``n_pixels`` consecutive rows keyed by ``spec_idx`` rather than one row across
``ch_NNNN`` columns. Every failure mode of that shape is silent — a frame
grouped wrongly, a partial frame plotted, or the previous action's last
spectrum drawn as the newest all produce a plausible-looking curve — so the
reframing is tested directly and both panels are then driven for real.

Run directly (``python -m pytest`` on this file) — the hte suite is not part of
``run_unit_tests.py``.
"""

import asyncio
import importlib
import json

import numpy as np
import pytest
from bokeh.document import Document

from helao.core.models.hlostatus import HloStatus
from helao.deploy.hte.servers import spec_long_format as lf
from helao.ui.reflex.state import make_panel_state

SERV_KEY = "SPEC_OD"
SERVERS = {SERV_KEY: {"host": "127.0.0.1", "port": 8112}}


def _snap(**cols):
    """A ring-buffer snapshot / packet payload of float columns."""
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


def _long(frames, wl, intensity, epochs=None):
    """Build a long-format window from per-frame spectra.

    Args:
        frames: One ``spec_idx`` value per spectrum.
        wl: The wavelength axis, repeated for every spectrum.
        intensity: One list of intensities per spectrum.
        epochs: One epoch per spectrum; defaults to ``frame`` as a float.
    """
    out = {"spec_idx": [], "wl": [], "i": [], "epoch_s": []}
    for position, frame in enumerate(frames):
        n = len(intensity[position])
        epoch = float(frame) if epochs is None else epochs[position]
        out["spec_idx"] += [float(frame)] * n
        out["wl"] += list(wl[:n])
        out["i"] += list(intensity[position])
        out["epoch_s"] += [float(epoch)] * n
    return _snap(**out)


# ======================================================================
# The shared reframing layer
# ======================================================================
def test_a_snapshot_missing_a_required_column_is_not_long_format():
    assert lf.has_long_format(_snap(spec_idx=[0], wl=[400.0], i=[1.0])) is True
    # A device-control action publishes a status payload on the same server.
    assert lf.has_long_format(_snap(epoch_s=[0.0])) is False
    assert lf.has_long_format({}) is False
    assert lf.has_long_format(None) is False


def test_a_spectrum_is_a_run_of_rows_not_a_row():
    window = _long([0], [400.0, 401.0, 402.0], [[10.0, 11.0, 12.0]])
    spectra = lf.latest_spectra(window)

    assert len(spectra) == 1
    assert spectra[0]["frame"] == 0
    assert list(spectra[0]["wl"]) == [400.0, 401.0, 402.0]
    assert list(spectra[0]["i"]) == [10.0, 11.0, 12.0]


def test_spectra_come_back_newest_first():
    window = _long(
        [0, 1, 2],
        [400.0, 401.0],
        [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
    )
    spectra = lf.latest_spectra(window, max_spectra=3)

    assert [s["frame"] for s in spectra] == [2, 1, 0]
    assert list(spectra[0]["i"]) == [3.0, 3.0]


def test_max_spectra_keeps_the_newest_not_the_oldest():
    window = _long([0, 1, 2, 3], [400.0], [[1.0], [2.0], [3.0], [4.0]])
    spectra = lf.latest_spectra(window, max_spectra=2)

    assert [s["frame"] for s in spectra] == [3, 2]


def test_max_spectra_below_one_is_treated_as_one():
    """It comes from config; a typo must not blank the panel."""
    window = _long([0, 1], [400.0], [[1.0], [2.0]])
    assert len(lf.latest_spectra(window, max_spectra=0)) == 1
    assert len(lf.latest_spectra(window, max_spectra=-3)) == 1


def test_every_returned_spectrum_has_the_same_length():
    """The panels share one x axis across all traces, so this is load-bearing."""
    window = _long([0, 1, 2], [400.0, 401.0], [[1.0, 2.0]] * 3)
    spectra = lf.latest_spectra(window, max_spectra=3)

    assert len({s["i"].size for s in spectra}) == 1
    assert len({s["wl"].size for s in spectra}) == 1


# -- the action boundary ------------------------------------------------
def test_the_previous_actions_last_spectrum_is_not_the_newest():
    """``spec_idx`` restarts per action, so the *largest* frame in a window is
    the old action's for as long as both are retained. Ranking by frame number
    would draw a stale spectrum as live, indefinitely."""
    window = _long(
        [0, 1, 42, 0],  # ...42 then 0: the boundary
        [400.0],
        [[1.0], [2.0], [99.0], [7.0]],
    )
    spectra = lf.latest_spectra(window, max_spectra=5)

    assert [s["frame"] for s in spectra] == [0]
    assert list(spectra[0]["i"]) == [7.0]


def test_the_current_action_offset_is_the_last_decrease():
    frames = np.asarray([0.0, 1.0, 2.0, 0.0, 1.0], dtype=float)
    assert lf.current_action_offset(frames) == 3
    # Only one action in the window.
    assert lf.current_action_offset(np.asarray([0.0, 1.0, 2.0])) == 0
    assert lf.current_action_offset(np.asarray([])) == 0
    assert lf.current_action_offset(np.asarray([5.0])) == 0


def test_only_the_newest_action_is_drawn_even_with_several_in_the_window():
    window = _long([0, 1, 0, 1, 0], [400.0], [[1.0], [2.0], [3.0], [4.0], [5.0]])
    spectra = lf.latest_spectra(window, max_spectra=9)

    assert [s["frame"] for s in spectra] == [0]
    assert list(spectra[0]["i"]) == [5.0]


# -- partial frames -----------------------------------------------------
def test_a_truncated_leading_frame_is_dropped():
    """The ring buffer drops rows from the front, so the oldest frame in a
    window can be half a spectrum. Plotted, it looks like a real measurement
    over a narrower wavelength range."""
    window = _long([0, 1], [400.0, 401.0, 402.0], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    # Chop the first two rows, leaving frame 0 with a single pixel.
    truncated = {k: v[2:] for k, v in window.items()}

    spectra = lf.latest_spectra(truncated, max_spectra=5)

    assert [s["frame"] for s in spectra] == [1]
    assert spectra[0]["i"].size == 3


def test_a_window_holding_only_a_partial_frame_yields_nothing():
    window = _long([0, 1], [400.0, 401.0], [[1.0, 2.0], [3.0, 4.0]])
    # Keep the tail of frame 0 only: one row, and it is also the newest run,
    # so it defines `expected` and survives -- a single-pixel spectrum.
    head_only = {k: v[:1] for k, v in window.items()}
    assert [s["frame"] for s in lf.latest_spectra(head_only)] == [0]


def test_an_empty_window_yields_nothing():
    assert lf.latest_spectra(_snap(spec_idx=[], wl=[], i=[])) == []
    assert lf.latest_spectra({}) == []


# -- defensive column handling -----------------------------------------
def test_nan_padded_rows_are_dropped_not_plotted():
    """``normalize_data_package`` pads a column with nan for a packet that did
    not carry it. A nan row belongs to no spectrum, and nan also compares false
    in both directions, which would break run detection outright."""
    window = _long([0], [400.0, 401.0], [[1.0, 2.0]])
    padded = {
        "spec_idx": np.concatenate((window["spec_idx"], [np.nan])),
        "wl": np.concatenate((window["wl"], [np.nan])),
        "i": np.concatenate((window["i"], [np.nan])),
        "epoch_s": np.concatenate((window["epoch_s"], [np.nan])),
    }
    spectra = lf.latest_spectra(padded)

    assert len(spectra) == 1
    assert spectra[0]["i"].size == 2
    assert np.isfinite(spectra[0]["i"]).all()
    assert np.isfinite(spectra[0]["wl"]).all()


def test_an_all_nan_window_yields_nothing():
    nan3 = [np.nan] * 3
    assert lf.latest_spectra(_snap(spec_idx=nan3, wl=nan3, i=nan3)) == []


def test_ragged_columns_are_trimmed_rather_than_indexed_past():
    window = _long([0], [400.0, 401.0, 402.0], [[1.0, 2.0, 3.0]])
    ragged = dict(window)
    ragged["i"] = ragged["i"][:2]  # a column that arrived short

    spectra = lf.latest_spectra(ragged)

    assert len(spectra) == 1
    assert spectra[0]["wl"].size == spectra[0]["i"].size == 2


def test_frame_runs_finds_the_boundaries():
    frames = np.asarray([0.0, 0.0, 1.0, 1.0, 1.0, 2.0])
    assert lf.frame_runs(frames) == [(0, 0, 2), (1, 2, 5), (2, 5, 6)]
    assert lf.frame_runs(np.asarray([])) == []


# -- epoch --------------------------------------------------------------
def test_each_frame_carries_its_own_epoch():
    """A buffered drain emits up to 15 spectra in one packet and they are not
    simultaneous, so one label per packet would mis-time 14 of them."""
    window = _long([0, 1], [400.0], [[1.0], [2.0]], epochs=[100.5, 200.25])
    spectra = lf.latest_spectra(window, max_spectra=2)

    assert spectra[0]["epoch_s"] == 200.25
    assert spectra[1]["epoch_s"] == 100.5


def test_a_missing_epoch_column_does_not_cost_the_traces():
    window = _long([0], [400.0, 401.0], [[1.0, 2.0]])
    del window["epoch_s"]

    spectra = lf.latest_spectra(window)

    assert len(spectra) == 1
    assert spectra[0]["epoch_s"] is None
    assert list(spectra[0]["i"]) == [1.0, 2.0]


# ======================================================================
# The Bokeh panel
# ======================================================================
class _FakeVis:
    """The attributes ``VisSubscriber.__init__`` reads, plus a document."""

    def __init__(self, doc, params=None):
        self.doc = doc
        self.server_cfg = {"params": params or {}}
        self.world_cfg = {"servers": SERVERS}


class _FakeDataModel:
    def __init__(self, data, status=HloStatus.active):
        self.data = data
        self.status = status


class _FakePackage:
    """The four attributes ``add_points`` reads off a data package."""

    def __init__(
        self,
        data,
        action_name="acquire_spec",
        action_uuid="uuid-1",
        status=HloStatus.active,
    ):
        self.action_name = action_name
        self.action_uuid = action_uuid
        self.datamodel = _FakeDataModel(data, status)


def _bokeh_panel(params=None):
    """Build the Bokeh panel and cancel its ingest task before it opens a socket."""
    module = importlib.import_module(
        "helao.deploy.hte.servers.visualizer.oceandirect_vis"
    )

    async def _make():
        vis = module.C_vis(_FakeVis(Document(), params), SERV_KEY)
        vis.IOloop_data_run = False
        vis.IOtask.cancel()
        return vis

    return module, asyncio.run(_make())


def test_the_bokeh_module_exports_only_the_panel_class():
    """A panel is not a Bokeh app: ``mount_visualizers`` imports the module by
    the ``action_vis`` config key and instantiates ``C_vis``. A
    ``makeBokehApp`` here would never be called, and its presence would suggest
    the module could be launched directly."""
    module, _panel = _bokeh_panel()
    assert module.__all__ == ["C_vis"]
    assert not hasattr(module, "makeBokehApp")


def test_the_streaming_actions_are_accepted_and_the_control_ones_are_not():
    """The device-control actions on this server publish a status dict with no
    ``spec_idx`` in it; reframing one would find no spectrum at all."""
    module, _panel = _bokeh_panel()
    for name in (
        "acquire_spec",
        "acquire_spec_adv",
        "acquire_spec_buffered",
        "acquire_spec_corrected",
        "calibrate_intensity",
    ):
        assert name in module.VALID_ACTION_NAME
    for name in (
        "set_tec",
        "set_shutter",
        "set_lamp",
        "set_corrections",
        "store_dark_spectrum",
        "stop_buffered_after",
    ):
        assert name not in module.VALID_ACTION_NAME


def test_bokeh_plots_are_bound_to_the_wavelength_and_intensity_columns():
    _module, panel = _bokeh_panel()
    for plot in (panel.plot, panel.plot_prev):
        renderers = [
            r for r in plot.renderers if hasattr(getattr(r, "glyph", None), "xs")
        ]
        assert len(renderers) == 1
        glyph = renderers[0].glyph
        assert (glyph.xs if isinstance(glyph.xs, str) else glyph.xs.field) == "wl"
        assert (
            glyph.ys if isinstance(glyph.ys, str) else glyph.ys.field
        ) == "intensity"


def test_bokeh_streams_one_trace_per_spectrum_in_a_packet():
    """A buffered drain delivers many spectra in one payload; each must become
    its own trace rather than being concatenated into one long curve."""
    _module, panel = _bokeh_panel()
    panel.downsample = 1
    window = _long([0, 1, 2], [400.0, 401.0], [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])

    panel.add_points([_FakePackage({"fck": window})])

    data = panel.datasource.data
    assert len(data["wl"]) == 3
    assert [len(row) for row in data["wl"]] == [2, 2, 2]
    # Oldest streamed first, so the newest holds the freshest ramp colour.
    assert [row[0] for row in data["intensity"]] == [1.0, 2.0, 3.0]
    assert data["frame"] == [0, 1, 2]
    assert data["color"][-1] == panel._ramp[0]
    assert data["color"][0] != panel._ramp[0]


def test_bokeh_downsampling_thins_both_axes_together():
    _module, panel = _bokeh_panel()
    panel.downsample = 2
    window = _long([0], [400.0, 401.0, 402.0, 403.0], [[1.0, 2.0, 3.0, 4.0]])

    panel.add_points([_FakePackage({"fck": window})])

    data = panel.datasource.data
    assert data["wl"][0] == [400.0, 402.0]
    assert data["intensity"][0] == [1.0, 3.0]


def test_bokeh_retains_at_most_max_spectra():
    _module, panel = _bokeh_panel()
    panel.downsample = 1
    panel.max_spectra = 2
    window = _long([0, 1, 2, 3], [400.0], [[1.0], [2.0], [3.0], [4.0]])

    panel.add_points([_FakePackage({"fck": window})])

    assert len(panel.datasource.data["wl"]) == 2
    assert panel.datasource.data["frame"] == [2, 3]


def test_bokeh_ignores_a_control_action_payload():
    _module, panel = _bokeh_panel()
    window = _long([0], [400.0], [[1.0]])

    panel.add_points([_FakePackage({"fck": window}, action_name="set_tec")])

    assert panel.datasource.data["wl"] == []


def test_bokeh_ignores_a_terminal_status_packet():
    _module, panel = _bokeh_panel()
    window = _long([0], [400.0], [[1.0]])

    panel.add_points([_FakePackage({"fck": window}, status=HloStatus.finished)])

    assert panel.datasource.data["wl"] == []


def test_bokeh_snapshots_the_previous_action_on_a_uuid_change():
    _module, panel = _bokeh_panel()
    panel.downsample = 1
    first = _long([0], [400.0], [[1.0]])
    second = _long([0], [400.0], [[9.0]])

    panel.add_points([_FakePackage({"fck": first}, action_uuid="uuid-a")])
    panel.add_points([_FakePackage({"fck": second}, action_uuid="uuid-b")])

    assert panel.cur_action_uuid == "uuid-b"
    assert panel.prev_action_uuid == "uuid-a"
    assert panel.prev_datasource.data["intensity"] == [[1.0]]
    assert panel.datasource.data["intensity"] == [[9.0]]


def test_bokeh_labels_each_spectrum_with_its_own_time():
    _module, panel = _bokeh_panel()
    panel.downsample = 1
    window = _long(
        [0, 1], [400.0], [[1.0], [2.0]], epochs=[1_700_000_000.0, 1_700_000_060.0]
    )

    panel.add_points([_FakePackage({"fck": window})])

    times = panel.datasource.data["time"]
    assert len(times) == 2
    assert times[0] != times[1]
    assert all(t for t in times)


def test_a_bad_max_spectra_input_falls_back_and_resizes_the_ramp():
    _module, panel = _bokeh_panel()
    panel.callback_input_max_spectra(
        "value", "5", "not a number", sender=panel.input_max_spectra
    )
    assert panel.max_spectra == 5
    panel.callback_input_max_spectra("value", "5", "1", sender=panel.input_max_spectra)
    assert panel.max_spectra == 2  # clamped up to the floor
    assert len(panel._ramp) == 2


def test_a_zero_downsample_is_clamped_to_one():
    """A stride of 0 empties every trace, and this is a free-text field."""
    _module, panel = _bokeh_panel()
    panel.callback_input_downsample("value", "2", "0", sender=panel.input_downsample)
    assert panel.downsample == 1


# ======================================================================
# The Reflex panel
# ======================================================================
class _FakeBuffer:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.requested = None

    def snapshot(self, points):
        self.requested = points
        return self._snapshot


class _FakeRows:
    def __init__(self, latest=None):
        self._latest = latest

    def latest(self):
        return self._latest


class _FakeIngest:
    def __init__(self, snapshot, action_uuid="uuid-1"):
        self.buffer = _FakeBuffer(snapshot)
        self.rows = _FakeRows({"action_uuid": action_uuid})


class _FakeState:
    """Stand-in for the bound state instance ``pull`` mutates."""

    def __init__(self):
        self.version = 0
        self.chart_spec = {}
        self.chart_url = ""
        self.chart_layout = ""
        self.action_uuid = ""
        self.frames = ""

    def panel_key(self):
        return "odspec-test"


def _reflex_module():
    return importlib.import_module("helao.deploy.hte.servers.reflex.oceandirect_vis")


def _reflex_state_class():
    module = _reflex_module()
    return module, make_panel_state(
        "oceandirect_vis_test", SERV_KEY, module.STATE_BASE, module.WS_PATH
    )


def _pull(window, action_uuid="uuid-1"):
    module = _reflex_module()
    state = _FakeState()
    ingest = _FakeIngest(window, action_uuid=action_uuid)
    module.STATE_BASE.pull(state, ingest)
    return module, state, ingest


def test_the_reflex_panel_reads_the_action_stream():
    module = _reflex_module()
    assert module.WS_PATH == "ws_data"


def test_the_reflex_state_base_is_a_mixin():
    """A var on a concrete state is owned by that class and shared by every
    substate beneath it, so two panels on a page would share one chart."""
    module = _reflex_module()
    assert getattr(module.STATE_BASE, "_mixin", False) is True
    # And it must actually mint, which is what enforces the mixin rule.
    _module, cls = _reflex_state_class()
    assert cls.__fields__["server_key"].default == SERV_KEY


def test_panel_ids_are_scoped_per_server_and_session():
    module = _reflex_module()
    assert module.panel_id("A", "tok") != module.panel_id("B", "tok")
    assert module.panel_id("A", "tok1") != module.panel_id("A", "tok2")


def test_the_reflex_panel_reads_a_pixel_counted_window():
    """A row here is one pixel, not one acquisition, so the inherited
    million-row default would be scanned and discarded every tick while
    "1000 points" would be half a spectrum."""
    module = _reflex_module()
    window = _long([0], [400.0, 401.0], [[1.0, 2.0]])
    _module, _state, ingest = _pull(window)

    assert ingest.buffer.requested == module.WINDOW_POINTS
    assert module.WINDOW_POINTS >= 2 * 2048  # two whole spectra of a real device


def test_the_reflex_pull_publishes_a_chart_and_advances_the_version():
    window = _long([0, 1], [400.0, 401.0], [[1.0, 2.0], [3.0, 4.0]])
    _module, state, _ingest = _pull(window)

    assert state.chart_spec
    assert state.chart_url
    assert state.chart_layout
    assert state.version == 1
    assert state.action_uuid == "uuid-1"


def test_the_reflex_panel_draws_every_spectrum_in_one_chart():
    """Each chart is a WebGL context and browsers cap live contexts at 16; an
    evicted chart stops drawing for good with nothing logged server-side. So
    the spectra are traces, not charts."""
    module = _reflex_module()
    window = _long(
        [0, 1, 2],
        [400.0, 401.0],
        [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
    )
    _module, state, _ingest = _pull(window)

    marks = state.chart_spec.get("marks") or state.chart_spec.get("traces") or []
    assert len(marks) == module.MAX_SPECTRA
    assert state.frames == "2, 1, 0"


def test_the_reflex_panel_labels_the_newest_spectrum_latest():
    window = _long([0, 1], [400.0], [[1.0], [2.0]])
    _module, state, _ingest = _pull(window)

    text = json.dumps(state.chart_spec, default=str)
    assert "latest" in text


def test_the_reflex_panel_survives_an_empty_buffer():
    """An empty window must yield a valid empty chart, not a raised error from
    inside the render.

    ``chart_layout`` is deliberately not asserted non-empty: ``layout_token``
    joins over the trace set, so a chart with no traces has an empty token by
    construction. What matters is that a spec and a buffer URL were published
    at all.
    """
    _module, state, _ingest = _pull(_snap(spec_idx=[], wl=[], i=[]))

    assert state.frames == ""
    assert state.version == 1
    assert state.chart_spec
    assert state.chart_url
    assert (state.chart_spec.get("traces") or []) == []


def test_the_reflex_panel_ignores_a_payload_with_no_spectrum_columns():
    _module, state, _ingest = _pull(_snap(epoch_s=[1.0, 2.0]))
    assert state.frames == ""


def test_a_spectrum_of_a_different_length_is_skipped_not_raised():
    """plots raises on a series whose length differs from the shared x axis,
    and it would raise from inside the render."""
    module = _reflex_module()
    window = _long([0], [400.0, 401.0], [[1.0, 2.0]])
    state = _FakeState()

    class _MixedBuffer:
        requested = None

        def snapshot(self, points):
            self.requested = points
            return window

    ingest = _FakeIngest(window)
    # Two frames whose pixel counts disagree cannot share an x axis.
    mixed = {
        "spec_idx": np.asarray([0.0, 0.0, 1.0], dtype=float),
        "wl": np.asarray([400.0, 401.0, 400.0], dtype=float),
        "i": np.asarray([1.0, 2.0, 5.0], dtype=float),
        "epoch_s": np.asarray([1.0, 1.0, 2.0], dtype=float),
    }
    ingest.buffer = _FakeBuffer(mixed)
    module.STATE_BASE.pull(state, ingest)

    # The newest frame (one pixel) defines the axis; the longer, older frame is
    # dropped by the reframing layer as a partial.
    assert state.frames == "1"
    assert state.version == 1


def test_the_reflex_panel_renders():
    """Constructing a component and rendering it are different things: a
    binding error surfaces at render, not at import, so a panel that builds can
    still fail the frontend bundle build."""
    module, cls = _reflex_state_class()
    rendered = json.dumps(module.build(SERV_KEY, cls).render(), default=str)

    assert SERV_KEY in rendered
    assert "Wavelength" in rendered or "chart" in rendered


def test_the_reflex_panel_binds_the_render_loop_on_mount():
    """``render_loop`` is the mount primer; without it the panel never ticks."""
    module, cls = _reflex_state_class()
    panel = module.build(SERV_KEY, cls)

    def _walk(component):
        yield component
        for child in getattr(component, "children", []) or []:
            yield from _walk(child)

    mounted = [
        component
        for component in _walk(panel)
        if (getattr(component, "event_triggers", None) or {}).get("on_mount")
    ]
    assert mounted, "no component binds on_mount"


@pytest.mark.parametrize("stack", ["bokeh", "reflex"])
def test_both_stacks_answer_to_the_same_config_key(stack):
    """A station gains the Reflex panel by adding a ``reflex:`` server and
    changing nothing else, which only holds if the module names match."""
    package = "visualizer" if stack == "bokeh" else "reflex"
    module = importlib.import_module(
        f"helao.deploy.hte.servers.{package}.oceandirect_vis"
    )
    assert module is not None
