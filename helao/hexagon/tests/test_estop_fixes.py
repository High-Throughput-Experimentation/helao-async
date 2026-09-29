"""Three defects a station E-STOP drill found.

A. ``ActionHost.estop_actives`` awaited the SYNC ``ActionSession.set_estop`` (a
   TypeError per active, swallowed) and never finalized the action.
B. Dispatch carried on after E-STOP: the effect awaited ``finish_active_experiment``
   while the E-STOP landed, then dispatched into ``active_sequence is None``.
C. ``estop_loop`` fanned ``switch=False`` to every server, and every driver's
   ``estop(switch)`` acts only when ``switch`` is True, so no driver ever acted.
"""

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.domain.models import HloStatus, LoopStatus

# --- A: estop_actives ---------------------------------------------------------


def _host(tmp_path):
    from helao.hexagon.adapters.native.artifact_store import (
        NativeArtifactStoreAdapter,
    )
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    class _Clock:
        def now_ns(self):
            return 0

        def offset(self):
            return 0.0

    class _Stub:
        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used unexpectedly")

    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="estop",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Clock(),
            transport=_Stub(),
            state_persistence=_Stub(),
            status=_Stub(),
            health=_Stub(),
            artifact_store=NativeArtifactStoreAdapter(config=_Stub(), clock=_Clock()),
            data_sink=_Stub(),
        ),
        helao_cfg={
            "root": str(tmp_path),
            "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )


@pytest.mark.asyncio
async def test_estop_route_finalizes_an_active_that_has_no_executor(tmp_path):
    """The MOTOR ``move`` shape: an active session, no executor.

    With no executor, ``stop_executor_by_id`` has nothing to stop, so nothing but
    ``estop_actives`` can end this action. Before the fix it raised TypeError
    (``await None``), the action stayed ``active`` and stayed in ``actives``.
    """

    from helao.helpers.premodels import Action
    from helao.hexagon.app.action_session import ActionSession

    host = _host(tmp_path)
    session = await ActionSession.open(host, Action(action_name="move"))
    uuid = session.action.action_uuid
    assert host.actives[uuid] is session
    assert not host.executors
    assert HloStatus.active in session.action.action_status

    route = next(r for r in host.routes if getattr(r, "path", "") == "/SIM/estop")
    body = await route.endpoint(switch=True)

    assert body["estopped_actions"] == [str(uuid)]
    assert HloStatus.estopped in session.action.action_status
    assert HloStatus.finished in session.action.action_status
    assert HloStatus.active not in session.action.action_status
    assert uuid not in host.actives


# --- B: dispatch continues after E-STOP ---------------------------------------


class _GSM:
    def __init__(self, loop_state):
        self.loop_state = loop_state


class _DispatchOrch:
    """Just the surface ``dispatch_experiment``/``dispatch_sequence`` read first."""

    def __init__(self, loop_state=LoopStatus.started):
        from helao.hexagon.app.orch_dispatch import DispatchRunner

        self.globalstatusmodel = _GSM(loop_state)
        self.experiment_dq = deque(["exp1", "exp2"])
        self.sequence_dq = deque(["seq1", "seq2"])
        self.action_dq = deque(["act1"])
        self.active_experiment = "EXP"
        self.active_sequence = "SEQ"
        self.calls = []
        self.dispatch_runner = DispatchRunner(self)

    async def intend_none(self):
        self.calls.append("intend_none")

    async def loop_task_dispatch_experiment(self):
        return await self.dispatch_runner.dispatch_experiment()

    async def loop_task_dispatch_sequence(self):
        return await self.dispatch_runner.dispatch_sequence()


def _forbid_staging(monkeypatch, orch):
    async def _boom(*a, **k):
        raise AssertionError("_stage_experiment ran after E-STOP")

    monkeypatch.setattr(orch.dispatch_runner, "_stage_experiment", _boom)


@pytest.mark.asyncio
async def test_dispatch_experiment_refuses_under_estop(monkeypatch):
    orch = _DispatchOrch(LoopStatus.estopped)
    _forbid_staging(monkeypatch, orch)
    rc = await orch.dispatch_runner.dispatch_experiment()
    assert rc is ErrorCodes.estop
    assert list(orch.experiment_dq) == ["exp1", "exp2"]
    assert list(orch.sequence_dq) == ["seq1", "seq2"]
    assert list(orch.action_dq) == ["act1"]
    assert (orch.active_experiment, orch.active_sequence) == ("EXP", "SEQ")
    assert orch.calls == []


@pytest.mark.asyncio
async def test_dispatch_sequence_refuses_under_estop():
    orch = _DispatchOrch(LoopStatus.estopped)
    rc = await orch.dispatch_runner.dispatch_sequence()
    assert rc is ErrorCodes.estop
    assert list(orch.sequence_dq) == ["seq1", "seq2"]
    assert list(orch.experiment_dq) == ["exp1", "exp2"]
    assert (orch.active_experiment, orch.active_sequence) == ("EXP", "SEQ")


@pytest.mark.asyncio
async def test_runner_race_estop_lands_during_finish_active_experiment(monkeypatch):
    """The drill's shape, on the legacy-ladder runner (orch_dispatch.py:653)."""
    from helao.hexagon.app.orch_dispatch import FinishThenDispatchExperiment

    orch = _DispatchOrch(LoopStatus.started)
    _forbid_staging(monkeypatch, orch)

    async def finish_active_experiment():
        await asyncio.sleep(0)  # the E-STOP lands inside this await
        orch.globalstatusmodel.loop_state = LoopStatus.estopped
        orch.active_experiment = None  # estop_finish_active's effect
        orch.active_sequence = None

    orch.finish_active_experiment = finish_active_experiment
    rc = await orch.dispatch_runner._execute(
        FinishThenDispatchExperiment(), ErrorCodes.unspecified
    )
    assert rc is ErrorCodes.estop
    assert list(orch.experiment_dq) == ["exp1", "exp2"]


@pytest.mark.asyncio
async def test_runner_race_estop_lands_during_finish_active_sequence():
    from helao.hexagon.app.orch_dispatch import FinishThenDispatchSequence

    orch = _DispatchOrch(LoopStatus.started)

    async def finish_active_sequence():
        await asyncio.sleep(0)
        orch.globalstatusmodel.loop_state = LoopStatus.estopped

    orch.finish_active_sequence = finish_active_sequence
    rc = await orch.dispatch_runner._execute(
        FinishThenDispatchSequence(), ErrorCodes.unspecified
    )
    assert rc is ErrorCodes.estop
    assert list(orch.sequence_dq) == ["seq1", "seq2"]


@pytest.mark.asyncio
async def test_effect_race_estop_lands_during_finish_active_experiment(monkeypatch):
    """The same race on the reducer's effect runner (orch_effects.py:227)."""
    from helao.hexagon.app.orch_effects import OrchCommandRunner
    from helao.hexagon.app.wiring import PortWiring
    from helao.hexagon.domain.orchestration import (
        FinishThenDispatchExperimentCmd,
        FinishThenDispatchSequenceCmd,
    )

    orch = _DispatchOrch(LoopStatus.started)
    _forbid_staging(monkeypatch, orch)

    async def finish_active_experiment():
        await asyncio.sleep(0)
        orch.globalstatusmodel.loop_state = LoopStatus.estopped
        orch.active_experiment = None
        orch.active_sequence = None

    async def finish_active_sequence():
        await asyncio.sleep(0)
        orch.globalstatusmodel.loop_state = LoopStatus.estopped

    orch.finish_active_experiment = finish_active_experiment
    orch.finish_active_sequence = finish_active_sequence
    runner = OrchCommandRunner(orch, PortWiring())

    assert await runner.execute(FinishThenDispatchExperimentCmd()) is ErrorCodes.estop
    assert list(orch.experiment_dq) == ["exp1", "exp2"]

    orch.globalstatusmodel.loop_state = LoopStatus.started
    assert await runner.execute(FinishThenDispatchSequenceCmd()) is ErrorCodes.estop
    assert list(orch.sequence_dq) == ["seq1", "seq2"]


# --- B: orphaned queues -------------------------------------------------------


class _Obj:
    def __init__(self, status):
        self.experiment_status = list(status)
        self.sequence_status = list(status)
        self.experiment_finished_timestamp = None
        self.sequence_finished_timestamp = None
        self.dispatched_experiments = []

    def get_exp(self):
        return "exp-model"


class _EstopOrch:
    def __init__(self):
        from helao.hexagon.app.orch_estop import EstopController

        self.estop_controller = EstopController(self)
        self.globalstatusmodel = SimpleNamespace(
            loop_state=LoopStatus.started,
            counter_dispatched_actions={"x": 1},
            server_dict={},
            clear_in_finished=lambda hlostatus: None,
        )
        self.active_experiment = _Obj([HloStatus.active])
        self.active_sequence = _Obj([HloStatus.active])
        self.experiment_dq = deque(["e1", "e2"])
        self.action_dq = deque(["a1", "a2", "a3"])
        self.sequence_dq = deque(["s1", "s2"])
        self.ntp_offset = 0.0
        self.global_params = {}
        self.active_seq_exp_counter = 3
        self.active_run_id = "RUN"
        self.current_stop_message = ""
        self.world_cfg = {}
        self.interrupt_q = asyncio.Queue()
        self.fanout = []
        self.aloop = SimpleNamespace(create_task=lambda coro: coro.close())

    async def write_active_sequence_seq(self):
        pass

    async def write_exp(self, exp):
        pass

    async def write_seq(self, seq):
        pass

    async def intend_none(self):
        pass

    async def estop_actions(self, switch):
        return await self.estop_controller.estop_actions(switch)

    async def estop_finish_active(self):
        return await self.estop_controller.estop_finish_active()


@pytest.mark.asyncio
async def test_estop_finish_active_drops_the_finalized_sequences_orphans():
    orch = _EstopOrch()
    await orch.estop_controller.estop_finish_active()
    assert orch.active_sequence is None
    assert len(orch.experiment_dq) == 0
    assert len(orch.action_dq) == 0
    # queued OTHER sequences are not this sequence's orphans
    assert list(orch.sequence_dq) == ["s1", "s2"]


@pytest.mark.asyncio
async def test_estop_finish_active_without_an_active_sequence_leaves_queues():
    orch = _EstopOrch()
    orch.active_sequence = None
    await orch.estop_controller.estop_finish_active()
    assert list(orch.experiment_dq) == ["e1", "e2"]
    assert list(orch.action_dq) == ["a1", "a2", "a3"]


# --- C: E-STOP reaches the drivers --------------------------------------------


@pytest.mark.asyncio
async def test_estop_loop_latches_and_clear_estop_releases(monkeypatch):
    import helao.core.servers.orch as orch_mod

    sent = []

    async def fake_dispatch(world_cfg, A, params=None, **kw):
        sent.append(params["switch"])

    monkeypatch.setattr(orch_mod, "async_action_dispatcher", fake_dispatch)

    orch = _EstopOrch()
    server = SimpleNamespace(
        action_server=SimpleNamespace(
            as_dict=lambda: {"server_name": "SIM", "machine_name": "m"},
            disp_name=lambda: "SIM",
        )
    )
    orch.globalstatusmodel.server_dict = {("SIM", "m", 1): server}

    # Action() validates action_server; keep the payload out of the way
    from helao.hexagon.app import orch_estop

    monkeypatch.setattr(orch_estop, "Action", lambda **kw: SimpleNamespace(**kw))
    logged = []
    monkeypatch.setattr(
        orch_estop.LOGGER, "info", lambda msg, *a, **k: logged.append(msg)
    )

    await orch.estop_controller.estop_loop()
    assert sent == [True]  # drivers act only on switch=True
    assert "estopping all servers" in logged

    sent.clear()
    logged.clear()
    await orch.estop_controller.clear_estop()
    assert sent == [False]
    # a release must not read as an E-STOP in the station log
    assert "releasing E-STOP on all servers" in logged
    assert "estopping all servers" not in logged


# --- B2: the unpacker must not refill after E-STOP ------------------------------


class _UnpackOrch:
    """Just what ``seq_unpacker`` reads and writes."""

    def __init__(self, n=5):
        self.active_sequence = SimpleNamespace(
            sequence_uuid="seq-A",
            planned_experiments=[
                SimpleNamespace(data_request_id=None, name=i) for i in range(n)
            ],
        )
        self.seq_model = SimpleNamespace(data_request_id=None)
        self.globalstatusmodel = _GSM(LoopStatus.stopped)
        self.experiment_dq = deque()
        self.after_append = None

    async def add_experiment(self, seq, experimentmodel):
        await asyncio.sleep(0)
        self.experiment_dq.append(experimentmodel.name)
        if self.after_append:
            self.after_append(len(self.experiment_dq))


@pytest.mark.asyncio
async def test_unpacker_stops_appending_when_estop_lands_mid_unpack():
    from helao.core.servers.orch_unpack import seq_unpacker

    orch = _UnpackOrch()

    def estop_after_second(n):
        if n == 2:
            orch.globalstatusmodel.loop_state = LoopStatus.estopped
            orch.active_sequence = None  # what estop_finish_active does
            orch.experiment_dq.clear()  # ... and clears the queue

    orch.after_append = estop_after_second
    await seq_unpacker(orch)
    assert len(orch.experiment_dq) == 0  # nothing refilled after the clear


@pytest.mark.asyncio
async def test_unpacker_stops_when_a_different_sequence_became_active():
    from helao.core.servers.orch_unpack import seq_unpacker

    orch = _UnpackOrch()

    def swap(n):
        if n == 1:
            orch.active_sequence = SimpleNamespace(
                sequence_uuid="seq-B", planned_experiments=[]
            )

    orch.after_append = swap
    await seq_unpacker(orch)
    assert list(orch.experiment_dq) == [0]


@pytest.mark.asyncio
async def test_unpacker_unpacks_everything_when_nothing_intervenes():
    from helao.core.servers.orch_unpack import seq_unpacker

    orch = _UnpackOrch()
    await seq_unpacker(orch)
    assert list(orch.experiment_dq) == [0, 1, 2, 3, 4]
    assert orch.globalstatusmodel.loop_state == LoopStatus.started


def test_estop_fanout_switch_is_required():
    from helao.hexagon.domain.orchestration import EstopFanout

    with pytest.raises(TypeError):
        EstopFanout()  # type: ignore[call-arg]


# --- Round 3: the /{server_key}/estop route -------------------------------------


def _estop_route(host):
    return next(r for r in host.routes if getattr(r, "path", "") == "/SIM/estop")


class _RaisingEstopDriver:
    async def estop(self, switch):
        raise RuntimeError("axis Y unplugged")


class _Session:
    """Stands in for a running executor's session; records the stop request."""

    def __init__(self):
        self.stopped = False

    def stop_action_task(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_a_raising_driver_estop_does_not_abort_the_route(tmp_path):
    from helao.helpers.premodels import Action
    from helao.hexagon.app.action_session import ActionSession

    host = _host(tmp_path)
    host.driver = _RaisingEstopDriver()
    session = await ActionSession.open(host, Action(action_name="move"))
    executor = _Session()
    host.executors["exec-1"] = executor

    body = await _estop_route(host).endpoint(switch=True)

    assert host.actionservermodel.estop is True  # latched
    assert executor.stopped  # executors stopped
    assert body["estopped_actions"] == [str(session.action.action_uuid)]
    assert HloStatus.estopped in session.action.action_status
    assert session.action.action_uuid not in host.actives
    assert "axis Y unplugged" in body["driver"]["error"]
    assert body["estop"] is True


@pytest.mark.asyncio
async def test_releasing_the_latch_leaves_work_started_after_the_estop(tmp_path):
    from helao.helpers.premodels import Action
    from helao.hexagon.app.action_session import ActionSession

    host = _host(tmp_path)
    host.actionservermodel.estop = True
    session = await ActionSession.open(host, Action(action_name="batch"))
    executor = _Session()
    host.executors["exec-1"] = executor

    body = await _estop_route(host).endpoint(switch=False)

    assert host.actionservermodel.estop is False  # released
    assert body["estopped_actions"] == []
    assert not executor.stopped
    assert HloStatus.estopped not in session.action.action_status
    assert HloStatus.active in session.action.action_status
    assert host.actives[session.action.action_uuid] is session


# --- Round 4: orphaned experiments with no active sequence ----------------------


@pytest.mark.asyncio
async def test_dispatch_experiment_drops_orphans_when_no_sequence_is_active(
    monkeypatch,
):
    """An orphan that outlived clear_estop must not crash the next start.

    ``_stage_experiment`` dereferences ``active_sequence``; with it None and the
    loop no longer estopped, nothing else would stop the pop.
    """
    orch = _DispatchOrch(LoopStatus.started)
    orch.active_sequence = None
    _forbid_staging(monkeypatch, orch)

    rc = await orch.dispatch_runner.dispatch_experiment()

    assert rc is ErrorCodes.none
    assert len(orch.experiment_dq) == 0
    assert list(orch.sequence_dq) == ["seq1", "seq2"]  # untouched


@pytest.mark.asyncio
async def test_dispatch_experiment_keeps_the_queue_when_a_sequence_is_active(
    monkeypatch,
):
    orch = _DispatchOrch(LoopStatus.started)  # active_sequence == "SEQ"
    staged = []

    async def _stage():
        staged.append(1)
        raise StopAsyncIteration  # stop right after the pop is reached

    monkeypatch.setattr(orch.dispatch_runner, "_stage_experiment", _stage)
    with pytest.raises(StopAsyncIteration):
        await orch.dispatch_runner.dispatch_experiment()
    assert staged == [1]
    assert list(orch.experiment_dq) == ["exp1", "exp2"]


# --- Round 5 -------------------------------------------------------------------
# 1. unpacker: an E-STOP inside the first add_experiment await must survive


@pytest.mark.asyncio
async def test_unpacker_does_not_erase_an_estop_that_lands_in_the_first_add():
    from helao.core.servers.orch_unpack import seq_unpacker

    orch = _UnpackOrch()

    def estop_during_first(n):
        if n == 1:
            # the reducer's flip lands first; estop_finish_active has not run
            orch.globalstatusmodel.loop_state = LoopStatus.estopped

    orch.after_append = estop_during_first
    await seq_unpacker(orch)
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped  # not `started`
    assert list(orch.experiment_dq) == [0]  # nothing further appended


# 2. dispatch_sequence must not wedge waiting for an unpacker that gave up


class _SeqOrch:
    """The reviewer's probe: real Sequence/Experiment, real unpacker."""

    def __init__(self, flip_in=None, n_planned=3):
        from helao.core.models.machine import MachineModel
        from helao.core.servers.orch_unpack import seq_unpacker
        from helao.helpers.premodels import Experiment, Sequence
        from helao.hexagon.app.orch_dispatch import DispatchRunner

        self._seq_unpacker = seq_unpacker
        self.flip_in = flip_in
        self.globalstatusmodel = SimpleNamespace(loop_state=LoopStatus.started)
        seq = Sequence(sequence_name="s")
        seq.planned_experiments = [
            Experiment(experiment_name=f"e{i}") for i in range(n_planned)
        ]
        self.sequence_dq = deque([seq])
        self.experiment_dq = deque()
        self.action_dq = deque()
        self.active_sequence = None
        self.world_cfg = {}
        self.run_type = "x"
        self.server = MachineModel(server_name="ORCH", machine_name="m")
        self.ntp_offset = 0.0
        self.global_params = {}
        self.sequence_lib = {}
        self.use_sync = False
        self.verify_plates = False
        self.aloop = asyncio.get_running_loop()
        self.dispatch_runner = DispatchRunner(self)

    async def put_lbuf(self, d):
        pass

    def register_obj_uuid(self, *a):
        pass

    def _resolve_active_run_id(self, s):
        pass

    async def intend_none(self):
        pass

    async def seq_unpacker(self):
        return await self._seq_unpacker(self)

    def _estop(self):
        self.globalstatusmodel.loop_state = LoopStatus.estopped

    async def write_seq(self, s):
        await asyncio.sleep(0)
        if self.flip_in == "write_seq":
            self._estop()
        if self.flip_in == "finalized":
            self._estop()
            self.active_sequence = None  # estop_finish_active ran too

    async def add_experiment(self, seq, experimentmodel):
        await asyncio.sleep(0.01)
        if self.flip_in == "add_experiment" and not self.experiment_dq:
            self._estop()
        self.experiment_dq.append(experimentmodel)


@pytest.mark.asyncio
@pytest.mark.parametrize("flip_in", ["write_seq", "add_experiment", "finalized"])
async def test_dispatch_sequence_returns_promptly_when_estopped_before_unpack_ends(
    flip_in,
):
    orch = _SeqOrch(flip_in)
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    # When the E-STOP lands inside the first add, that experiment still reaches
    # the queue, the wait ends normally, and the loop handles the estopped state.
    assert rc is (ErrorCodes.none if flip_in == "add_experiment" else ErrorCodes.estop)
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped


@pytest.mark.asyncio
async def test_dispatch_sequence_returns_when_the_unpacker_finished_with_nothing():
    orch = _SeqOrch(n_planned=0)  # a sequence with no planned experiments
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.none
    assert len(orch.experiment_dq) == 0


@pytest.mark.asyncio
async def test_dispatch_sequence_still_waits_for_a_slow_unpacker_and_returns():
    orch = _SeqOrch()
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.none
    assert len(orch.experiment_dq) >= 1
    await asyncio.sleep(0.1)
    assert len(orch.experiment_dq) == 3


# 3. an executor-backed action is finalized once, not once by /estop and again
#    by the executor loop


@pytest.mark.asyncio
async def test_estop_then_late_executor_finish_runs_the_tail_once(
    tmp_path, monkeypatch
):
    import helao.hexagon.adapters.native.finalizer as fin
    from helao.helpers.premodels import Action
    from helao.hexagon.app.action_session import ActionSession

    counts = {"move_dir": 0, "prefinish": 0, "write_act": 0, "status_put": 0}

    async def fake_move_dir(*a, **k):
        counts["move_dir"] += 1

    async def fake_prefinish(*a, **k):
        counts["prefinish"] += 1

    monkeypatch.setattr(fin, "move_dir", fake_move_dir)
    monkeypatch.setattr(fin, "run_prefinish", fake_prefinish)

    host = _host(tmp_path)
    host.aloop = asyncio.get_running_loop()
    orig_write_act = host.write_act

    async def counting_write_act(*a, **k):
        counts["write_act"] += 1
        return await orig_write_act(*a, **k)

    host.write_act = counting_write_act
    session = await ActionSession.open(host, Action(action_name="scan"))
    orig_put = host.status_q.put

    async def counting_put(x):
        counts["status_put"] += 1
        return await orig_put(x)

    host.status_q.put = counting_put

    await _estop_route(host).endpoint(switch=True)
    await asyncio.sleep(0.2)  # move_dir is fire-and-forget
    after_estop = dict(counts)
    assert after_estop["prefinish"] == 1 and after_estop["move_dir"] == 1

    # the executor loop's own finish, arriving after the E-STOP's
    await session.finish()
    await asyncio.sleep(0.2)
    assert counts == after_estop, (after_estop, counts)


# 4. the action path after an E-STOP that lands during the start-condition wait


@pytest.mark.asyncio
async def test_launch_action_bails_when_estop_lands_during_the_start_wait():
    from helao.helpers.premodels import Action
    from helao.hexagon.app.orch_dispatch import DispatchRunner
    from helao.hexagon.domain.models import LoopIntent

    class Orch:
        def __init__(self):
            self.globalstatusmodel = SimpleNamespace(
                loop_state=LoopStatus.started,
                loop_intent=LoopIntent.none,
                counter_dispatched_actions={"E": 0},
            )
            self.active_experiment = SimpleNamespace(experiment_uuid="E")
            self.action_dq = deque([Action(action_name="next")])
            self.global_params = {}
            self.active_run_id = None
            self.ntp_offset = 0.0
            self.dispatch_runner = DispatchRunner(self)

        async def intend_none(self):
            pass

        async def orch_wait_for_all_actions(self):
            await asyncio.sleep(0)
            self.globalstatusmodel.loop_state = LoopStatus.estopped
            self.active_experiment = None  # estop_finish_active
            self.globalstatusmodel.counter_dispatched_actions = {}
            self.action_dq.clear()

    o = Orch()
    rc = await o.dispatch_runner._launch_action()
    assert rc is ErrorCodes.estop


# 6. the fan-out reaching a REAL /{server_key}/estop route, not a spy


class _RecordingDriver:
    def __init__(self):
        self.received = []

    async def estop(self, switch):
        self.received.append(switch)
        return switch


@pytest.mark.parametrize("switch", [True, False])
def test_http_estop_arrives_as_a_real_bool(tmp_path, switch):
    """Exactly what ``async_action_dispatcher``'s HTTP fallback sends:
    ``params=_query_safe({"switch": ...})`` plus ``json={"action": ...}``.
    A string ``"false"`` that reached the driver would be truthy."""
    from starlette.testclient import TestClient

    from helao.helpers.dispatcher import _query_safe
    from helao.helpers.premodels import Action

    host = _host(tmp_path)
    host.driver = _RecordingDriver()
    A = Action(action_name="estop", action_params={"switch": switch})
    resp = TestClient(host).post(
        "/SIM/estop",
        params=_query_safe({"switch": switch}),
        json={"action": A.as_dict()},
    )
    assert resp.status_code == 200, resp.text
    assert host.driver.received == [switch]
    assert type(host.driver.received[0]) is bool
    assert host.actionservermodel.estop is switch


# --- Round 6 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_sequence_logs_an_unpacker_that_raised(monkeypatch):
    import helao.hexagon.app.orch_dispatch as od

    logged = []
    monkeypatch.setattr(
        od.LOGGER, "error", lambda msg, *a, **k: logged.append((msg, k.get("exc_info")))
    )
    orch = _SeqOrch()

    async def boom():
        raise ValueError("bad plan")

    orch.seq_unpacker = boom
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.none
    assert any(
        isinstance(exc, ValueError) and "unpacker" in msg for msg, exc in logged
    ), logged


@pytest.mark.asyncio
async def test_dispatch_sequence_survives_a_cancelled_unpacker():
    orch = _SeqOrch()

    async def cancelled():
        raise asyncio.CancelledError

    orch.seq_unpacker = cancelled
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.none


def _launch_orch(loop_state):
    from helao.helpers.premodels import Action
    from helao.hexagon.app.orch_dispatch import DispatchRunner
    from helao.hexagon.domain.models import LoopIntent

    class Orch:
        def __init__(self):
            self.globalstatusmodel = SimpleNamespace(
                loop_state=loop_state,
                loop_intent=LoopIntent.none,
                counter_dispatched_actions={},
            )
            self.active_experiment = None
            self.action_dq = deque([Action(action_name="next")])
            self.global_params = {}
            self.active_run_id = None
            self.ntp_offset = 0.0
            self.dispatch_runner = DispatchRunner(self)

        async def intend_none(self):
            pass

        async def orch_wait_for_all_actions(self):
            pass

    return Orch()


@pytest.mark.asyncio
async def test_launch_action_drops_the_head_action_when_no_experiment_is_active(
    monkeypatch,
):
    """The None clause on its own: the loop is NOT estopped."""
    import helao.hexagon.app.orch_dispatch as od

    warned = []
    monkeypatch.setattr(od.LOGGER, "warning", lambda msg, *a, **k: warned.append(msg))
    o = _launch_orch(LoopStatus.started)
    rc = await o.dispatch_runner._launch_action()
    assert rc is ErrorCodes.estop
    assert not o.action_dq  # dropped, not left to loop on
    assert any(
        "no active experiment for head action next; dropping it" in m for m in warned
    ), warned


# --- Round 7: the route leaves evidence that the E-STOP happened ----------------


@pytest.mark.asyncio
@pytest.mark.parametrize("switch,word", [(True, "latch"), (False, "release")])
async def test_estop_route_logs_one_evidence_line(tmp_path, monkeypatch, switch, word):
    """A drill found MOTOR/KMOTOR logged nothing at the E-STOP, so nothing showed
    the stop had happened. The line names the driver's reply and what was finalized."""
    import helao.hexagon.app.action_host as ah

    host = _host(tmp_path)  # built first: its constructor logs too
    host.driver = _RecordingDriver()
    logged = []
    monkeypatch.setattr(ah.LOGGER, "info", lambda msg, *a, **k: logged.append(msg))

    await _estop_route(host).endpoint(switch=switch)

    assert logged == [
        f"E-STOP {word} on SIM: driver={switch!r}, estopped_actions=[]"
    ], logged


@pytest.mark.asyncio
async def test_estop_evidence_line_follows_a_driver_failure(tmp_path, monkeypatch):
    import helao.hexagon.app.action_host as ah

    host = _host(tmp_path)
    host.driver = _RaisingEstopDriver()
    logged = []
    monkeypatch.setattr(ah.LOGGER, "info", lambda msg, *a, **k: logged.append(msg))
    monkeypatch.setattr(ah.LOGGER, "exception", lambda *a, **k: None)

    await _estop_route(host).endpoint(switch=True)

    assert len(logged) == 1 and logged[0].startswith("E-STOP latch on SIM: driver=")
    assert "axis Y unplugged" in logged[0]


# --- Round 8: a hung driver must not stop the E-STOP ---------------------------


class _HangingEstopDriver:
    async def estop(self, switch):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_a_hanging_driver_estop_is_bounded_and_the_latch_still_lands(
    tmp_path, monkeypatch
):
    """A wedged driver (e.g. a stuck GamryCOM thread) used to block the route
    before it latched. The bound is on the awaited call; a driver blocking the
    loop synchronously cannot be interrupted by it (accepted)."""
    from helao.helpers.premodels import Action
    from helao.hexagon.app.action_session import ActionSession
    import helao.hexagon.app.action_host as ah

    host = _host(tmp_path)
    host.driver = _HangingEstopDriver()
    session = await ActionSession.open(host, Action(action_name="move"))
    executor = _Session()
    host.executors["exec-1"] = executor
    errors, logged = [], []
    monkeypatch.setattr(ah, "ESTOP_DRIVER_TIMEOUT_S", 0.05)
    monkeypatch.setattr(ah.LOGGER, "error", lambda msg, *a, **k: errors.append(msg))
    monkeypatch.setattr(ah.LOGGER, "info", lambda msg, *a, **k: logged.append(msg))

    body = await asyncio.wait_for(_estop_route(host).endpoint(switch=True), 2.0)

    assert body["driver"] == {"error": "timeout"}
    assert host.actionservermodel.estop is True
    assert executor.stopped
    assert body["estopped_actions"] == [str(session.action.action_uuid)]
    assert any("SIM" in m and "timed out" in m for m in errors), errors
    assert any(m.startswith("E-STOP latch on SIM") for m in logged), logged


def test_the_driver_bound_stays_under_the_dispatcher_rpc_probe():
    import helao.hexagon.app.action_host as ah

    assert ah.ESTOP_DRIVER_TIMEOUT_S == 2.0  # dispatcher's RPC probe is 3 s


def _fanout_orch(monkeypatch, names, hang):
    import helao.core.servers.orch as orch_mod
    from helao.hexagon.app import orch_estop

    received, logged = [], []

    async def fake_dispatch(world_cfg, A, params=None, **kw):
        name = A.action_server
        received.append(name)
        if name == hang:
            await asyncio.sleep(3600)
        if name == "BOOM":
            raise RuntimeError("no estop endpoint")

    monkeypatch.setattr(orch_mod, "async_action_dispatcher", fake_dispatch)
    monkeypatch.setattr(orch_estop, "Action", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(
        orch_estop.LOGGER, "info", lambda msg, *a, **k: logged.append(msg)
    )
    monkeypatch.setattr(
        orch_estop.LOGGER, "error", lambda msg, *a, **k: logged.append(msg)
    )
    orch = _EstopOrch()
    orch.globalstatusmodel.server_dict = {
        (n, "m", 1): SimpleNamespace(
            action_server=SimpleNamespace(
                as_dict=lambda n=n: n, disp_name=lambda n=n: n
            )
        )
        for n in names
    }
    return orch, received, logged


@pytest.mark.asyncio
async def test_a_server_whose_estop_never_returns_does_not_starve_the_others(
    monkeypatch,
):
    orch, received, logged = _fanout_orch(monkeypatch, ["A", "B", "C"], hang="A")
    task = asyncio.ensure_future(orch.estop_controller.estop_actions(True))
    try:

        async def _all_received():
            while set(received) != {"A", "B", "C"}:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_all_received(), 1.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    sends = [m for m in logged if m.startswith("Sending estop=")]
    assert sends == [f"Sending estop=True request to {n}" for n in "ABC"]


@pytest.mark.asyncio
async def test_a_failing_server_is_logged_and_the_others_still_get_the_estop(
    monkeypatch,
):
    orch, received, logged = _fanout_orch(monkeypatch, ["BOOM", "B"], hang=None)
    await orch.estop_controller.estop_actions(True)
    assert received == ["BOOM", "B"]
    assert any("estop for BOOM failed" in m for m in logged), logged


@pytest.mark.asyncio
async def test_estop_actions_returns_when_a_server_never_answers(monkeypatch):
    """A server with a frozen loop hangs its dispatch forever (the HTTP fallback
    has no total timeout). Unbounded, ``estop_actions`` never returned, so the
    stop message and the alert after it never ran."""
    from helao.hexagon.app import orch_estop

    monkeypatch.setattr(orch_estop, "ESTOP_SEND_TIMEOUT_S", 0.2)
    orch, received, logged = _fanout_orch(monkeypatch, ["A", "B", "C"], hang="A")

    await asyncio.wait_for(orch.estop_controller.estop_actions(True), 2.0)

    assert set(received) == {"A", "B", "C"}
    assert any("estop for A" in m and "timed out" in m for m in logged), logged
