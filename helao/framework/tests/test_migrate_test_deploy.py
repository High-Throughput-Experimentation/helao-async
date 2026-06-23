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
