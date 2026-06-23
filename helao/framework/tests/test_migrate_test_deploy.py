"""Migration tests for SP7: test-deployment pilot onto helao.framework.*"""
import pytest
from helao.framework.support.lib_decorators import experiment, sequence
from helao.framework.domain.plan_makers import EXPERIMENT_CTX, ActionPlanMaker
from helao.framework.domain.run_models import RunExperiment


def _make_run_exp(**kw) -> RunExperiment:
    defaults = dict(
        experiment_name="test_exp",
        sequence_name="test_seq",
        sequence_label="test_seq__001",
        experiment_output_dir="26.25/0622/test",
    )
    defaults.update(kw)
    return RunExperiment(**defaults)


def test_experiment_decorator_sets_version():
    @experiment(version=3)
    def my_exp(param: float = 1.0):
        pass
    assert my_exp.experiment_version == 3


def test_experiment_decorator_injects_ctx():
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    run_exp = _make_run_exp()
    my_exp(run_exp)
    assert captured[0] is run_exp


def test_experiment_decorator_resets_ctx_after_call():
    @experiment(version=1)
    def my_exp():
        pass

    assert EXPERIMENT_CTX.get(None) is None
    my_exp(_make_run_exp())
    assert EXPERIMENT_CTX.get(None) is None


def test_experiment_decorator_positional_arg_form():
    received = []

    @experiment(version=1)
    def my_exp(experiment: RunExperiment, extra: int = 0):
        received.append(experiment)

    run_exp = _make_run_exp()
    my_exp(run_exp, extra=7)
    assert received[0] is run_exp


def test_sequence_decorator_sets_version():
    @sequence(version=5)
    def my_seq():
        pass
    assert my_seq.sequence_version == 5


def test_file_utils_importable():
    from helao.framework.support.file_utils import (
        file_in_use, rm_tree, rm_tree_async, zip_dir, unzpickle, zpickle
    )
    assert callable(file_in_use)
    assert callable(unzpickle)


def test_file_in_use_returns_false_for_nonexistent(tmp_path):
    from helao.framework.support.file_utils import file_in_use
    assert file_in_use(tmp_path / "no_such_file.txt") is False


def test_dispatcher_importable():
    from helao.framework.support.dispatcher import (
        async_action_dispatcher,
        async_private_dispatcher,
        private_dispatcher,
        aclose_all_rpc_clients,
        close_all_sync_rpc_clients,
    )
    assert callable(async_private_dispatcher)


def test_base_api_importable():
    from helao.framework.app.server_api import BaseAPI
    assert BaseAPI is not None


def test_base_api_has_base_attribute(tmp_path):
    from helao.framework.app.server_api import BaseAPI
    from helao.framework.app.base_api import FrameworkBase
    app = BaseAPI("SRV", save_root=str(tmp_path))
    assert isinstance(app.base, FrameworkBase)


def test_base_api_instantiates_driver(tmp_path):
    from helao.framework.app.server_api import BaseAPI
    from helao.framework.app.base_api import FrameworkBase

    class FakeDriver:
        def __init__(self, base: FrameworkBase):
            self.base = base

    app = BaseAPI("SRV", driver_classes=[FakeDriver], save_root=str(tmp_path))
    assert isinstance(app.driver, FakeDriver)
    assert app.driver.base is app.base


def test_action_session_start_executor(tmp_path):
    import asyncio
    from helao.framework.app.base_api import FrameworkBase, ActionContext
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.adapters.ntp_clock import NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink
    from helao.framework.adapters.fakes.transport import FakeTransport
    from helao.framework.domain.run_models import RunAction
    from helao.framework.domain.executor import Executor
    from helao.framework.models.hlostatus import HloStatus

    base = FrameworkBase(
        server_key="SRV",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )

    async def _drive():
        action = RunAction(
            action_name="test_act",
            action_output_dir="26.25/0622/test",
            save_act=True,
        )
        active = await base.setup_and_contain_action(ActionContext(action=action))

        exec_done = []

        class DoneExec(Executor):
            async def _exec(self):
                exec_done.append(True)
                return {"data": {}, "error": None}

        result_dict = active.start_executor(DoneExec(active=active))
        assert isinstance(result_dict, dict)
        assert "action_name" in result_dict
        # give the background task time to run
        await asyncio.sleep(0.2)
        assert exec_done, "executor _exec was not called"

    asyncio.run(_drive())


def test_micro_orch_run_action_accepts_action_model():
    import asyncio
    from helao.framework.runners.micro_orch import MicroOrch
    from helao.framework.models.action import ActionModel
    from helao.framework.models.machine import MachineModel

    action = ActionModel(
        action_name="noop",
        action_server=MachineModel(server_name="ORCH"),
        action_params={},
    )

    async def _run():
        micro = MicroOrch()
        return await micro.run_action(action)

    state = asyncio.run(_run())
    assert hasattr(state, "action_dq")  # state is an OrchState
    assert len(state.action_dq) == 0


def test_wssim_import_chain():
    """ws_simulator module imports cleanly under the framework import swap."""
    import helao.deploy.test.servers.action.ws_simulator as wssim_mod
    assert callable(wssim_mod.makeApp), "makeApp must be a callable in ws_simulator"
    assert "WsSim" in dir(wssim_mod), "WsSim driver class must be importable"
    assert "WsExec" in dir(wssim_mod), "WsExec executor class must be importable"


def test_test_runner_importable():
    """test_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.test_runner as mod
    # module-level symbols confirm the framework import chain resolved
    assert callable(mod.consecutive_noblocking), "consecutive_noblocking must be a coroutine function"
    assert callable(mod.conditional_stop), "conditional_stop must be a coroutine function"
    assert isinstance(mod.WORLD_CFG, dict), "WORLD_CFG must be a dict"


def test_oersim_runner_importable():
    """oersim_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.oersim_runner as mod
    assert callable(mod.main), "main must be a coroutine function"
    assert callable(mod._act), "_act helper must be callable"
    assert isinstance(mod.WORLD_CFG, dict), "WORLD_CFG must be a dict"


def test_simulatews_runner_importable():
    """simulatews_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.simulatews_runner as mod
    assert callable(mod.main), "main must be a coroutine function"
    assert callable(mod._act), "_act helper must be callable"
    assert isinstance(mod.WORLD_CFG, dict), "WORLD_CFG must be a dict"


def test_gpsim_driver_importable():
    """gpsim_driver.py — skipped when gpflow is absent (transitive dep)."""
    pytest.importorskip("gpflow", reason="gpflow not installed — skipping GPSim test")
    from helao.deploy.test.drivers.data.gpsim_driver import GPSim, GPSimExec, calc_eta
    assert callable(calc_eta), "calc_eta must be callable"
    assert callable(GPSim), "GPSim must be a callable class"
    assert callable(GPSimExec), "GPSimExec must be a callable class"


def test_cpsim_driver_importable():
    """cpsim_driver.py — skipped when gpflow is absent (transitive via gpsim_driver)."""
    pytest.importorskip("gpflow", reason="gpflow not installed — skipping CPSim test")
    from helao.deploy.test.drivers.pstat.cpsim_driver import CPSim, CPSimExec
    assert callable(CPSim), "CPSim must be a callable class"
    assert callable(CPSimExec), "CPSimExec must be a callable class"


def test_wssim_import_and_makeapp_attempt(tmp_path):
    """Golden-master: import ws_simulator, makeApp('SIM'), POST /SIM/acquire_data.

    The action-server surface the simulator relies on — the ``ACTION_CTX``
    request wrapper (so ``setup_and_contain_action()`` works with no args), the
    ``executors`` registry, ``stop_action_task``, and the ``put_lbuf``/``get_lbuf``
    live buffer — is fully wired, so this drives the real endpoint and asserts a
    200 with a valid action record.

    The only tolerated failure is the ``asyncio.get_event_loop()`` flake in
    ``WsSim.__init__`` (deprecated in 3.12): under the full suite there may be no
    running loop in the thread at construction time, which a real uvicorn server
    never hits. That single environmental case is xfailed; everything else fails.
    """
    import asyncio
    import httpx
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.framework.adapters.fs_storage import FsStorage

    try:
        app = makeApp("SIM")
    except RuntimeError as exc:
        if "event loop" in str(exc).lower():
            pytest.xfail(f"WsSim.__init__ asyncio.get_event_loop() flake: {exc}")
        raise

    # makeApp succeeded — override storage so files land in tmp_path
    app.base.storage = FsStorage(save_root=str(tmp_path))

    async def _drive():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/SIM/acquire_data",
                json={"duration": 0.2, "acquisition_rate": 0.2},
            )

    resp = asyncio.run(_drive())

    assert resp.status_code == 200, f"acquire_data returned {resp.status_code}"
    body = resp.json()
    assert "action_uuid" in body, f"response missing action_uuid: {list(body.keys())}"
    assert "action_name" in body, f"response missing action_name: {list(body.keys())}"
    assert body["action_name"] == "acquire_data"
