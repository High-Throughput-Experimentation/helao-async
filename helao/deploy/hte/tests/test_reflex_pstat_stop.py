"""The Reflex potentiostat panels must be able to abort a measurement.

The Bokeh panels have always carried a stop button — one on
``servers/visualizer/gamry_vis.py``, one per channel on ``biologic_vis.py`` —
that POSTs the bare private ``stop_private`` route on the panel's own action
server. Their Reflex ports carried none, so a station running only the Reflex
stack could watch a measurement run and had no way to stop it from the UI.

These tests assert the two stacks issue the *same call*, and they get the Bokeh
side by building the real Bokeh visualizer and pressing its button, capturing
the dispatch it schedules. A hand-written expectation would only prove the
Reflex panel matches what this file believes about the Bokeh one.

Run directly (``python -m pytest`` on this file) — the hte suite is not part of
``run_unit_tests.py``.
"""

import asyncio
import importlib
import json
import pathlib

import numpy as np
import pytest
from bokeh.document import Document

from helao.core.error import ErrorCodes
from helao.ui.shared import palette
from helao.ui.reflex.state import make_panel_state
from helao.deploy.hte.servers.reflex import _pstat, _pstat_panel

SERV_KEY = "PSTAT"
SERVERS = {SERV_KEY: {"host": "127.0.0.1", "port": 8004}}
WORLD = {"servers": SERVERS}

#: Reflex panel module <-> Bokeh visualizer module, and the channel each stop
#: is issued for. ``None`` is a single-potentiostat panel, whose ``stop_private``
#: takes no arguments.
PANELS = {
    "gamry_vis": None,
    "biologic_vis": 1,
}


# -- the Bokeh side, executed rather than assumed -----------------------------


class _CapturingDoc:
    """Stands in for the Bokeh document, keeping what was scheduled on it.

    ``callback_stop_measure`` does not dispatch inline — it hands
    ``add_next_tick_callback`` a ``partial`` so the cancel does not block the
    document. The partial's keywords *are* the wire call, which is what these
    tests compare against.
    """

    def __init__(self):
        self.calls = []

    def add_next_tick_callback(self, callback):
        self.calls.append(callback)


class _FakeVis:
    """The three attributes ``VisSubscriber.__init__`` reads."""

    def __init__(self, doc, params=None):
        self.doc = doc
        self.server_cfg = {"params": params or {}}
        self.world_cfg = WORLD


def _build_bokeh(modname):
    """Build a real Bokeh visualizer with its ingest task cancelled.

    ``_mount`` starts ``IOloop_data`` with ``asyncio.create_task``, so this
    runs inside a loop and cancels the task before it can open a socket to a
    server that is not there. Same shape as
    ``test_pstat_vis_axis_selectors.py``'s harness.
    """
    module = importlib.import_module(f"helao.deploy.hte.servers.visualizer.{modname}")

    async def _make():
        vis = module.C_vis(_FakeVis(Document(), {"num_channels": 2}), SERV_KEY)
        vis.IOloop_data_run = False
        vis.IOtask.cancel()
        return vis

    return asyncio.run(_make())


def bokeh_stop_call(modname, channel):
    """Press the Bokeh panel's stop button and return the call it scheduled.

    Returns:
        dict: the ``async_private_dispatcher`` keywords, i.e. the wire.
    """
    vis = _build_bokeh(modname)
    doc = _CapturingDoc()
    vis.vis.doc = doc
    if channel is None:
        vis.callback_stop_measure(None)
    else:
        vis.callback_stop_measure(None, channel=channel)
    assert len(doc.calls) == 1, doc.calls
    scheduled = doc.calls[0]
    assert scheduled.func.__name__ == "async_private_dispatcher", scheduled.func
    return dict(scheduled.keywords)


# -- the Reflex side ----------------------------------------------------------


class _FakeState:
    """A stand-in carrying what ``request_stop`` touches.

    Deliberately not a real state: Reflex forwards attribute assignment on one
    to a parent state that does not exist outside a session, so every write
    would raise. ``async with self`` is the state lock, a no-op here.
    """

    def __init__(self, server_key=SERV_KEY):
        self.server_key = server_key
        self.stop_status = ""
        self.stop_targets = []
        self.action_name = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def spy(monkeypatch):
    """Capture what the Reflex panel dispatches, and choose its reply."""
    sent = []
    reply = {"error_code": ErrorCodes.none, "raises": None}

    async def _dispatch(**kwargs):
        sent.append(kwargs)
        if reply["raises"] is not None:
            raise reply["raises"]
        return None, reply["error_code"]

    monkeypatch.setattr(_pstat, "async_private_dispatcher", _dispatch)
    monkeypatch.setattr(_pstat_panel, "world_config", lambda: WORLD)
    return sent, reply


def panel_state_class(modname):
    """Mint the concrete state Reflex would bind this panel to."""
    module = importlib.import_module(f"helao.deploy.hte.servers.reflex.{modname}")
    return module, make_panel_state(
        f"{modname}_stop_test", SERV_KEY, module.STATE_BASE, module.WS_PATH
    )


def press_reflex_stop(modname, channel, state=None):
    """Drive the panel's stop handler exactly as a click would.

    ``.fn`` unwraps the ``rx.event`` decorator to the coroutine the browser's
    click reaches, which is the same object the button is wired to — asserted
    separately in :func:`test_the_button_is_wired_to_the_handler_under_test`.
    """
    _module, cls = panel_state_class(modname)
    state = state or _FakeState()
    asyncio.run(cls.request_stop.fn(state, "" if channel is None else str(channel)))
    return state


# -- the two stacks issue the same call ---------------------------------------


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_bokeh_panel_still_dispatches_stop_private(modname):
    """The fixture the Reflex side is compared against, extracted by pressing
    the real button. If this changes, the parity assertion below must move
    with it rather than silently keep matching a stale expectation."""
    call = bokeh_stop_call(modname, PANELS[modname])

    assert call["private_action"] == "stop_private", call
    assert call["server_key"] == SERV_KEY
    assert (call["host"], call["port"]) == ("127.0.0.1", 8004)
    expected = {} if PANELS[modname] is None else {"channel": PANELS[modname]}
    assert call["params_dict"] == expected, call
    print(f"test_the_bokeh_panel_still_dispatches_stop_private[{modname}] PASS")


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_reflex_stop_issues_the_bokeh_wire(modname, spy):
    """Route, target and params identical to the Bokeh button's, per panel."""
    sent, _reply = spy
    bokeh = bokeh_stop_call(modname, PANELS[modname])
    press_reflex_stop(modname, PANELS[modname])

    assert len(sent) == 1, sent
    reflex = sent[0]
    for field in ("server_key", "host", "port", "private_action", "params_dict"):
        assert reflex[field] == bokeh[field], (field, reflex[field], bokeh[field])
    print(f"test_the_reflex_stop_issues_the_bokeh_wire[{modname}] PASS")


def test_the_channel_reaches_the_wire_as_the_int_the_endpoint_declares(spy):
    """A click delivers a string; ``stop_private(channel: Optional[int])``
    declares an int, and the Bokeh button sends one. ``"1"`` and ``1`` are not
    the same params dict, so the comparison above would not catch a str."""
    sent, _reply = spy
    press_reflex_stop("biologic_vis", 3)

    assert sent[0]["params_dict"] == {"channel": 3}
    assert isinstance(sent[0]["params_dict"]["channel"], int)
    print("test_the_channel_reaches_the_wire_as_the_int_the_endpoint_declares PASS")


def test_a_single_potentiostat_sends_no_channel(spy):
    """Gamry's ``stop_private`` takes no arguments and stops every executor;
    inventing a channel for it would be a param the endpoint never declared."""
    sent, _reply = spy
    press_reflex_stop("gamry_vis", None)

    assert sent[0]["params_dict"] == {}
    print("test_a_single_potentiostat_sends_no_channel PASS")


def test_the_route_is_the_bare_private_one_not_an_action(spy):
    """``stop_private`` is bare-path and ``tags=["private"]`` — it must not be
    prefixed with the server key the way an action route is, or it would enter
    the action namespace and queue behind the running experiment."""
    sent, _reply = spy
    press_reflex_stop("gamry_vis", None)

    assert sent[0]["private_action"] == "stop_private"
    assert "/" not in sent[0]["private_action"]
    assert not sent[0]["private_action"].startswith(SERV_KEY)
    print("test_the_route_is_the_bare_private_one_not_an_action PASS")


#: Panel module -> the action server whose frozen route checklist it calls.
CHECKLISTS = {"gamry_vis": "gamry_server2", "biologic_vis": "biologic_server"}


def frozen_stop_route(server_module):
    """The ``stop_private`` entry of a server's frozen route checklist."""
    root = pathlib.Path(__file__).resolve().parents[4]
    rows = json.loads(
        (
            root / "helao/hexagon/tests/checklists/hte" / f"{server_module}.json"
        ).read_text()
    )
    (row,) = [r for r in rows if r["path"].endswith("stop_private")]
    return row


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_call_is_an_additive_consumer_of_an_already_frozen_route(modname, spy):
    """This slice adds a caller, not a route: the endpoint it presses is
    already in the server's frozen checklist, with the params being sent and
    no others. Nothing here re-freezes anything — but a later change to the
    endpoint's signature would land on this assertion rather than on a station
    pressing a button that 422s."""
    sent, _reply = spy
    press_reflex_stop(modname, PANELS[modname])
    frozen = frozen_stop_route(CHECKLISTS[modname])

    assert frozen["path"] == f"/{sent[0]['private_action']}", frozen
    assert frozen["tags"] == ["private"], frozen
    declared = {param["name"] for param in frozen["params"]}
    assert set(sent[0]["params_dict"]) <= declared, (sent[0], declared)
    if PANELS[modname] is not None:
        assert "channel" in declared, frozen
    print(
        "test_the_call_is_an_additive_consumer_of_an_already_frozen_route"
        f"[{modname}] PASS"
    )


def test_the_stop_call_fails_fast_rather_than_holding_the_panel(spy):
    """The dispatcher's defaults are 60s and 5 retries. An abort that spends
    minutes retrying against a server that is not answering tells the operator
    nothing while they wait for it."""
    sent, _reply = spy
    press_reflex_stop("gamry_vis", None)

    assert sent[0]["timeout"] == _pstat.STOP_TIMEOUT < 60
    assert sent[0]["retries"] == _pstat.STOP_RETRIES < 5
    print("test_the_stop_call_fails_fast_rather_than_holding_the_panel PASS")


# -- the button is wired to the handler under test ----------------------------


def _walk(component):
    yield component
    for child in getattr(component, "children", []) or []:
        yield from _walk(child)


def stop_buttons(modname):
    """Every button in the built panel that carries an ``on_click``."""
    module, cls = panel_state_class(modname)
    panel = module.build(SERV_KEY, cls)
    return cls, [
        component
        for component in _walk(panel)
        if (getattr(component, "event_triggers", None) or {}).get("on_click")
    ]


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_button_is_wired_to_the_handler_under_test(modname):
    """The vacuity guard: a handler the panel never binds is a handler no
    operator can reach, and a test that only drives it would pass anyway."""
    cls, buttons = stop_buttons(modname)

    assert len(buttons) == 1, buttons
    chain = buttons[0].event_triggers["on_click"]
    assert len(chain.events) == 1, chain.events
    assert chain.events[0].handler.fn is cls.request_stop.fn
    print(f"test_the_button_is_wired_to_the_handler_under_test[{modname}] PASS")


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_panel_renders_with_the_buttons_on_it(modname):
    """Constructing a component and rendering it are different things: a var
    ``rx.foreach`` cannot iterate raises on the way to the frontend, not at
    import, so a panel that builds can still fail the bundle build."""
    module, cls = panel_state_class(modname)
    text = json.dumps(module.build(SERV_KEY, cls).render(), default=str)

    assert palette.REFLEX_PSTAT_STOP_CLASS in text
    assert "request_stop" in text
    print(f"test_the_panel_renders_with_the_buttons_on_it[{modname}] PASS")


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_button_passes_the_channel_not_the_label(modname):
    """Each row is ``[label, channel]``, and the click passes element 1. Wiring
    element 0 would send the button's own text as the channel — which fails at
    the ``int()``, in the browser, on the one press that matters."""
    _cls, buttons = stop_buttons(modname)
    (spec,) = buttons[0].event_triggers["on_click"].events

    (_arg_name, value), *rest = spec.args
    assert not rest, spec.args
    assert "at?.(1)" in str(value), str(value)
    print(f"test_the_button_passes_the_channel_not_the_label[{modname}] PASS")


# -- one button per thing that can be stopped ---------------------------------


def _targets(modname, state, snapshot):
    module = importlib.import_module(f"helao.deploy.hte.servers.reflex.{modname}")
    module.STATE_BASE._update_stop_targets(state, snapshot)
    return state.stop_targets


def _snap(**cols):
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


def test_a_channel_gets_a_button_as_soon_as_it_is_seen():
    """A Reflex panel is handed its server's key and nothing else, so the
    channel count exists in this process only as what has arrived on the
    wire."""
    state = _FakeState()
    targets = _targets("biologic_vis", state, _snap(t_s=[0, 1, 2], channel=[0, 2, 2]))

    assert targets == [["Stop channel 0", "0"], ["Stop channel 2", "2"]]
    print("test_a_channel_gets_a_button_as_soon_as_it_is_seen PASS")


def test_a_channels_button_survives_the_window_emptying():
    """Between actions the trailing window can carry no rows for a channel. A
    stop button that vanishes then is missing exactly when the next action
    starts and the operator reaches for it."""
    state = _FakeState()
    _targets("biologic_vis", state, _snap(t_s=[0, 1], channel=[0, 1]))
    targets = _targets("biologic_vis", state, _snap(t_s=[], channel=[]))

    assert [row[1] for row in targets] == ["0", "1"]
    print("test_a_channels_button_survives_the_window_emptying PASS")


def test_channel_buttons_are_ordered_numerically_not_lexically():
    state = _FakeState()
    snapshot = _snap(t_s=[0, 1, 2], channel=[10, 2, 1])
    targets = _targets("biologic_vis", state, snapshot)

    assert [row[1] for row in targets] == ["1", "2", "10"]
    print("test_channel_buttons_are_ordered_numerically_not_lexically PASS")


def test_the_single_potentiostat_button_names_the_running_action():
    """``gamry_vis.py`` relabels its button ``Stop {action_name}``; the port
    says the same thing on the same event."""
    state = _FakeState()
    state.action_name = "run_CV"
    targets = _targets("gamry_vis", state, _snap(t_s=[0, 1]))

    assert targets == [["Stop run_CV", ""]]
    print("test_the_single_potentiostat_button_names_the_running_action PASS")


def test_the_single_potentiostat_button_exists_before_any_action():
    state = _FakeState()
    targets = _targets("gamry_vis", state, {})

    assert targets == [[_pstat_panel.IDLE_STOP_LABEL, ""]]
    print("test_the_single_potentiostat_button_exists_before_any_action PASS")


# -- a stop that did not land must say so -------------------------------------


def test_a_successful_stop_is_reported(spy):
    state = press_reflex_stop("gamry_vis", None)

    assert state.stop_status == "stop requested"
    print("test_a_successful_stop_is_reported PASS")


def test_an_error_code_is_surfaced_in_the_panel(spy):
    """The operator pressed stop because the instrument is doing something
    they want stopped. A button that swallows its own failure tells them it
    worked."""
    _sent, reply = spy
    reply["error_code"] = ErrorCodes.http

    state = press_reflex_stop("biologic_vis", 1)

    assert "stop failed" in state.stop_status, state.stop_status
    assert str(ErrorCodes.http) in state.stop_status, state.stop_status
    print("test_an_error_code_is_surfaced_in_the_panel PASS")


def test_a_raising_dispatch_is_surfaced_and_does_not_escape(spy):
    _sent, reply = spy
    reply["raises"] = OSError("connection refused")

    state = press_reflex_stop("gamry_vis", None)

    assert "stop failed" in state.stop_status
    assert "OSError" in state.stop_status, state.stop_status
    print("test_a_raising_dispatch_is_surfaced_and_does_not_escape PASS")


def test_a_server_with_no_address_is_not_dispatched_to(spy, monkeypatch):
    """``server_address`` yields ``(None, None)`` for a server the config does
    not declare. Dispatching to ``None`` would fail somewhere further down with
    a message about none of this."""
    sent, _reply = spy
    monkeypatch.setattr(_pstat_panel, "world_config", dict)

    state = press_reflex_stop("gamry_vis", None)

    assert sent == []
    assert "no address" in state.stop_status, state.stop_status
    print("test_a_server_with_no_address_is_not_dispatched_to PASS")


# -- the pieces under the panel -----------------------------------------------


def test_stop_params_shapes():
    assert _pstat.stop_params() == {}
    assert _pstat.stop_params(None) == {}
    assert _pstat.stop_params("") == {}
    assert _pstat.stop_params(0) == {"channel": 0}
    assert _pstat.stop_params("2") == {"channel": 2}
    print("test_stop_params_shapes PASS")


def test_channel_zero_is_a_channel_not_an_absent_one():
    """``0`` is falsy and is BioLogic's first channel; a truthiness test here
    would silently turn "stop channel 0" into "stop everything"."""
    assert _pstat.stop_params(0) == {"channel": 0}
    print("test_channel_zero_is_a_channel_not_an_absent_one PASS")


def test_server_address_reads_the_same_config_the_bokeh_panel_does():
    assert _pstat.server_address(WORLD, SERV_KEY) == ("127.0.0.1", 8004)
    assert _pstat.server_address(WORLD, "NOPE") == (None, None)
    assert _pstat.server_address({}, SERV_KEY) == (None, None)
    print("test_server_address_reads_the_same_config_the_bokeh_panel_does PASS")


def test_world_config_falls_back_to_the_installed_global(monkeypatch):
    """A stop pressed before ingest has started still needs an address."""
    monkeypatch.setattr(_pstat_panel, "get_registry", lambda: None)
    monkeypatch.setattr(_pstat_panel.config_loader, "CONFIG", WORLD, raising=False)

    assert _pstat_panel.world_config() is WORLD
    print("test_world_config_falls_back_to_the_installed_global PASS")


# -- colour -------------------------------------------------------------------


@pytest.mark.parametrize("modname", sorted(PANELS))
def test_the_stop_button_holds_no_colour_of_its_own(modname):
    """Every colour in both stacks comes from ``palette``; the button's is the
    same danger red the Bokeh twin gets from ``button_type="danger"``."""
    _cls, buttons = stop_buttons(modname)

    assert buttons[0].class_name == palette.REFLEX_PSTAT_STOP_CLASS
    assert palette.REFLEX_PSTAT_STOP_CLASS.startswith("bg-red-700")
    assert palette.TW["red-700"] == palette.BUTTON_DANGER_BG
    print(f"test_the_stop_button_holds_no_colour_of_its_own[{modname}] PASS")


def test_the_stop_button_is_not_painted_as_the_estop():
    """It aborts one server's measurement; the station-wide cascade is a
    different authority and a different red."""
    assert palette.TW["red-700"] != palette.ESTOP_BG
    print("test_the_stop_button_is_not_painted_as_the_estop PASS")
