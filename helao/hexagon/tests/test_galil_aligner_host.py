"""GalilAlignerHost + AlignerMotorContext tests (P3a galil-split slice-4).

Linux construct-test tier ONLY. The D6 extraction moves the Bokeh aligner
Server + HelaoVis + the aligner-session Active OUT of the Galil driver into
this vis-layer host. Real behavior (Bokeh session, live plate alignment) is an
at-station gate; these tests prove the seam is wired correctly:

- The context delegates motion/transform/calibration + the driver-owned
  `blocked`/`motor_busy` flags to the driver, and owns the aligner-session
  state (`base`/`aligner_active`/`aligner_plateid`/`aligning_enabled`/`aligner`).
- The context exposes EVERY `motor.*` name `layouts/aligner.py` reaches for, so
  the near-untouched aligner keeps resolving against the context.
- The host's orchestration verbs (`run_aligner_precheck`/`start_aligner_run`/
  `stop_aligner`/`shutdown`) reproduce the legacy driver semantics.
- The legacy driver has genuinely shed the D6 surface.
"""

import asyncio

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.vis.galil_aligner_host import (
    AlignerMotorContext,
    GalilAlignerHost,
)


class _FakeDriver:
    """Records delegation; stands in for the legacy Galil (no gclib)."""

    def __init__(self):
        self.blocked = False
        self.motor_busy = False
        self.galil_enabled = True
        self.transform = object()
        self.dflt_matrix = "DFLT"
        self.plate_transfermatrix = "PTM"
        self._position_sink = None
        self.calls = []

    async def _motor_move(self, *a, **k):
        self.calls.append(("_motor_move", a, k))
        return {"err_code": 0}

    async def query_axis_position(self, *a, **k):
        self.calls.append(("query_axis_position", a, k))
        return {"position": [0.0]}

    async def query_axis_moving(self, *a, **k):
        self.calls.append(("query_axis_moving", a, k))
        return {"motor_status": ["stopped"]}

    def update_plate_transfermatrix(self, *a, **k):
        self.calls.append(("update_plate_transfermatrix", a, k))
        return "NEWPTM"

    def save_transfermatrix(self, *a, **k):
        self.calls.append(("save_transfermatrix", a, k))

    def get_all_axis(self):
        return ["x", "y"]

    def set_position_sink(self, sink):
        self._position_sink = sink


class _FakeAction:
    def __init__(self, plateid):
        self.action_params = {"plateid_or_pmpath": plateid}

    def as_dict(self):
        return {"plateid": self.action_params["plateid_or_pmpath"]}


class _FakeActive:
    def __init__(self, plateid=6353):
        self.action = _FakeAction(plateid)


def _ctx():
    d = _FakeDriver()
    return AlignerMotorContext(d, base="BASE"), d


# --------------------------------------------------------------------------
# Context: ownership vs delegation
# --------------------------------------------------------------------------
def test_context_owns_aligner_session_state():
    ctx, _ = _ctx()
    assert ctx.base == "BASE"
    assert ctx.aligner_active is None
    assert ctx.aligner_plateid is None
    assert ctx.aligning_enabled is False
    assert ctx.aligner is None


def test_context_delegates_flags_to_driver():
    ctx, d = _ctx()
    ctx.blocked = True
    assert d.blocked is True and ctx.blocked is True
    d.motor_busy = True
    assert ctx.motor_busy is True  # read reflects live driver state
    ctx.motor_busy = False
    assert d.motor_busy is False


def test_context_delegates_transform_and_calibration():
    ctx, d = _ctx()
    assert ctx.transform is d.transform
    assert ctx.dflt_matrix == "DFLT"
    assert ctx.plate_transfermatrix == "PTM"
    assert ctx.update_plate_transfermatrix(newtransfermatrix="M") == "NEWPTM"
    ctx.save_transfermatrix(file="f")
    assert asyncio.run(ctx._motor_move(d_mm=[1, 2])) == {"err_code": 0}
    assert asyncio.run(ctx.query_axis_position(axis=["x"])) == {"position": [0.0]}
    assert [c[0] for c in d.calls] == [
        "update_plate_transfermatrix",
        "save_transfermatrix",
        "_motor_move",
        "query_axis_position",
    ]


def test_context_exposes_full_aligner_motor_surface():
    """Guard: the context must expose every `motor.*` name aligner.py uses
    (coupling map, 2026-07-22). A missing name would AttributeError only at
    at-station runtime, so pin it here."""
    ctx, _ = _ctx()
    required = [
        # motion
        "_motor_move",
        "query_axis_position",
        # transform
        "transform",
        # calibration / matrix state
        "plate_transfermatrix",
        "dflt_matrix",
        "update_plate_transfermatrix",
        "save_transfermatrix",
        # base reach-through
        "base",
        # active reach-through
        "aligner_active",
        # flags / ids / back-ref
        "aligning_enabled",
        "motor_busy",
        "blocked",
        "aligner_plateid",
        "aligner",
    ]
    for name in required:
        assert hasattr(ctx, name), f"context missing motor.{name}"


# --------------------------------------------------------------------------
# Host: orchestration verbs (no Bokeh)
# --------------------------------------------------------------------------
def _host():
    d = _FakeDriver()
    h = GalilAlignerHost(
        driver=d,
        base="BASE",
        server_cfg={"host": "127.0.0.1", "port": 8003},
        server_name="MOTOR",
        config={"enable_aligner": True},
    )
    return h, d


def test_precheck_not_available_before_bokeh_start():
    h, _ = _host()
    # bokehapp is None until start(); precheck must report not_available
    ok, code = h.run_aligner_precheck()
    assert ok is False and code == ErrorCodes.not_available


def test_precheck_in_progress_when_blocked_or_disabled():
    h, d = _host()
    d.blocked = True
    ok, code = h.run_aligner_precheck()
    assert ok is False and code == ErrorCodes.in_progress
    d.blocked = False
    d.galil_enabled = False
    ok, code = h.run_aligner_precheck()
    assert ok is False and code == ErrorCodes.in_progress


def test_precheck_ok_when_bokeh_and_aligner_present():
    h, _ = _host()
    h.bokehapp = object()  # simulate started server
    h.context.aligner = object()  # simulate constructed Aligner
    ok, code = h.run_aligner_precheck()
    assert ok is True and code == ErrorCodes.none


def test_start_aligner_run_sets_session_state_and_returns_dict():
    h, d = _host()
    active = _FakeActive(plateid=1234)
    result = asyncio.run(h.start_aligner_run(active))
    assert d.blocked is True  # driver-owned lock engaged
    assert h.context.aligner_active is active
    assert h.context.aligner_plateid == 1234
    assert h.context.aligning_enabled is True
    assert result == {"plateid": 1234}
    # kicks off a motion-status query (legacy parity)
    assert ("query_axis_moving", (), {"axis": ["x", "y"]}) in d.calls


def test_stop_aligner_not_available_without_bokeh():
    h, _ = _host()
    assert asyncio.run(h.stop_aligner()) == ErrorCodes.not_available


def test_stop_aligner_calls_aligner_stop_align():
    h, _ = _host()
    h.bokehapp = object()

    class _AL:
        def __init__(self):
            self.stopped = False

        def stop_align(self):
            self.stopped = True

    al = _AL()
    h.context.aligner = al
    assert asyncio.run(h.stop_aligner()) == ErrorCodes.none
    assert al.stopped is True


def test_shutdown_cancels_aligner_iotask():
    h, _ = _host()

    class _Task:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class _AL:
        def __init__(self):
            self.IOtask = _Task()

    al = _AL()
    h.context.aligner = al
    h.shutdown()
    assert al.IOtask.cancelled is True


def test_shutdown_noop_without_aligner():
    h, _ = _host()
    h.shutdown()  # must not raise when no aligner constructed


# --------------------------------------------------------------------------
# Driver: D6 surface genuinely removed
# --------------------------------------------------------------------------
def test_driver_shed_d6_surface():
    from helao.deploy.hte.drivers.motion import galil_motion_driver as gm

    d = gm.Galil(config={"axis_id": {"x": "A"}})
    for gone in [
        "start_aligner",
        "makeBokehApp",
        "start_aligner_run",
        "run_aligner_precheck",
        "stop_aligner",
        "base",
        "aligner_active",
        "bokehapp",
        "aligner_enabled",
    ]:
        assert not hasattr(d, gone), f"driver still exposes {gone}"
    # module no longer imports the Bokeh/aligner symbols
    for sym in ["Server", "HelaoVis", "Aligner", "partial"]:
        assert not hasattr(gm, sym), f"driver module still exposes {sym}"
    # position-notify sink is the only remaining aligner tie
    assert d._position_sink is None
    d.set_position_sink("Q")
    assert d._position_sink == "Q"


def test_update_aligner_pushes_to_sink_only_when_wired():
    from helao.deploy.hte.drivers.motion import galil_motion_driver as gm

    d = gm.Galil(config={"axis_id": {}})
    # no sink -> no-op, must not raise
    asyncio.run(d.update_aligner({"ax": ["x"]}))

    class _Q:
        def __init__(self):
            self.items = []

        async def put(self, msg):
            self.items.append(msg)

    q = _Q()
    d.set_position_sink(q)
    asyncio.run(d.update_aligner({"ax": ["x"], "position": [1.0]}))
    assert q.items == [{"ax": ["x"], "position": [1.0]}]
