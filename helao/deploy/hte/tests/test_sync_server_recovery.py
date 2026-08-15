"""Offline tests for the sync server's startup pending sweep.

:func:`sync_server.sweep_pending` is the automatic half of a recovery mechanism
whose durable half already worked: an unsynced yml stays in ``RUNS_FINISHED``
and a ``.prg`` sidecar under ``RUNS_SYNCED`` records what already landed, so
re-enqueueing is cheap and idempotent -- but :class:`HelaoSyncer` holds its work
queue in memory, action servers get no ``--restore``, and nothing ever called
``finish_pending`` on its own. These tests pin the sweep's contract:

* it composes the driver's existing ``finish_pending(actions_first=True)``
  rather than reimplementing discovery (the driver is byte-pinned against its
  hexagon-native twin by ``helao/hexagon/tests/test_native_sync_pins.py``, so
  the logic had to live in the server);
* it is suppressible, skippable and failure-tolerant without ever raising into
  the startup path;
* its summary survives ``json.dumps``, because it is served over HTTP on
  ``/tasks``.

Everything here is hermetic: no share, no network, no config. The sweep itself is
driven directly against a recording stub driver.

The second half covers the *wiring*, which the stub cannot reach: that the
startup handler is registered after BaseAPI's own, that shutdown cancels it, and
that ``/tasks`` carries the summary. ``makeApp`` is safe to call for this --
:class:`HelaoSyncer` is constructed in BaseAPI's startup event, not at
construction, so no AWS config is resolved and no syncer loop is spawned -- using
the same injected-``CONFIG`` seam as ``helao/hexagon/tests/test_db_shim.py``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from helao.deploy.hte.servers.action.sync_server import SWEEP_PARAM, sweep_pending


class _StubLogger:
    """Logger stand-in recording what the code under test reported, by level."""

    def __init__(self):
        self.infos = []
        self.errors = []

    def info(self, msg="", *a, **k):
        self.infos.append(str(msg))

    def warning(self, msg="", *a, **k):
        pass

    def error(self, msg="", *a, **k):
        self.errors.append(str(msg))


class _StubDriver:
    """Syncer stand-in recording every ``finish_pending`` call and its kwargs."""

    def __init__(self, pending=(), raises=None):
        self._pending = list(pending)
        self._raises = raises
        self.calls = []  # one dict of kwargs per call

    async def finish_pending(self, omit_manual_exps=True, actions_first=False):
        self.calls.append(
            {"omit_manual_exps": omit_manual_exps, "actions_first": actions_first}
        )
        if self._raises is not None:
            raise self._raises
        return list(self._pending)


def test_an_armed_sweep_enqueues_every_pending_yml_the_driver_reports():
    """The whole point: a restart must not leave finished ymls unswept.

    ``enqueued`` is the length of ``finish_pending``'s return, which is its
    pending-*sequence* list. If this regresses to not calling the driver at all,
    ymls accumulate in RUNS_FINISHED silently -- the failure mode this exists to
    close (179 unswept sequences on the production share).
    """
    driver = _StubDriver(pending=["a-seq.yml", "b-seq.yml", "c-seq.yml"])
    logger = _StubLogger()

    summary = asyncio.run(sweep_pending(driver, enabled=True, logger=logger))

    assert len(driver.calls) == 1
    assert summary["enabled"] is True
    assert summary["ran"] is True
    assert summary["enqueued"] == 3
    assert summary["error"] is None
    assert summary["reason"] is None


def test_the_sweep_asks_for_actions_first():
    """``actions_first=True`` is load-bearing, not a default worth drifting.

    A sequence cannot sync before its experiments and actions, so sweeping
    sequences first makes every partially-synced run bounce off its own
    incomplete children. The driver's own default is ``False``, so the kwarg
    must be passed explicitly -- dropping it would leave the sweep running but
    unable to drain a partial sync.
    """
    driver = _StubDriver(pending=["a-seq.yml"])

    asyncio.run(sweep_pending(driver, enabled=True, logger=_StubLogger()))

    assert driver.calls == [{"omit_manual_exps": True, "actions_first": True}]


def test_a_suppressed_sweep_touches_nothing_and_says_so():
    """``sync_pending_on_startup: false`` must be a real off switch.

    A station that deliberately disarms the sweep (say, while triaging a bad
    run) needs it to enqueue nothing at all, and needs the reason visible on
    ``/tasks`` rather than looking like a sweep that found an empty share.
    """
    driver = _StubDriver(pending=["a-seq.yml"])
    logger = _StubLogger()

    summary = asyncio.run(sweep_pending(driver, enabled=False, logger=logger))

    assert driver.calls == []
    assert summary["enabled"] is False
    assert summary["ran"] is False
    # None, not 0: "did not run" must not read as "ran and found nothing".
    assert summary["enqueued"] is None
    assert SWEEP_PARAM in summary["reason"]
    assert any(SWEEP_PARAM in m for m in logger.infos)
    assert logger.errors == []


def test_a_missing_driver_is_a_skip_not_a_crash():
    """``app.driver`` is ``None`` until BaseAPI's startup builds it, and stays
    ``None`` if construction failed. The sweep runs from a startup task, so an
    unguarded attribute access here would surface as an unretrieved task
    exception at every start on such a server -- noise that hides real errors.
    """
    logger = _StubLogger()

    summary = asyncio.run(sweep_pending(None, enabled=True, logger=logger))

    assert summary["ran"] is False
    assert summary["enqueued"] is None
    assert summary["error"] is None
    assert "driver" in summary["reason"]
    assert logger.errors == []


def test_a_failing_driver_is_reported_not_propagated():
    """A sweep failure must never take the server down.

    The sweep is dispatched as a startup task; letting an exception escape would
    both lose the summary and leave an unhandled task exception on the loop. The
    ymls are still in RUNS_FINISHED for the next start or a manual
    ``/finish_pending``, so reporting is the correct response, and the error text
    has to reach ``/tasks`` or the failure is invisible.
    """
    driver = _StubDriver(raises=RuntimeError("s3 unreachable"))
    logger = _StubLogger()

    summary = asyncio.run(sweep_pending(driver, enabled=True, logger=logger))

    assert summary["ran"] is False
    assert summary["enqueued"] is None
    assert summary["error"] == "RuntimeError: s3 unreachable"
    assert logger.errors, "a failed sweep must be logged at error level"


def test_cancellation_is_not_swallowed_as_a_failure():
    """Shutdown mid-sweep is a cancel, not an error.

    The shutdown handler cancels the sweep task and awaits it; if
    ``sweep_pending`` caught ``CancelledError`` and returned a summary instead,
    the await would never see the cancellation it asked for and a shutdown could
    hang behind a sweep it believed it had stopped.
    """

    async def _drive():
        driver = _StubDriver(raises=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await sweep_pending(driver, enabled=True, logger=_StubLogger())

    asyncio.run(_drive())


def test_an_empty_share_is_a_quiet_pass_distinguishable_from_never_running():
    """Nothing pending is the healthy steady state, and must not look like an
    error or like a sweep that never happened: ``ran`` is True and ``enqueued``
    is 0, where ``/tasks`` reports ``null`` for "has not finished yet"."""
    driver = _StubDriver(pending=[])
    logger = _StubLogger()

    summary = asyncio.run(sweep_pending(driver, enabled=True, logger=logger))

    assert summary["ran"] is True
    assert summary["enqueued"] == 0
    assert summary["error"] is None
    assert logger.errors == []


@pytest.mark.parametrize(
    "driver,enabled",
    [
        (_StubDriver(pending=["a-seq.yml"]), True),
        (_StubDriver(pending=["a-seq.yml"]), False),
        (None, True),
        (_StubDriver(raises=RuntimeError("boom")), True),
    ],
)
def test_every_summary_shape_is_json_serialisable(driver, enabled):
    """The summary is served on ``/tasks``, so an unserialisable value in any
    branch (an exception object, a Path, a set) would turn a status poll into a
    500 -- and only for the branch that produced it, which is exactly the
    failure branch nobody exercises before a station does."""
    summary = asyncio.run(sweep_pending(driver, enabled=enabled, logger=_StubLogger()))

    assert json.loads(json.dumps(summary)) == summary
    # keys the /tasks consumer reads
    assert set(summary) >= {"enabled", "ran", "enqueued", "reason", "error"}
    assert isinstance(summary["finished_at"], float)


# --- wiring -----------------------------------------------------------------


def _world(tmp_path, params=None):
    """A minimal injected world config naming one DB action server."""
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "DB": {
                "host": "127.0.0.1",
                "port": 8911,
                "group": "action",
                "fast": "sync_server",
                "params": params if params is not None else {},
            },
        },
    }


@pytest.fixture()
def installed_config(tmp_path, monkeypatch):
    """Install a throwaway world config, as ``test_db_shim.py`` does."""
    from helao.helpers import config_loader

    def _install(params=None):
        world = _world(tmp_path, params)
        logs = tmp_path / "LOGS"
        logs.mkdir(exist_ok=True)
        monkeypatch.setattr(config_loader, "CONFIG", world)
        return world

    return _install


def _make_app(installed_config, params=None) -> Any:
    """Build the real app against the injected config.

    Returned as ``Any`` deliberately. These tests exist to poke the two
    user-attached app attributes (``last_startup_sweep``, ``startup_sweep_task``)
    and to introspect ``app.routes``, neither of which pyright can see on
    ``BaseAPI`` / Starlette's ``BaseRoute`` -- the same reason ``makeApp`` itself
    carries ``# type: ignore[attr-defined]`` on those assignments. Widening here
    keeps that concession in one place instead of on a dozen assertions.
    """
    from helao.deploy.hte.servers.action import sync_server

    installed_config(params)
    return sync_server.makeApp("DB")


def test_the_sweep_is_armed_from_a_startup_handler_registered_after_baseapis(
    installed_config,
):
    """Ordering is the whole reason this is a startup handler and not inline.

    ``app.base`` and ``app.driver`` are both created in BaseAPI's *own* startup
    event, so the sweep can only see a driver if its handler runs after that one.
    Starlette preserves registration order, so registering ours later is what
    guarantees it -- and reading ``app.base.aloop`` from module scope instead
    would raise at import, before any loop exists.
    """
    app = _make_app(installed_config)

    startup_names = [h.__name__ for h in app.router.on_startup]
    assert "_arm_startup_sweep" in startup_names
    assert startup_names.index("_arm_startup_sweep") > startup_names.index(
        "startup_event"
    )
    assert "_cancel_startup_sweep" in [h.__name__ for h in app.router.on_shutdown]


def test_no_route_is_added_by_the_recovery_wiring(installed_config):
    """The frozen checklist (``checklists/hte/sync_server.json``) pins this
    module's route set, so a new route would break that gate. The sweep is
    therefore observable through the existing ``/tasks`` body instead."""
    app = _make_app(installed_config)

    paths = sorted({r.path for r in app.routes if r.path.startswith("/finish")})
    assert paths == ["/finish_pending", "/finish_yml"]
    assert "/sweep_pending" not in {r.path for r in app.routes}
    assert "/last_startup_sweep" not in {r.path for r in app.routes}


def test_the_summary_starts_as_none_so_never_ran_is_visible(installed_config):
    """``/tasks`` must be able to say "the sweep has not finished yet" -- an
    absent attribute would raise, and an empty dict would read as a completed
    sweep that found nothing."""
    app = _make_app(installed_config)

    assert app.last_startup_sweep is None
    assert app.startup_sweep_task is None


@pytest.mark.parametrize(
    "params,expected",
    [
        ({}, True),
        ({"sync_pending_on_startup": True}, True),
        ({"sync_pending_on_startup": False}, False),
    ],
)
def test_the_param_is_read_from_server_params_and_defaults_to_armed(
    installed_config, params, expected
):
    """Armed by default: a recovery that had to be switched on would leave the
    silent-loss window exactly as wide as it was. The key is read from the
    server's own ``params`` block, not the world config."""
    app = _make_app(installed_config, params)

    assert bool(app.server_params.get(SWEEP_PARAM, True)) is expected


def _handler(app, name, which="on_startup"):
    """The registered lifecycle handler called ``name``."""
    return next(h for h in getattr(app.router, which) if h.__name__ == name)


def _prime(app, driver):
    """Stand in for what the host's startup event binds, without running it.

    B5: ``app.base`` used to be assignable, because it was a separate ``Base``
    the legacy startup handler attached. On an ``ActionHost`` it is a read-only
    property returning the host itself, so the loop is set where the host
    actually keeps it -- ``app.aloop``, which is the attribute the sweep
    dispatcher reads either way.
    """
    app.driver = driver
    app.aloop = asyncio.get_running_loop()


@pytest.mark.asyncio
async def test_the_startup_handler_dispatches_a_task_and_records_its_summary(
    installed_config,
):
    """The handler must *dispatch*, not await.

    Awaiting the sweep inside a startup handler would hold the server's health
    endpoints down for as long as enqueueing hundreds of ymls takes -- which is
    precisely the state an operator would be trying to inspect. So the handler
    returns immediately with a task, and the summary lands on the app when that
    task finishes.
    """
    app = _make_app(installed_config)
    driver = _StubDriver(pending=["a-seq.yml", "b-seq.yml"])
    _prime(app, driver)

    _handler(app, "_arm_startup_sweep")()

    assert app.startup_sweep_task is not None
    assert app.last_startup_sweep is None, "must not have awaited the sweep inline"
    await app.startup_sweep_task
    summary = app.last_startup_sweep
    assert summary is not None and summary["enqueued"] == 2
    assert driver.calls == [{"omit_manual_exps": True, "actions_first": True}]


@pytest.mark.asyncio
async def test_a_suppressing_param_reaches_the_dispatched_sweep(installed_config):
    """The off switch has to survive the hop through the task, not just be read.

    ``server_params`` is captured in the handler and passed as ``enabled``; if
    that plumbing broke, the config key would silently do nothing -- the worst
    kind of off switch.
    """
    app = _make_app(installed_config, {"sync_pending_on_startup": False})
    driver = _StubDriver(pending=["a-seq.yml"])
    _prime(app, driver)

    _handler(app, "_arm_startup_sweep")()
    await app.startup_sweep_task

    assert driver.calls == []
    assert app.last_startup_sweep["enabled"] is False


@pytest.mark.asyncio
async def test_shutdown_cancels_a_sweep_still_in_flight(installed_config):
    """Shutdown must not hang behind a sweep that is mid-enqueue.

    Cutting it short is safe -- whatever it queued is queued, and whatever it
    did not is still in RUNS_FINISHED for the next start. The handler has to
    swallow the resulting ``CancelledError`` from its own ``await``, or a clean
    stop would surface as an error during shutdown.
    """

    class _BlockingDriver:
        def __init__(self):
            self.entered = asyncio.Event()

        async def finish_pending(self, omit_manual_exps=True, actions_first=False):
            self.entered.set()
            await asyncio.sleep(3600)  # never completes on its own
            return []

    app = _make_app(installed_config)
    driver = _BlockingDriver()
    _prime(app, driver)

    _handler(app, "_arm_startup_sweep")()
    await driver.entered.wait()

    await _handler(app, "_cancel_startup_sweep", "on_shutdown")()

    assert app.startup_sweep_task is None
    # cancelled, so no summary -- "never ran" rather than a bogus success
    assert app.last_startup_sweep is None


@pytest.mark.asyncio
async def test_shutdown_before_the_sweep_was_armed_is_a_noop(installed_config):
    """A server that fails before startup still runs shutdown handlers, so the
    cancel path must tolerate a task that was never created."""
    app = _make_app(installed_config)

    await _handler(app, "_cancel_startup_sweep", "on_shutdown")()

    assert app.startup_sweep_task is None


@pytest.mark.asyncio
async def test_tasks_reports_the_sweep_beside_the_queue_it_already_reported(
    installed_config,
):
    """``/tasks`` is the observability seam, chosen over a new route because the
    frozen checklist pins the route set. Its pre-existing keys must survive the
    addition -- operators and ``conc_items.py``-style smoke clients read them."""
    app = _make_app(installed_config)
    app.driver = SimpleNamespace(
        running_tasks={"job-1": None}, task_queue=SimpleNamespace(qsize=lambda: 4)
    )
    endpoint = next(
        r.endpoint for r in app.routes if getattr(r, "path", None) == "/tasks"
    )

    body = await endpoint()
    assert body["running"] == ["job-1"]
    assert body["num_queued"] == 4
    assert body["last_startup_sweep"] is None

    app.last_startup_sweep = {"ran": True, "enqueued": 0}
    body = await endpoint()
    assert body["last_startup_sweep"] == {"ran": True, "enqueued": 0}
    assert json.loads(json.dumps(body)) == body
