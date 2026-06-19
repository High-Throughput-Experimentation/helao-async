"""Orchestrator-access backends for the Bokeh operator UI.

The :class:`BokehOperator` UI talks only to an :class:`OrchBackend`. Two
implementations exist: :class:`LocalBackend` wraps a live in-process
:class:`~helao.core.servers.orch.Orch`; :class:`RemoteBackend` (added later)
drives a remote orchestrator over OrchAPI HTTP/RPC endpoints.

List/state methods return *normalized plain dicts* so the UI never has to
branch on object-vs-JSON. See the method docstrings for the contract.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Optional

from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.ws_utils import WsSubscriber as Wss
from helao.core.error import ErrorCodes

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class OrchBackend(ABC):
    """Abstract orchestrator access used by :class:`BokehOperator`."""

    #: name -> callable sequence library (local in every backend)
    sequence_lib: dict
    #: name -> callable experiment library (local in every backend)
    experiment_lib: dict

    @abstractmethod
    def unpack_sequence(self, sequence_name: str, sequence_params: dict) -> list:
        """Expand a library sequence into a list of planned Experiment models."""

    @abstractmethod
    def get_step_flags(self) -> dict:
        """Return {'actions': bool, 'experiments': bool, 'sequences': bool}."""

    @abstractmethod
    async def set_step_flag(self, kind: str, value: bool) -> None:
        """Set one step-through flag ('actions'|'experiments'|'sequences')."""

    @abstractmethod
    async def list_sequences(self) -> list: ...

    @abstractmethod
    async def list_experiments(self) -> list: ...

    @abstractmethod
    async def list_actions(self) -> list: ...

    @abstractmethod
    async def get_histories(self) -> dict: ...

    @abstractmethod
    async def get_status_summary(self) -> dict: ...

    @abstractmethod
    async def get_orch_state(self) -> dict: ...

    @abstractmethod
    async def add_sequence(self, sequence) -> object: ...

    @abstractmethod
    async def add_split_sequences(self, sequence) -> object: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def skip(self) -> None: ...

    @abstractmethod
    async def estop(self) -> None: ...

    @abstractmethod
    async def clear_sequences(self) -> None: ...

    @abstractmethod
    async def clear_experiments(self) -> None: ...

    @abstractmethod
    async def clear_actions(self) -> None: ...

    @abstractmethod
    def subscribe(self, on_change: Callable[[], None]) -> None:
        """Register a callback fired whenever orch state may have changed."""

    @abstractmethod
    def close(self) -> None:
        """Tear down subscriptions / background tasks."""


_SEQ_KEYS = ["sequence_name", "sequence_label", "sequence_uuid", "campaign_name", "campaign_uuid"]
_EXP_KEYS = ["experiment_name", "experiment_uuid"]
_STEP_ATTRS = {
    "actions": "step_thru_actions",
    "experiments": "step_thru_experiments",
    "sequences": "step_thru_sequences",
}


class _OpShim:
    """Tiny stand-in for the in-orch operator: routes update_q puts to on_change."""

    def __init__(self, on_change):
        import asyncio
        self.update_q = asyncio.Queue()
        self._on_change = on_change
        self._task = asyncio.create_task(self._drain())

    async def _drain(self):
        while True:
            await self.update_q.get()
            self._on_change()

    def cancel(self):
        self._task.cancel()


class LocalBackend(OrchBackend):
    """Pass-through backend wrapping a live in-process Orch."""

    def __init__(self, orch):
        self.orch = orch
        self.sequence_lib = orch.sequence_lib
        self.experiment_lib = orch.experiment_lib
        self._shim = None

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.orch.unpack_sequence(
            sequence_name=sequence_name, sequence_params=sequence_params
        )

    def get_step_flags(self):
        return {kind: getattr(self.orch, attr) for kind, attr in _STEP_ATTRS.items()}

    async def set_step_flag(self, kind, value):
        setattr(self.orch, _STEP_ATTRS[kind], bool(value))

    async def list_sequences(self):
        return [{k: s.as_dict().get(k) for k in _SEQ_KEYS} for s in self.orch.list_sequences()]

    async def list_experiments(self):
        return [{k: e.as_dict().get(k) for k in _EXP_KEYS} for e in self.orch.list_experiments()]

    async def list_actions(self):
        out = []
        for a in self.orch.list_actions():
            d = a.as_dict()
            out.append({
                "action_name": d.get("action_name"),
                "action_server": a.action_server.disp_name(),
                "action_uuid": d.get("action_uuid"),
            })
        return out

    async def get_histories(self):
        return {
            "action": list(self.orch.action_history.items()),
            "experiment": list(self.orch.experiment_history.items()),
            "sequence": list(self.orch.sequence_history.items()),
        }

    async def get_status_summary(self):
        return {k: list(v) for k, v in self.orch.status_summary.items()}

    async def get_orch_state(self):
        gsm = self.orch.globalstatusmodel
        aseq = self.orch.active_sequence
        aexp = self.orch.active_experiment
        return {
            "loop_state": gsm.loop_state,
            "active_sequence": aseq.clean_dict() if aseq else {},
            "active_experiment": aexp.clean_dict() if aexp else {},
            "n_sequences": len(self.orch.sequence_dq),
            "n_experiments": len(self.orch.experiment_dq),
            "n_actions": len(self.orch.action_dq),
            "current_stop_message": self.orch.current_stop_message,
        }

    async def add_sequence(self, sequence):
        return await self.orch.add_sequence(sequence=sequence)

    async def add_split_sequences(self, sequence):
        return await self.orch.add_split_sequences(sequence=sequence)

    async def start(self):
        await self.orch.start()

    async def stop(self):
        await self.orch.stop()

    async def skip(self):
        await self.orch.skip()

    async def estop(self):
        await self.orch.estop_loop()

    async def clear_sequences(self):
        await self.orch.clear_sequences()

    async def clear_experiments(self):
        await self.orch.clear_experiments()

    async def clear_actions(self):
        await self.orch.clear_actions()

    def subscribe(self, on_change):
        self._shim = _OpShim(on_change)
        self.orch.orch_op = self._shim

    def close(self):
        if self._shim is not None:
            self._shim.cancel()
        self.orch.orch_op = None


class RemoteBackend(OrchBackend):
    """Backend that drives a remote orchestrator over OrchAPI endpoints.

    Libraries are loaded locally (identical config -> identical libs as the
    orch), so param panels and sequence unpacking run in-process; all queue
    reads and control go over HTTP/RPC. Live refresh comes from the orch's
    ws_status WebSocket plus a slow poll safety net.
    """

    def __init__(self, vis, orch_key: Optional[str] = None, poll_interval: float = 5.0):
        self.vis = vis
        self.world_cfg = vis.world_cfg
        self.orch_key = orch_key or self._detect_orch_key(vis.world_cfg)
        srv = vis.world_cfg["servers"][self.orch_key]
        self.host = srv["host"]
        self.port = srv["port"]
        self.poll_interval = poll_interval
        self._dispatch = async_private_dispatcher

        self.experiment_lib, _, _ = import_autolibs(
            world_config_dict=vis.world_cfg, lib_dir=None,
            user_lib_dir=vis.helaodirs.user_exp, lib_type="experiment",
        )
        self.sequence_lib, _, _ = import_autolibs(
            world_config_dict=vis.world_cfg, lib_dir=None,
            user_lib_dir=vis.helaodirs.user_seq, lib_type="sequence",
        )
        self._step_flags = {"actions": False, "experiments": False, "sequences": False}
        self._wss = None
        self._ws_task = None
        self._poll_task = None
        self._prime_task = None

    @staticmethod
    def _detect_orch_key(world_cfg) -> str:
        orch_keys = [
            k for k, v in world_cfg["servers"].items()
            if v.get("group") == "orchestrator"
        ]
        if not orch_keys:
            raise ValueError("RemoteBackend: no group:orchestrator server in config")
        return orch_keys[0]

    async def _call(self, endpoint, params_dict=None, json_dict=None):
        resp, err = await self._dispatch(
            self.orch_key, self.host, self.port, endpoint,
            params_dict=params_dict or {}, json_dict=json_dict or {},
        )
        if err != ErrorCodes.none:
            LOGGER.warning(f"RemoteBackend {endpoint} failed: {err}")
            return None
        return resp

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._step_flags)

    async def set_step_flag(self, kind, value):
        await self._call("set_step_flag", params_dict={"kind": kind, "value": value})
        self._step_flags[kind] = bool(value)

    async def list_sequences(self):
        resp = await self._call("list_sequences") or []
        return [{k: row.get(k) for k in _SEQ_KEYS} for row in resp]

    async def list_experiments(self):
        resp = await self._call("list_experiments") or []
        return [{k: row.get(k) for k in _EXP_KEYS} for row in resp]

    async def list_actions(self):
        resp = await self._call("list_actions") or []
        out = []
        for row in resp:
            srv = row.get("action_server")
            srv_name = srv.get("server_name") if isinstance(srv, dict) else srv
            out.append({
                "action_name": row.get("action_name"),
                "action_server": srv_name,
                "action_uuid": row.get("action_uuid"),
            })
        return out

    async def get_histories(self):
        resp = await self._call("get_histories")
        return resp or {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        resp = await self._call("get_status_summary")
        return resp or {}

    async def get_orch_state(self):
        resp = await self._call("get_orch_state")
        return resp or {}

    async def add_sequence(self, sequence):
        return await self._call("append_sequence", json_dict={"sequence": sequence.model_dump()})

    async def add_split_sequences(self, sequence):
        return await self._call("append_split_sequences", json_dict={"sequence": sequence.model_dump()})

    async def start(self):
        await self._call("start")

    async def stop(self):
        await self._call("stop")

    async def skip(self):
        await self._call("skip_experiment")

    async def estop(self):
        await self._call("estop_orch")

    async def clear_sequences(self):
        await self._call("clear_sequences")

    async def clear_experiments(self):
        await self._call("clear_experiments")

    async def clear_actions(self):
        await self._call("clear_actions")

    def subscribe(self, on_change):
        async def _prime():
            resp = await self._call("get_step_flags")
            if resp:
                self._step_flags.update(resp)
            on_change()
        self._wss = Wss(self.host, self.port, "ws_status")
        self._ws_task = asyncio.create_task(self._ws_loop(on_change))
        self._poll_task = asyncio.create_task(self._poll_loop(on_change))
        self._prime_task = asyncio.create_task(_prime())

    async def _ws_loop(self, on_change):
        while True:
            try:
                msgs = await self._wss.read_messages()
                if msgs:
                    on_change()
            except Exception:
                LOGGER.warning("RemoteBackend ws_status read failed", exc_info=True)
                await asyncio.sleep(1.0)
            await asyncio.sleep(0.05)

    async def _poll_loop(self, on_change):
        while True:
            await asyncio.sleep(self.poll_interval)
            on_change()

    def close(self):
        for t in (self._ws_task, self._poll_task, self._prime_task):
            if t is not None:
                t.cancel()
