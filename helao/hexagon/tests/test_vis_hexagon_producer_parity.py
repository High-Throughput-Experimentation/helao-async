"""P7e task 5: a HEXAGON-hosted visualizer consuming HEXAGON-produced frames.

The Bokeh half of Amendment 1 gate item 1 asks for a *hexagon-hosted* vis
decoding byte-identical frames produced by a *hexagon* server. P7b proved two
thirds of that and left the join open:

* ``test_ws_consumer_parity.py`` proved the hexagon producer's *bytes* match
  the legacy producer's for one channel (``ws_status``), and
* the per-deployment ``test_vis_ws_parity.py`` suites proved the panels'
  ``add_points`` conform -- but fed them frames from the *legacy* encoder only.

Nothing yet drove a hexagon-produced frame into a panel, and nothing drove any
frame into a panel living inside a hexagon-composed document. Both are here:

1. :func:`test_panels_agree_on_hexagon_and_legacy_produced_frames` runs each
   panel's real ``add_points`` twice -- once over a legacy-produced frame, once
   over a hexagon-produced one -- and compares the resulting Bokeh data source
   column-for-column. Five panels, two deployments, both channels.
2. :func:`test_hexagon_hosted_document_panel_consumes_hexagon_frames` builds a
   document through the P7e graft (so ``makeVisApp``, ``build_wiring`` and
   ``VIS_REQUIRED`` all really run), points the action server it subscribes to
   at a replay server serving hexagon-produced frames, and lets the panel's own
   unmodified ``IOloop_data`` pull them in.
3. :func:`test_no_hexagon_orch_ws_producer_exists` and its neighbours pin the
   residual: there is no hexagon producer for the orchestrator's dict-shaped
   ``/ws_status``. See :func:`test_no_hexagon_orch_ws_producer_exists` for what
   breaks the day one appears.

Anti-vacuity, since a conformance loop over an empty panel set is the failure
mode this whole slice is prone to: :data:`PANELS` is size-asserted and required
to span both deployments and both channels; every comparison asserts the shared
result is *non-empty* before asserting the two sides are equal; and each
equality has a mutation twin proving it can fail.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from bokeh.document import Document
from bokeh.models import ColumnDataSource

from harness import ws_frames as wf

REPO_ROOT = Path(__file__).resolve().parents[3]
GRAFT_CONFIG = (
    REPO_ROOT / "helao" / "deploy" / "test" / "configs" / "goldenhexgraft.yml"
)
VIS_GRAFT = "helao.deploy.hexagon.servers.visualizer.graft"


# ---------------------------------------------------------------------------
# panel conformance matrix
# ---------------------------------------------------------------------------


class PanelSpec:
    """One panel, and the two payloads used to prove its ingest can differ.

    Attributes:
        module: Dotted path of the ``*_vis`` module.
        serv_key: Action server key the panel subscribes to.
        channel: ``ws_live`` or ``ws_data``.
        numeric: Payload the equality assertions are made over.
        numeric_alt: A *different* payload, for the mutation twin.
        source: Picks the Bokeh data source that ingest lands in.
        vis_params: The VIS server's own ``params`` block.
        action_params: The ACTION server's ``params`` block.
        action_name: ``ws_data`` only -- panels filter on it.
    """

    def __init__(
        self,
        module: str,
        serv_key: str,
        channel: str,
        numeric: dict,
        numeric_alt: dict,
        source: Callable[[Any], ColumnDataSource],
        vis_params: Optional[dict] = None,
        action_params: Optional[dict] = None,
        action_name: str = "",
    ):
        self.module = module
        self.serv_key = serv_key
        self.channel = channel
        self.numeric = numeric
        self.numeric_alt = numeric_alt
        self.source = source
        self.vis_params = vis_params or {}
        self.action_params = action_params or {}
        self.action_name = action_name

    @property
    def id(self) -> str:
        return self.module.rsplit(".", 1)[-1]


_TEST_VIS = "helao.deploy.test.servers.visualizer"
_HTE_VIS = "helao.deploy.hte.servers.visualizer"

#: The panels this file drives hexagon-produced frames into. Spans both
#: deployments, both channels, and both of the unrecognized-key tolerances the
#: P7b suites measured (unconditional-append vs. guarded), so the comparison is
#: not accidentally over one shape of panel.
PANELS = [
    PanelSpec(
        module=f"{_TEST_VIS}.wssim_live_vis",
        serv_key="SIM",
        channel="ws_live",
        numeric={f"series_{i}": float(i) for i in range(6)},
        numeric_alt={f"series_{i}": float(i) + 42.0 for i in range(6)},
        source=lambda v: v.datasource,
    ),
    PanelSpec(
        module=f"{_HTE_VIS}.co2_vis",
        serv_key="CO2",
        channel="ws_live",
        numeric={"co2_ppm": 410.0},
        numeric_alt={"co2_ppm": 911.0},
        source=lambda v: v.datasource,
    ),
    PanelSpec(
        module=f"{_TEST_VIS}.oersim_vis",
        serv_key="OERSIM",
        channel="ws_data",
        numeric={"t_s": [0.0, 1.0], "erhe_v": [0.1, 0.2]},
        numeric_alt={"t_s": [0.0, 1.0], "erhe_v": [0.7, 0.8]},
        source=lambda v: v.datasource,
        action_name="measure_cp",
    ),
    PanelSpec(
        module=f"{_HTE_VIS}.gamry_vis",
        serv_key="GAMRY0",
        channel="ws_data",
        numeric={"t_s": [0.0, 1.0], "I_A": [0.01, 0.02]},
        numeric_alt={"t_s": [0.0, 1.0], "I_A": [0.07, 0.08]},
        source=lambda v: v.datasource,
        vis_params={"num_channels": 1},
        action_name="run_CA",
    ),
    PanelSpec(
        module=f"{_HTE_VIS}.biologic_vis",
        serv_key="BIOLOGIC0",
        channel="ws_data",
        numeric={
            "channel": [0, 0],
            "t_s": [0.0, 1.0],
            "Ewe_V": [0.1, 0.2],
            "I_A": [0.01, 0.02],
        },
        numeric_alt={
            "channel": [0, 0],
            "t_s": [0.0, 1.0],
            "Ewe_V": [0.7, 0.8],
            "I_A": [0.01, 0.02],
        },
        source=lambda v: v.channel_datasources[0],
        vis_params={"num_channels": 1},
        action_name="run_CA",
    ),
]


class _FakeVis:
    """The three attributes ``VisSubscriber.__init__`` reads.

    Same double the P7b per-deployment suites use; repeated rather than
    imported because those live under two different deployment packages and
    neither is importable as a shared helper from here.
    """

    def __init__(self, doc, vis_params: dict, servers: dict):
        self.doc = doc
        self.server_cfg = {"params": vis_params}
        self.world_cfg = {"servers": servers}


def _build_panel(spec: PanelSpec):
    """Construct a panel and stop its ingest task before it opens a socket to
    a server that is not there."""
    module = import_module(spec.module)
    vis = module.C_vis(
        _FakeVis(
            Document(),
            spec.vis_params,
            {
                spec.serv_key: {
                    "host": "127.0.0.1",
                    "port": 8004,
                    "params": spec.action_params,
                }
            },
        ),
        spec.serv_key,
    )
    vis.IOloop_data_run = False
    vis.IOtask.cancel()
    return vis


async def _decoded(spec: PanelSpec, producer: str, numeric: dict):
    """One message for ``spec``'s channel, produced by ``producer`` and decoded
    through the real ``WsSubscriber`` -- the exact object
    ``VisSubscriber.IOloop_data`` hands ``add_points``."""
    if spec.channel == "ws_live":
        payload = wf.build_live_payload(numeric=numeric, strings={})
    else:
        payload = wf.build_data_payload(
            numeric=numeric,
            strings={wf.STRING_COLUMN: [wf.STRING_VALUES[0]] * 2},
            action_name=spec.action_name,
        )
    _, decoded = await wf.roundtrip(spec.channel, producer, payload=payload)
    return decoded


def _snapshot(source: ColumnDataSource) -> dict:
    """A comparable, order-preserving view of a data source's columns.

    ``ColumnDataSource.stream`` may hand back numpy arrays, which do not
    compare with ``==`` to a useful bool, so every column is listified.
    """
    return {k: list(v) for k, v in source.data.items()}


async def _ingest(spec: PanelSpec, producer: str, numeric: dict) -> dict:
    """Feed one ``producer``-produced message into a fresh panel and return
    what landed in its data source."""
    decoded = await _decoded(spec, producer, numeric)
    vis = _build_panel(spec)
    assert vis.connected, f"{spec.id} never resolved its server config"
    vis.add_points([decoded])
    return _snapshot(spec.source(vis))


def test_panel_matrix_is_not_vacuous():
    """The conformance loop below must actually span something.

    A loop over an empty (or single-shape) PANELS list is this slice's named
    failure mode, so the matrix is pinned by size AND by coverage of both
    deployments and both channels.
    """
    assert len(PANELS) == 5, [p.id for p in PANELS]
    assert len({p.id for p in PANELS}) == 5
    deployments = {p.module.split(".")[2] for p in PANELS}
    assert deployments == {"test", "hte"}, deployments
    assert {p.channel for p in PANELS} == {"ws_live", "ws_data"}
    for p in PANELS:
        assert hasattr(import_module(p.module).C_vis, "add_points"), p.id


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", PANELS, ids=lambda s: s.id)
async def test_panels_agree_on_hexagon_and_legacy_produced_frames(spec: PanelSpec):
    """The consumers agree on hexagon-produced bytes.

    P7b proved the two producers' bytes match; this proves the thing that
    actually matters downstream -- that the real ``add_points`` implementations
    reach the same plotted state either way. Each side gets its OWN panel
    instance, so a shared data source cannot manufacture the agreement.
    """
    legacy = await _ingest(spec, "base_api", spec.numeric)
    hexagon = await _ingest(spec, wf.HEXAGON, spec.numeric)

    # Non-emptiness first: two empty dicts are trivially equal, which is
    # exactly the vacuous pass this assertion order rules out.
    assert hexagon, f"{spec.id} ingested nothing at all"
    ingested = {k: v for k, v in hexagon.items() if v}
    assert ingested, f"{spec.id} produced only empty columns: {hexagon}"
    for column in spec.numeric:
        if column in hexagon:
            assert hexagon[column], f"{spec.id} left {column!r} empty"

    assert hexagon == legacy, (
        f"{spec.id} reached a different state from a hexagon-produced frame "
        f"than from a legacy-produced one\nlegacy:  {legacy}\nhexagon: {hexagon}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", PANELS, ids=lambda s: s.id)
async def test_panel_agreement_can_fail(spec: PanelSpec):
    """Mutation twin for the test above: a hexagon frame carrying a DIFFERENT
    payload must land differently. Without this, ``hexagon == legacy`` could be
    passing because the panel ignores its input entirely."""
    baseline = await _ingest(spec, wf.HEXAGON, spec.numeric)
    mutated = await _ingest(spec, wf.HEXAGON, spec.numeric_alt)
    assert mutated != baseline, (
        f"{spec.id} reached an identical state from two different payloads -- "
        "the equality assertion in the sibling test cannot fail"
    )


@pytest.mark.asyncio
async def test_hexagon_producer_is_the_base_api_wire_family_not_the_orch_one():
    """Which of the two encodings a hexagon action server speaks, discriminated
    by decoded type rather than by name.

    The bridge puts typed models on the fan-out queues, so its frames decode to
    ``ActionModel``/``DataPackageModel`` like ``base_api``'s -- never to the
    plain dicts ``_ws_relay`` sends. A panel written against one shape blanks
    silently on the other, so this is the property that makes the conformance
    above transferable to a station.
    """
    from helao.core.models.action import ActionModel
    from helao.core.models.data import DataPackageModel

    _, hex_status = await wf.roundtrip("ws_status", wf.HEXAGON)
    _, hex_data = await wf.roundtrip("ws_data", wf.HEXAGON)
    _, orch_status = await wf.roundtrip("ws_status", "orch_api")
    _, orch_data = await wf.roundtrip("ws_data", "orch_api")

    assert isinstance(hex_status, ActionModel), type(hex_status)
    assert isinstance(hex_data, DataPackageModel), type(hex_data)
    assert hex_status.action_uuid == wf.ACTION_UUID
    row = next(iter(hex_data.datamodel.data.values()))
    assert row[wf.NUMERIC_COLUMN] == wf.NUMERIC_VALUES

    # ... and the orch family really is the other shape, so the assertions
    # above discriminate rather than holding for everything.
    assert type(orch_status) is dict, type(orch_status)
    assert type(orch_data) is dict, type(orch_data)


# ---------------------------------------------------------------------------
# a hexagon-hosted document, consuming hexagon-produced frames
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_config(tmp_path, monkeypatch):
    """The P7e gate config with its root redirected into tmp_path."""
    from helao.helpers import config_loader
    from helao.helpers.config_loader import read_config

    cfg = copy.deepcopy(read_config(str(GRAFT_CONFIG)))
    cfg["root"] = str(tmp_path)
    monkeypatch.setattr(config_loader, "CONFIG", cfg)
    return cfg


def _drain_next_tick(doc: Document) -> int:
    """Run every queued next-tick callback, as a Bokeh session's IOLoop would.

    ``VisSubscriber.IOloop_data`` never calls ``add_points`` directly -- it
    hands it to ``doc.add_next_tick_callback`` so the mutation happens on the
    document thread. With no browser session attached there is no IOLoop to
    service that queue, so the test plays that one role and nothing else: the
    callback object, its payload and the panel method it invokes are all the
    production ones.

    Returns:
        How many callbacks were run.
    """
    ran = 0
    for cb in list(doc.callbacks.session_callbacks):
        doc.callbacks.remove_session_callback(cb)
        cb.callback()
        ran += 1
    return ran


def _find_source(doc: Document, column: str) -> ColumnDataSource:
    """The document's data source carrying ``column``.

    Found by walking the real model graph rather than by holding a reference to
    the panel object: ``live_visualizer`` discards what ``mount_visualizers``
    returns, and reaching past that with a spy would weaken the claim that this
    is the document a browser would get.
    """
    # `select` is typed as yielding bare Models, hence the isinstance narrowing
    # -- it is also what makes `.data` well-defined at every call site below.
    found = [
        m
        for m in doc.select({"type": ColumnDataSource})
        if isinstance(m, ColumnDataSource) and column in m.column_names
    ]
    assert found, (
        f"no ColumnDataSource in the grafted document carries {column!r} -- "
        "the panel did not mount"
    )
    assert len(found) == 1, f"{len(found)} sources carry {column!r}"
    return found[0]


async def _cancel_new_tasks(before):
    for task in asyncio.all_tasks() - before:
        task.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_hexagon_hosted_document_panel_consumes_hexagon_frames(
    real_config, tmp_path
):
    """The join P7e could not run: a hexagon-COMPOSED Bokeh document whose
    panel ingests frames a hexagon action server produced.

    Everything on the consuming side is production code: the generic P7e graft
    resolves its legacy target from config, ``makeVisApp`` builds the wiring and
    enforces ``VIS_REQUIRED``, the real ``live_visualizer`` mounts the real
    ``wssim_live_vis`` for ``SIM``, and that panel's own ``IOloop_data`` opens
    its own ``WsSubscriber`` and decodes what arrives. The only substitution is
    the action server itself, replaced by a replay server serving bytes the
    hexagon producer stack (``DispatcherStatusAdapter`` -> ``WsPublishBridge``
    -> ``WsPublisher.broadcast``) actually made.

    Two frames with different values are served, and both are asserted to land
    in order -- so "the panel consumed them" cannot be satisfied by a panel
    that merely mounted, nor by one that ingested a constant.
    """
    first = await wf.frame(
        "ws_live",
        wf.HEXAGON,
        payload=wf.build_live_payload(
            numeric={f"series_{i}": float(i) for i in range(6)}, strings={}
        ),
    )
    second = await wf.frame(
        "ws_live",
        wf.HEXAGON,
        payload=wf.build_live_payload(
            numeric={f"series_{i}": float(i) + 42.0 for i in range(6)}, strings={}
        ),
    )
    assert first != second, "the two frames are identical; ordering proves nothing"

    async with wf.replay_server({"ws_live": [first, second]}) as (host, port):
        # SIM is the only server in goldenhexgraft.yml declaring `live_vis`, so
        # this is the socket the mounted panel will subscribe to. Rewritten
        # BEFORE the graft builds, because VisSubscriber resolves host/port at
        # construction time.
        real_config["servers"]["SIM"]["host"] = host
        real_config["servers"]["SIM"]["port"] = port

        graft = import_module(VIS_GRAFT)
        before = asyncio.all_tasks()
        doc = Document()
        out = graft.makeBokehApp(
            doc,
            confPrefix="goldenhexgraft",
            server_key="LIVE",
            helao_repo_root=str(REPO_ROOT),
        )
        try:
            assert out is doc
            # composed, not hexagon in name only (P7e's property, restated here
            # because it is the premise of "hexagon-HOSTED")
            assert doc.hexagon_wiring is not None  # type: ignore[attr-defined]
            source = _find_source(doc, "series_0")
            assert list(source.data["series_0"]) == [], "panel started non-empty"

            ran = 0
            for _ in range(300):
                await asyncio.sleep(0.05)
                ran += _drain_next_tick(doc)
                if len(source.data["series_0"]) >= 2:
                    break

            assert ran, "the panel's IOloop_data never queued an add_points call"
            assert list(source.data["series_0"]) == [0.0, 42.0], _snapshot(source)
            assert list(source.data["series_5"]) == [5.0, 47.0], _snapshot(source)
            assert len(source.data["datetime"]) == 2
        finally:
            await _cancel_new_tasks(before)


@pytest.mark.asyncio
async def test_hexagon_hosted_document_ingest_can_fail(real_config, tmp_path):
    """Mutation twin for the document test: with the SIM socket pointed at a
    replay server that serves the OTHER channel's frames, the same document
    ingests nothing.

    Without this, "series_0 is non-empty" could be passing on a panel that
    fabricates rows regardless of the wire -- and the drain helper could be
    running callbacks that never carried a message.
    """
    wrong_channel = await wf.frame("ws_data", wf.HEXAGON)

    async with wf.replay_server({"ws_live": [wrong_channel]}) as (host, port):
        real_config["servers"]["SIM"]["host"] = host
        real_config["servers"]["SIM"]["port"] = port

        graft = import_module(VIS_GRAFT)
        before = asyncio.all_tasks()
        doc = Document()
        graft.makeBokehApp(
            doc,
            confPrefix="goldenhexgraft",
            server_key="LIVE",
            helao_repo_root=str(REPO_ROOT),
        )
        try:
            source = _find_source(doc, "series_0")
            rejected = False
            for _ in range(200):
                await asyncio.sleep(0.05)
                # wssim_live_vis iterates `datapackage.items()` and a
                # DataPackageModel has no .items -- the drained callback raises
                # rather than quietly adding a row, which is itself the proof
                # that a message really reached it.
                try:
                    _drain_next_tick(doc)
                except AttributeError:
                    rejected = True
                    break
            # Without this the "ingested nothing" assertion below would also
            # hold for a document that never received anything at all, which
            # would make this twin prove nothing about the sibling test.
            assert rejected, "the wrong-channel frame never reached add_points"
            assert list(source.data["series_0"]) == [], _snapshot(source)
        finally:
            await _cancel_new_tasks(before)


# ---------------------------------------------------------------------------
# the residual: no hexagon producer for the orchestrator's WS routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_hexagon_orch_ws_producer_exists(tmp_path, monkeypatch):
    """THE RESIDUAL for Amendment 1 gate item 1, pinned rather than papered over.

    ``ws_publish.py`` concedes it in prose ("orch WS stays on legacy relays,
    Q1"); this is the executable form. A hexagon-composed ORCHESTRATOR has a
    status adapter with no publish bridge bound, so every ``publish_*`` on it
    raises. Its ``/ws_status`` and ``/ws_data`` therefore have no hexagon
    producer at all -- they are served by the untouched legacy
    ``StatusBroadcaster._ws_relay``, which sends a DIFFERENT payload shape
    (dicts, not models) from the one the action-server bridge sends.

    ``test_factory.test_status_adapter_unbound_is_fail_loud`` asserts this of a
    bare adapter and says in its own docstring that the makeOrchApp side is
    "verified by code review"; this closes that with the composed app.

    The day a hexagon orch producer lands, this test fails -- deliberately.
    Binding a bridge in ``makeOrchApp`` breaks the two assertions below, and
    that failure is the signal to re-run the orch half of gate item 1 (the
    consumers of the dict shape -- ``RemoteBackend._ws_loop`` and every
    ``/ws_status`` subscriber -- have never been conformance-tested against a
    model-shaped frame).
    """
    from helao.helpers import config_loader
    from helao.hexagon.adapters.errors import UnwiredPortError
    from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
    from helao.hexagon.app import factory

    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "root": str(tmp_path),
            "dummy": True,
            "simulation": True,
            "servers": {
                "ORCH": {
                    "host": "127.0.0.1",
                    "port": 8901,
                    "group": "orchestrator",
                    "fast": "async_orch2",
                    "params": {},
                }
            },
        },
    )

    app = factory.makeOrchApp("ORCH")
    status = app.hexagon_wiring.status  # type: ignore[attr-defined]
    assert isinstance(status, DispatcherStatusAdapter)
    assert status._publish_bridge is None, (
        "a hexagon orch composition now binds a WS publish bridge -- the orch "
        "half of gate item 1 is no longer a known hole and must be tested"
    )
    assert not hasattr(
        app, "hexagon_ws_bridge"
    ), "makeOrchApp now carries a ws bridge attribute; see this test's docstring"
    with pytest.raises(UnwiredPortError):
        await status.publish_status(wf.build_status_payload().as_dict())

    # And the source-level twin, so the hole is visible without constructing an
    # app: the ONLY bind_publish_bridge call site in the composition root is in
    # makeActionApp.
    assert "bind_publish_bridge" not in inspect.getsource(factory.makeOrchApp)
    assert "bind_publish_bridge" in inspect.getsource(factory.makeActionApp)


@pytest.mark.asyncio
async def test_orch_channels_have_no_hexagon_equivalent_on_the_wire():
    """The residual, restated as a wire fact rather than a wiring fact.

    ``encode_hexagon`` cannot currently produce the shape an orch subscriber
    reads: for the two channels where the families diverge, the hexagon
    producer's frame decodes to a model and the orch relay's to a dict. So the
    conformance this file establishes covers action-server channels only, and
    an orch consumer gains nothing from it.
    """
    diverging = [c for c in wf.CHANNELS if c != "ws_live"]
    assert diverging == ["ws_status", "ws_data"], diverging
    for channel in diverging:
        _, hexagon = await wf.roundtrip(channel, wf.HEXAGON)
        _, orch = await wf.roundtrip(channel, "orch_api")
        assert type(hexagon) is not type(orch), (
            f"{channel}: the hexagon producer and the orch relay now agree on "
            "shape; a hexagon orch producer may have landed"
        )
        assert type(orch) is dict

    # ws_live is the one channel where they already agree (dict-native on both
    # sides), so the divergence above is channel-specific, not universal.
    _, hex_live = await wf.roundtrip("ws_live", wf.HEXAGON)
    _, orch_live = await wf.roundtrip("ws_live", "orch_api")
    assert type(hex_live) is type(orch_live) is dict
    assert hex_live == orch_live
