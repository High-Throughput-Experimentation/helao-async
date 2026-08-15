"""Hexagon-native orchestrator host (B3a).

Legacy's shape is ``OrchAPI(HelaoFastAPI)`` holding ``self.orch =
Orch(Base)``. Two objects, and the API layer is a SIBLING of ``BaseAPI``
rather than a subclass -- which is why the two WS encoding families differ
and must stay independently frozen.

The native shape collapses that: ``OrchHost(ActionHost)`` is the app, the
orchestrator, and the action server it has always also been (9 of its 72
routes are ``/{server_key}/...`` action endpoints -- ``wait``, ``interrupt``,
``estop`` and friends -- which is why GM captures contain ``ORCH__wait``
directories). It answers to ``host.orch`` and ``host.base``, both of which
are ``self``: ``orch_api`` reaches ``self.orch.<member>`` at 60 sites and
``Orch`` inherits ``Base``, so inventing an indirection would buy nothing.

Scope: construction, state, the queue/persistence/estop/lifecycle
collaborators, and every route that does not run the loop. The dispatch
loop, status ingestion and the monitors are B3b; their routes are
registered here and raise, so a caller fails at the call site instead of
receiving a 404 that reads like a missing server.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.error import ErrorCodes
from helao.core.models.orchstatus import LoopIntent, LoopStatus
from helao.core.models.server import ActionServerModel, GlobalStatusModel
from helao.core.servers import orch_unpack
from helao.helpers import helao_logging as logging
from helao.helpers.dequedict import DequeDict
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.processors import MetaProcessor
from helao.helpers.server_keys import resolve_sync_server_key
from helao.helpers.zdeque import zdeque

if TYPE_CHECKING:  # pragma: no cover - typing only
    from helao.core.servers.base import Active
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import ORCH_REQUIRED, PortWiring

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["OrchHost"]


class OrchHost(ActionHost):
    """The native orchestrator server."""

    def __init__(
        self,
        server_key: str,
        server_title: str,
        description: str,
        version: float = 3.0,
        wiring: Optional[PortWiring] = None,
        helao_cfg: Optional[dict] = None,
    ):
        """Build the orchestrator, its state, and its collaborators.

        Args:
            server_key: Server key in the launched config.
            server_title: OpenAPI title.
            description: OpenAPI description.
            version: Server version.
            wiring: Composed ports; built from the global config when omitted.
            helao_cfg: Config dict to use instead of the global ``CONFIG``.
        """
        super().__init__(
            server_key=server_key,
            server_title=server_title,
            description=description,
            version=version,
            driver_classes=None,
            wiring=wiring,
            helao_cfg=helao_cfg,
        )
        self.hexagon_wiring.require(*ORCH_REQUIRED)

        # --- orch.py:95-112: the experiment and sequence libraries -------
        # Resolved relative to the CWD by import_autolibs, which is why a
        # process running from anywhere but the repo root gets an EMPTY
        # library plus one ERROR line, and an operator with nothing to
        # select. The Reflex operator hit exactly this.
        (
            self.experiment_lib,
            self.experiment_codehash_lib,
            self.experiment_codepath_lib,
        ) = import_autolibs(
            world_config_dict=self.world_cfg,
            lib_dir=None,
            user_lib_dir=self.helaodirs.user_exp,
            lib_type="experiment",
        )
        self.sequence_lib, self.sequence_codehash_lib, self.sequence_codepath_lib = (
            import_autolibs(
                world_config_dict=self.world_cfg,
                lib_dir=None,
                user_lib_dir=self.helaodirs.user_seq,
                lib_type="sequence",
            )
        )

        # --- orch.py:114-119: the syncer --------------------------------
        # B7 follow-up, recorded not fixed: this is the legacy HelaoSyncer,
        # imported from helao/core/drivers/. The native re-body lives at
        # hexagon/adapters/native/sync_driver.py and the DB server already
        # runs on it, but switching the orchestrator's own instance is a
        # behaviour decision, and B3a makes none.
        sync_server_key = resolve_sync_server_key(self.world_cfg)
        self.use_sync = sync_server_key is not None
        if self.use_sync:
            self.syncer = HelaoSyncer(
                action_serv=self, sync_server_name=sync_server_key
            )

        # --- orch.py:121-125: the three queues --------------------------
        self.sequence_dq = zdeque([])
        self.experiment_dq = zdeque([])
        self.action_dq = zdeque([])
        self.dispatch_buffer = []
        self.nonblocking = []

        # --- orch.py:128-145: history and the active run ----------------
        self.last_dispatched_action_uuid = None
        self.action_history = DequeDict(maxlen=1000)
        self.experiment_history = DequeDict(maxlen=1000)
        self.sequence_history = DequeDict(maxlen=1000)
        self.last_action_uuid = ""
        self.last_interrupt = time.time()
        self.active_experiment: Optional[Experiment] = None
        self.last_experiment: Optional[Experiment] = None
        self.active_sequence: Optional[Sequence] = None
        self.active_seq_exp_counter = 0
        self.last_sequence: Optional[Sequence] = None
        self.active_run_id: Optional[UUID] = None
        self.heartbeat_interval = self.server_params.get("heartbeat_interval", 10)
        self.ignore_heartbeats = self.server_params.get("ignore_heartbeats", [])
        self.verify_plates = self.server_params.get("verify_plates", True)

        # --- orch.py:146-153: the global status model -------------------
        self.globalstatusmodel = GlobalStatusModel(orchestrator=self.server)
        self.globalstatusmodel._sort_status()
        self.interrupt_q = asyncio.Queue()
        self.incoming_status = asyncio.Queue()
        self.incoming = None

        self.init_success = False

        # --- orch.py:155-176: task handles and wait state ---------------
        self.loop_task = None
        self.status_subscriber = None
        self.globstat_broadcaster = None
        self.heartbeat_monitor = None
        self.driver_monitor = None
        self.wait_task = None
        self.current_wait_ts = 0
        self.last_wait_ts = 0
        self.globstat_q = MultisubscriberQueue()
        self.globstat_clients = set()
        self.current_stop_message = ""
        self.aiolock = asyncio.Lock()

        # --- orch.py:172-177: step-through flags ------------------------
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.status_summary = {}
        self.global_params = {}

        # --- orch.py:178-188: meta post-processors ----------------------
        # import_postprocessors is inherited from ActionHost, where B1 fixed
        # it to resolve BARE NAMES against a deployment's processors/ dir --
        # a path-only loader skips them with a warning, and the only visible
        # consequence is a missing output file.
        self.exp_postprocessors: list = []
        self.exp_postprocess_libs = self.server_cfg.get("exp_postprocess_libs", [])
        self.import_postprocessors(
            self.exp_postprocess_libs, self.exp_postprocessors, MetaProcessor
        )
        self.seq_postprocessors: list = []
        self.seq_postprocess_libs = self.server_cfg.get("seq_postprocess_libs", [])
        self.import_postprocessors(
            self.seq_postprocess_libs, self.seq_postprocessors, MetaProcessor
        )

        self._init_orch_collaborators()
        self._register_orch_routes()
        self._register_orch_payload_routes()
        self._register_orch_family_overrides()
        self._register_orch_action_routes()
        self._register_orch_loop_routes()

    # -- names the API layer and the collaborators reach through ---------

    @property
    def orch(self) -> "OrchHost":
        """``app.orch`` and ``app`` are the same object here."""
        return self

    def _init_orch_collaborators(self) -> None:
        """Construct the seven collaborators, in legacy's order (orch.py:206)."""
        from helao.hexagon.app.orch_dispatch import DispatchRunner
        from helao.hexagon.app.orch_estop import EstopController
        from helao.hexagon.app.orch_lifecycle import RunLifecycle
        from helao.hexagon.app.orch_monitor import ServerMonitor
        from helao.hexagon.app.orch_persist import QueuePersister
        from helao.hexagon.app.orch_queues import RunQueues
        from helao.hexagon.app.orch_status_sync import StatusIngester

        self.queue_persister = QueuePersister(self)
        self.server_monitor = ServerMonitor(self)
        self.status_ingester = StatusIngester(self)
        self.run_queues = RunQueues(self)
        self.run_lifecycle = RunLifecycle(self)
        self.dispatch_runner = DispatchRunner(self)
        self.estop_controller = EstopController(self)

    # -- sequence unpacking (orch.py delegations to orch_unpack) ---------

    def unpack_sequence(self, sequence_name: str, sequence_params) -> list[Experiment]:
        """Expand a sequence into its experiment list via the sequence library."""
        return orch_unpack.unpack_sequence(
            sequence_name, sequence_params, self.sequence_lib
        )

    async def seq_unpacker(self) -> None:
        """Unpack the active sequence into the experiment queue."""
        return await orch_unpack.seq_unpacker(self)

    def verify_plate_in_params(self, paramd: dict) -> bool:
        """Return whether the params name a plate this station may run."""
        return orch_unpack.verify_plate_in_params(paramd)

    # -- queue surface (delegations to RunQueues) ------------------------
    #
    # Every index here is ABSOLUTE. A rendered row index is page-local, so
    # a caller paging the queue must add its own offset before calling --
    # dropping it deletes the wrong queued item with nothing on screen
    # looking wrong.

    def _prep_sequence_meta(self, sequence: Sequence) -> None:
        """Populate a sequence's metadata before it joins the queue."""
        return self.run_queues._prep_sequence_meta(sequence)

    def _ensure_run_id(self) -> UUID:
        """Return the active run_id, minting one if there is none."""
        return self.run_queues._ensure_run_id()

    def _resolve_active_run_id(self, sequence: Sequence) -> None:
        """Attach the active run_id to ``sequence``."""
        return self.run_queues._resolve_active_run_id(sequence)

    async def add_sequence(self, sequence: Sequence) -> UUID:
        """Append a sequence to the queue. Returns its UUID."""
        return await self.run_queues.add_sequence(sequence)

    async def add_split_sequences(self, sequence: Sequence) -> None:
        """Append a sequence split into per-plate children."""
        return await self.run_queues.add_split_sequences(sequence)

    async def prepend_sequences(self, sequences: list[Sequence]) -> list[UUID]:
        """Put sequences at the FRONT of the queue. Returns their UUIDs."""
        return await self.run_queues.prepend_sequences(sequences)

    def _rebuild_sequence_dq(self, seqs) -> None:
        """Replace the sequence deque's contents with ``seqs``."""
        return self.run_queues._rebuild_sequence_dq(seqs)

    async def move_sequence(self, from_idx: int, to_idx: int) -> None:
        """Move a queued sequence. Out of range is a no-op, not an error."""
        return await self.run_queues.move_sequence(from_idx, to_idx)

    async def remove_sequence(self, idx: int) -> None:
        """Remove a queued sequence. Out of range is a no-op."""
        return await self.run_queues.remove_sequence(idx)

    def _rebuild_experiment_dq(self, exps) -> None:
        """Replace the experiment deque's contents with ``exps``."""
        return self.run_queues._rebuild_experiment_dq(exps)

    async def move_experiment(self, from_idx: int, to_idx: int) -> None:
        """Move a queued experiment. Out of range is a no-op."""
        return await self.run_queues.move_experiment(from_idx, to_idx)

    async def remove_experiment(
        self, idx: Optional[int] = None, by_uuid: Optional[UUID] = None
    ) -> None:
        """Remove a queued experiment by index or by uuid."""
        return await self.run_queues.remove_experiment(idx=idx, by_uuid=by_uuid)

    def _rebuild_action_dq(self, acts) -> None:
        """Replace the action deque's contents with ``acts``."""
        return self.run_queues._rebuild_action_dq(acts)

    async def move_action(self, from_idx: int, to_idx: int) -> None:
        """Move a queued action. Out of range is a no-op."""
        return await self.run_queues.move_action(from_idx, to_idx)

    async def remove_action(self, idx: int) -> None:
        """Remove a queued action. Out of range is a no-op."""
        return await self.run_queues.remove_action(idx)

    async def add_experiment(
        self,
        seq: Sequence,
        experimentmodel: Union[Experiment, ExperimentModel, ShortExperimentModel],
        prepend: bool = False,
        at_index: Optional[int] = None,
    ) -> UUID:
        """Queue an experiment under ``seq``. Returns its UUID."""
        return await self.run_queues.add_experiment(
            seq, experimentmodel, prepend=prepend, at_index=at_index
        )

    def list_sequences(self, limit: Optional[int] = None, offset: int = 0) -> list:
        """Return queued sequences. ``limit=None`` means the WHOLE queue."""
        return self.run_queues.list_sequences(limit=limit, offset=offset)

    def list_experiments(self, limit: Optional[int] = None, offset: int = 0) -> list:
        """Return queued experiments. ``limit=None`` means the whole queue."""
        return self.run_queues.list_experiments(limit=limit, offset=offset)

    def list_all_experiments(self) -> list:
        """Return every queued experiment, unpaged."""
        return self.run_queues.list_all_experiments()

    def drop_experiment_inds(self, inds: list[int]) -> list:
        """Drop queued experiments at the given ABSOLUTE indices."""
        return self.run_queues.drop_experiment_inds(inds)

    def get_experiment(self, last=False) -> Experiment:
        """Return the active experiment, or the last finished one."""
        return self.run_queues.get_experiment(last=last)

    def get_sequence(self, last=False) -> Sequence:
        """Return the active sequence, or the last finished one."""
        return self.run_queues.get_sequence(last=last)

    def list_active_actions(self) -> list:
        """Return the actions currently running across all servers."""
        return self.run_queues.list_active_actions()

    def list_actions(self, limit: Optional[int] = None, offset: int = 0) -> list:
        """Return queued actions. ``limit=None`` means the whole queue."""
        return self.run_queues.list_actions(limit=limit, offset=offset)

    async def clear_sequences(self) -> None:
        """Empty the sequence queue."""
        return await self.run_queues.clear_sequences()

    async def clear_experiments(self) -> None:
        """Empty the experiment queue."""
        return await self.run_queues.clear_experiments()

    # -- run lifecycle (delegations to RunLifecycle) ---------------------

    async def finish_active_sequence(self) -> None:
        """Finalize the active sequence and write its meta file."""
        return await self.run_lifecycle.finish_active_sequence()

    async def finish_active_experiment(self) -> None:
        """Finalize the active experiment and write its meta file."""
        return await self.run_lifecycle.finish_active_experiment()

    async def write_active_experiment_exp(self) -> None:
        """Write the active experiment's meta file."""
        return await self.run_lifecycle.write_active_experiment_exp()

    async def write_active_sequence_seq(self) -> None:
        """Write the active sequence's meta file."""
        return await self.run_lifecycle.write_active_sequence_seq()

    async def dispatch_wait_task(
        self, active: "Active", print_every_secs: int = 5
    ) -> None:
        """Run the orchestrator's own ``wait`` action to completion."""
        return await self.run_lifecycle.dispatch_wait_task(
            active, print_every_secs=print_every_secs
        )

    # -- queue persistence (delegations to QueuePersister) ---------------

    def export_queues(self, timestamp_pck: bool = False) -> str:
        """Pickle all three queues to STATES. Returns the path written."""
        return self.queue_persister.export_queues(timestamp_pck=timestamp_pck)

    def import_queues(self, pck_path: Optional[str] = None) -> str:
        """Restore all three queues from a pickle. Returns the path read."""
        return self.queue_persister.import_queues(pck_path)

    # -- route registration ---------------------------------------------

    def _register_orch_routes(self) -> None:
        """Register the orchestrator's own private routes.

        Eight of ``orch_api``'s private routes -- /get_status,
        /attach_client, /detach_client, /stop_executor, /endpoints,
        /get_lbuf, /list_executors, /shutdown -- are ALREADY registered by
        ActionHost with the same bodies, so they are not repeated here.
        FastAPI accepts a duplicate path without complaint and the first
        registration wins, so a second copy would sit shadowed and never
        execute while every surface check still passed.
        """
        from typing import Optional as _Optional

        from fastapi import Body

        @self.post("/global_status", tags=["private"])
        def global_status():
            """Return the orchestrator's global status model as JSON."""
            return self.globalstatusmodel.as_json()

        @self.post("/export_queues", tags=["private"])
        def export_queues(timestamp_pck: bool = False):
            """Pickle all three queues to STATES."""
            return self.export_queues(timestamp_pck)

        @self.post("/import_queues", tags=["private"])
        def import_queues(pck_path: _Optional[str] = None):
            """Restore all three queues from a pickle."""
            return self.import_queues(pck_path)

        @self.post("/append_sequence", tags=["private"])
        async def append_sequence(sequence: Sequence = Body({}, embed=True)):
            """Queue a sequence."""
            return await self.add_sequence(sequence)

        @self.post("/append_split_sequences", tags=["private"])
        async def append_split_sequences(sequence: Sequence = Body({}, embed=True)):
            """Queue a sequence split into per-plate children."""
            return await self.add_split_sequences(sequence)

        @self.post("/prepend_sequences", tags=["private"])
        async def prepend_sequences(
            sequences: list[Sequence] = Body([], embed=True),
        ):
            """Put sequences at the front of the queue."""
            return await self.prepend_sequences(sequences)

        @self.post("/move_sequence", tags=["private"])
        async def move_sequence(from_idx: int, to_idx: int):
            """Move a queued sequence. Indices are ABSOLUTE."""
            return await self.move_sequence(from_idx, to_idx)

        @self.post("/remove_sequence", tags=["private"])
        async def remove_sequence(idx: int):
            """Remove a queued sequence. Index is ABSOLUTE."""
            return await self.remove_sequence(idx)

        @self.post("/move_experiment", tags=["private"])
        async def move_experiment(from_idx: int, to_idx: int):
            """Move a queued experiment. Indices are ABSOLUTE."""
            return await self.move_experiment(from_idx, to_idx)

        @self.post("/remove_experiment", tags=["private"])
        async def remove_experiment(idx: int):
            """Remove a queued experiment. Index is ABSOLUTE."""
            return await self.remove_experiment(idx)

        @self.post("/move_action", tags=["private"])
        async def move_action(from_idx: int, to_idx: int):
            """Move a queued action. Indices are ABSOLUTE."""
            return await self.move_action(from_idx, to_idx)

        @self.post("/remove_action", tags=["private"])
        async def remove_action(idx: int):
            """Remove a queued action. Index is ABSOLUTE."""
            return await self.remove_action(idx)

        @self.post("/append_experiment", tags=["private"])
        async def append_experiment(experiment: Experiment = Body({}, embed=True)):
            """Queue an experiment under the active sequence."""
            return await self.add_experiment(self.seq_model, experiment.get_exp())

        @self.post("/prepend_experiment", tags=["private"])
        async def prepend_experiment(experiment: Experiment = Body({}, embed=True)):
            """Put an experiment at the front of the queue."""
            return await self.add_experiment(
                self.seq_model, experiment.get_exp(), prepend=True
            )

        @self.post("/insert_experiment", tags=["private"])
        async def insert_experiment(
            experiment: Experiment = Body({}, embed=True), idx: int = 0
        ):
            """Insert an experiment at an ABSOLUTE queue index."""
            return await self.add_experiment(
                self.seq_model, experiment.get_exp(), at_index=idx
            )

        @self.post("/list_sequences", tags=["private"])
        def list_sequences(limit: _Optional[int] = None, offset: int = 0):
            """Page the sequence queue. ``limit=None`` means all of it."""
            return self.list_sequences(limit=limit, offset=offset)

        @self.post("/list_experiments", tags=["private"])
        def list_experiments(limit: _Optional[int] = None, offset: int = 0):
            """Page the experiment queue. ``limit=None`` means all of it."""
            return self.list_experiments(limit=limit, offset=offset)

        @self.post("/list_all_experiments", tags=["private"])
        def list_all_experiments():
            """Return every queued experiment, unpaged."""
            return self.list_all_experiments()

        @self.post("/list_actions", tags=["private"])
        def list_actions(limit: _Optional[int] = None, offset: int = 0):
            """Page the action queue. ``limit=None`` means all of it."""
            return self.list_actions(limit=limit, offset=offset)

        @self.post("/drop_experiment_inds", tags=["private"])
        def drop_experiment_inds(inds: list[int]):
            """Drop queued experiments at ABSOLUTE indices."""
            return self.drop_experiment_inds(inds)

        @self.post("/clear_sequences", tags=["private"])
        async def clear_sequences():
            """Empty the sequence queue."""
            return await self.clear_sequences()

        @self.post("/clear_experiments", tags=["private"])
        async def clear_experiments():
            """Empty the experiment queue."""
            return await self.clear_experiments()

    def _register_orch_payload_routes(self) -> None:
        """The read-only payload routes and the global-param surface.

        The three payload builders are imported from ``orch_api`` rather
        than reimplemented: they shape what the operator UIs parse, and a
        second implementation would drift from the one the Bokeh and Reflex
        operators are written against. B7 deletes the importer.
        """
        from typing import Optional as _Optional

        from helao.core.servers.orch_api import (
            _histories_payload,
            _history_page_payload,
            _queue_object_payload,
        )

        @self.post("/get_queue_object", tags=["private"])
        def get_queue_object(kind: str, idx: int):
            """Return one queued object. ``idx`` is ABSOLUTE."""
            return _queue_object_payload(self, kind, idx)

        @self.post("/get_histories", tags=["private"])
        def get_histories():
            """Return all three history containers whole.

            Kept beside the paged /get_history_page rather than replaced by
            it: helao/hexagon/tests/smoke/conc_items.py calls this one.
            """
            return _histories_payload(self)

        @self.post("/get_history_page", tags=["private"])
        def get_history_page(kind: str, limit: _Optional[int] = None, offset: int = 0):
            """Page one history container, newest first, with a total.

            History indices are page-local and must NOT have an offset
            added -- the opposite of the queues. The history cache holds
            only the rendered page, so adding an offset indexes past its end.
            """
            return _history_page_payload(self, kind, limit, offset)

        @self.post("/latest_action_uuids", tags=["private"])
        def latest_action_uuids():
            """Return the 50 most recent action uuids."""
            return list(self.action_history.keys())[-50:]

        @self.post("/drop_experiment_range", tags=["private"])
        def drop_experiment_range(lower: int, upper: int):
            """Drop queued experiments in an INCLUSIVE absolute range."""
            inds = list(range(lower, upper + 1))
            return self.drop_experiment_inds(inds)

        @self.post("/update_global_params", tags=["private"])
        async def update_global_params(params: dict = {}):
            """Merge ``params`` into the orchestrator's global params."""
            params = params or {}
            LOGGER.info(f"Updated global params with {params}.")
            self.global_params.update(params)

        @self.post("/get_global_params", tags=["private"])
        def get_global_params():
            """Return the orchestrator's global params."""
            return self.global_params

        @self.post("/clear_global_params_private", tags=["private"])
        def clear_global_params_private():
            """Empty the orchestrator's global params."""
            self.global_params = {}
            return self.global_params

    def _register_orch_action_routes(self) -> None:
        """The orchestrator's OWN action endpoints, on B1's context machinery.

        The orchestrator has always also been an action server -- which is
        why GM captures contain ``ORCH__wait`` directories. These ride
        ``@host.action()``, so they get the explicit ActionContext, the
        queuing middleware and the native session for free.

        ``/{server_key}/estop`` is NOT here: ActionHost already registers it
        with the same body (driver hook, latch, stop executors, finalize
        actives). Registering a second one would sit shadowed and never
        run, because FastAPI accepts the duplicate silently and the first
        wins -- and a route-surface check would still pass, since the path
        is present either way.

        Three of the nine are NOT completable in B3a and are registered as
        raising stubs alongside the loop routes: ``interrupt`` calls
        ``stop()``, and ``conditional_stop``/``conditional_skip`` call
        ``stop()``/``skip()``. All three are B3b members. The plan put all
        nine action routes in B3a; that was wrong, and this is the seam.
        """
        from helao.core.servers.orch_api import WaitExec, checkcond
        from helao.hexagon.app.action_context import ActionContext, action_version

        @self.action()
        async def wait(ctx: ActionContext, waittime: float = 10.0):
            """Sleep ``waittime`` seconds via a ``WaitExec`` executor."""
            active = await ctx.begin()
            active.action.action_abbr = "wait"
            executor = WaitExec(active=active, oneoff=False)
            return active.start_executor(executor)

        @self.action()
        async def cancel_wait(ctx: ActionContext):
            """Stop every running ``wait`` executor and finish the action."""
            active = await ctx.begin()
            for exec_id, executor in self.executors.items():
                if exec_id.split()[0] == "wait":
                    executor.stop_action_task()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        async def add_global_param(
            ctx: ActionContext,
            param_name: str = "global_param_test",
            param_value: Union[str, float, int, bool] = True,
        ):
            """Write ``param_name=param_value`` into ``global_params``."""
            active = await ctx.begin()
            pdict = {
                active.action.action_params["param_name"]: active.action.action_params[
                    "param_value"
                ]
            }
            active.action.action_params.update(pdict)
            self.global_params.update(pdict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        async def clear_global_params(ctx: ActionContext):
            """Empty ``global_params`` as an action, so the run records it."""
            active = await ctx.begin()
            self.global_params = {}
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        async def interrupt(ctx: ActionContext, reason: str = "wait"):
            """Stop the orchestrator with ``reason`` and finish."""
            active = await ctx.begin()
            self.current_stop_message = active.action.action_params["reason"]
            LOGGER.warning(active.action.action_params["reason"])
            await self.stop()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        async def conditional_exp(
            ctx: ActionContext,
            check_parameter: Optional[str] = "",
            check_condition: checkcond = checkcond.equals,
            check_value: Union[float, int, bool] = True,
            conditional_experiment_name: str = "",
            conditional_experiment_params: dict = {},
        ):
            """Prepend an experiment when the condition holds."""
            active = await ctx.begin()
            experiment_model = Experiment(
                experiment_name=active.action.action_params[
                    "conditional_experiment_name"
                ],
                experiment_params=active.action.action_params[
                    "conditional_experiment_params"
                ],
            )
            cond = active.action.action_params["check_condition"]
            check_key = active.action.action_params.get("check_parameter") or ""
            param = None
            if check_key:
                param = self.global_params.get(check_key)
                if param is None:
                    param = active.action.action_params.get(check_key)
            thresh = active.action.action_params["check_value"]
            check = False
            if cond == checkcond.uncond:
                check = True
            elif cond is None:
                check = False
            elif param is None:
                LOGGER.warning(
                    "conditional_exp: parameter %r is missing (not in "
                    "global_params or action_params); condition cannot be "
                    "evaluated -> treating as False.",
                    check_key,
                )
                check = False
            elif cond == checkcond.equals:
                check = param == thresh
            elif cond == checkcond.above:
                check = param > thresh
            elif cond == checkcond.below:
                check = param < thresh
            elif cond == checkcond.isnot:
                check = param != thresh
            if check:
                await self.add_experiment(
                    seq=self.seq_model,
                    experimentmodel=experiment_model,
                    prepend=True,
                )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        @action_version(2)
        async def conditional_stop(
            ctx: ActionContext,
            stop_parameter: Optional[str] = "",
            stop_condition: checkcond = checkcond.equals,
            stop_value: Union[str, float, int, bool] = True,
            reason: str = "conditional stop",
            clear_queues: bool = False,
        ):
            """Stop the orchestrator, optionally clearing every queue."""
            active = await ctx.begin()
            cond = active.action.action_params["stop_condition"]
            param = active.action.action_params.get(
                active.action.action_params["stop_parameter"], None
            )
            thresh = active.action.action_params["stop_value"]
            stop = False
            if cond == checkcond.equals:
                stop = param == thresh
            elif cond == checkcond.above:
                stop = param > thresh
            elif cond == checkcond.below:
                stop = param < thresh
            elif cond == checkcond.isnot:
                stop = param != thresh
            elif cond == checkcond.uncond:
                stop = True
            elif cond is None:
                stop = False
            if stop:
                if active.action.action_params["clear_queues"]:
                    await self.clear_actions()
                    await self.clear_experiments()
                    await self.clear_sequences()
                await self.stop()
                self.current_stop_message = active.action.action_params["reason"]
                LOGGER.warning(active.action.action_params["reason"])
                LOGGER.alert(f"ORCH STOPPED ~ {active.action.action_params['reason']}")
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.action()
        async def conditional_skip(
            ctx: ActionContext,
            skip_parameter: Optional[str] = "",
            skip_condition: checkcond = checkcond.equals,
            skip_value: Union[str, float, int, bool] = True,
            skip_queued_actions: bool = True,
            skip_queued_experiments: bool = False,
            reason: str = "conditional skip",
        ):
            """Clear queued actions and/or experiments when the condition holds."""
            active = await ctx.begin()
            cond = active.action.action_params["skip_condition"]
            param = active.action.action_params.get(
                active.action.action_params["skip_parameter"], None
            )
            thresh = active.action.action_params["skip_value"]
            skip = False
            if cond == checkcond.equals:
                skip = param == thresh
            elif cond == checkcond.above:
                skip = param > thresh
            elif cond == checkcond.below:
                skip = param < thresh
            elif cond == checkcond.isnot:
                skip = param != thresh
            elif cond == checkcond.uncond:
                skip = True
            elif cond is None:
                skip = False
            if skip:
                if active.action.action_params["skip_queued_actions"]:
                    await self.clear_actions()
                if active.action.action_params["skip_queued_experiments"]:
                    await self.clear_experiments()
            finished_action = await active.finish()
            return finished_action.as_dict()

    def _replace_inherited_route(self, path: str) -> None:
        """Drop a route ActionHost registered, so this host can re-register it.

        FastAPI matches in registration order and ActionHost's routes are
        registered first (in ``super().__init__``), so simply adding a
        second copy leaves the inherited one serving every request while
        the override sits shadowed -- and every path-level surface check
        still passes.

        Needed because the two API families are NOT the same contract, the
        way the two WS encoding families are not. ``/stop_executor`` is the
        measured case: ``BaseAPI`` declares ``executor_id: str`` (required),
        ``OrchAPI`` declares ``executor_id: str = ""`` and returns an error
        dict when it is blank. Inheriting the action family's version makes
        the orchestrator 422 a request legacy answered.
        """
        self.router.routes = [
            r for r in self.router.routes if getattr(r, "path", None) != path
        ]

    def _register_orch_family_overrides(self) -> None:
        """Routes whose ORCH-family contract differs from the action family."""
        self._replace_inherited_route("/stop_executor")

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str = ""):
            """Stop one executor, or report that none was named.

            ``executor_id`` is OPTIONAL here and required on an action
            server -- the orchestrator answers a blank one with an error
            dict rather than a 422.
            """
            if executor_id == "":
                return {"error": "executor_id was not specified"}
            return self.stop_executor(executor_id)

    # -- uuid registration (delegations to RunQueues) --------------------

    def register_obj_uuid(self, obj_uuid_key, obj_uuid_dict, obj_type: str) -> None:
        """Record a sequence/experiment uuid in its history map."""
        return self.run_queues.register_obj_uuid(obj_uuid_key, obj_uuid_dict, obj_type)

    def register_action_uuid(self, action_uuid, action_dict) -> None:
        """Record an action uuid in the action history map."""
        return self.run_queues.register_action_uuid(action_uuid, action_dict)

    def track_action_uuid(self, action_uuid) -> None:
        """Mark ``action_uuid`` as the most recently dispatched action."""
        return self.run_queues.track_action_uuid(action_uuid)

    # -- status ingestion (delegations to StatusIngester) ----------------

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ) -> bool:
        """Fold one action server's status into the global model."""
        return await self.status_ingester.update_status(actionservermodel)

    async def update_nonblocking(
        self, actionmodel: Action, server_host: str, server_port: int
    ) -> dict:
        """Record a non-blocking action's status transition."""
        return await self.status_ingester.update_nonblocking(
            actionmodel, server_host, server_port
        )

    async def clear_nonblocking(self) -> list:
        """Stop tracking every non-blocking action."""
        return await self.status_ingester.clear_nonblocking()

    # -- the dispatch loop (delegations to DispatchRunner) ---------------

    async def loop_task_dispatch_sequence(self) -> ErrorCodes:
        """Dequeue and unpack the next sequence."""
        return await self.dispatch_runner.dispatch_sequence()

    async def loop_task_dispatch_experiment(self) -> ErrorCodes:
        """Dequeue the next experiment and expand it into actions."""
        return await self.dispatch_runner.dispatch_experiment()

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        """Dispatch the action at the head of the queue."""
        return await self.dispatch_runner._launch_action()

    async def dispatch_loop_task(self) -> None:
        """The loop itself."""
        return await self.dispatch_runner.dispatch_loop_task()

    # -- loop control ----------------------------------------------------
    #
    # These carry real logic rather than delegating, and are ported
    # statement for statement from orch.py. The state checks are the whole
    # substance: `start` on an already-started loop must log and do
    # nothing, and `skip` on an IDLE orchestrator clears the action queue
    # rather than posting an intent nothing will read.

    async def wait_for_interrupt(self, pending_action=None) -> bool:
        """Block until an interrupt arrives; re-queue ``pending_action`` on stop.

        Returns False when the pending action was pushed back and the
        caller must bail out, True otherwise.
        """
        interrupt = await self.interrupt_q.get()
        if isinstance(interrupt, GlobalStatusModel):
            self.incoming = interrupt
        self.last_interrupt = time.time()
        while not self.interrupt_q.empty():
            interrupt = await self.interrupt_q.get()
            if isinstance(interrupt, GlobalStatusModel):
                self.incoming = interrupt
                await self.globstat_q.put(interrupt.as_json())
        if (
            pending_action is not None
            and self.globalstatusmodel.loop_intent == LoopIntent.stop
        ):
            pending_action.action_server.machine_name = self.server.machine_name
            self.action_dq.insert(0, pending_action)
            return False
        return True

    async def orch_wait_for_all_actions(self) -> None:
        """Block until no action anywhere is still active."""
        while not self.globalstatusmodel.actions_idle():
            if time.time() - self.last_interrupt > 10.0:
                LOGGER.info("some actions are still active, waiting for status update")
            await self.wait_for_interrupt()

    async def start(self) -> None:
        """Start or resume the loop when there is something queued."""
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            if (
                self.action_dq
                or self.experiment_dq
                or self.sequence_dq
                or (self.active_sequence is not None)
            ):
                await self.start_loop()
            else:
                LOGGER.info("experiment list is empty")
        else:
            LOGGER.info("already running")
        self.current_stop_message = ""

    async def start_loop(self) -> LoopStatus:
        """Create the loop task, refusing to start while E-STOP is latched."""
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            LOGGER.info("starting orch loop")
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.error("E-STOP flag was raised, clear E-STOP before starting.")
        else:
            LOGGER.info("loop already started.")
        return self.globalstatusmodel.loop_state

    async def stop(self, reset_run_id: bool = False) -> None:
        """Request a graceful stop, respecting the current loop state."""
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_stop()
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.info("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            LOGGER.info("orchestrator is not running")
        if reset_run_id:
            LOGGER.info("resetting active_run_id on stop")
            self.active_run_id = None

    async def stop_loop(self) -> None:
        """Alias legacy keeps for callers that spell it this way."""
        await self.intend_stop()

    async def skip(self) -> None:
        """Skip while running; clear the action queue when idle."""
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_skip()
        else:
            LOGGER.info("orchestrator not running, clearing action queue")
            self.action_dq.clear()

    async def intend_skip(self) -> None:
        """Post a skip intent to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_stop(self) -> None:
        """Post a stop intent to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self) -> None:
        """Clear any pending loop intent."""
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    # -- E-STOP (delegations to EstopController) -------------------------

    async def estop_loop(self, reason: str = "") -> None:
        """Latch E-STOP and stop the loop."""
        return await self.estop_controller.estop_loop(reason=reason)

    async def estop_actions(self, switch: bool) -> None:
        """Fan E-STOP out to every action server."""
        return await self.estop_controller.estop_actions(switch)

    async def estop_finish_active(self) -> None:
        """Finalize the in-flight experiment and sequence as estopped."""
        return await self.estop_controller.estop_finish_active()

    async def clear_estop(self) -> None:
        """Clear the E-STOP latch."""
        return await self.estop_controller.clear_estop()

    async def clear_error(self) -> None:
        """Clear the error state."""
        return await self.estop_controller.clear_error()

    async def clear_actions(self) -> None:
        """Empty the action queue."""
        return await self.run_queues.clear_actions()

    def _register_orch_loop_routes(self) -> None:
        """The loop-control, status-ingestion and read-state routes (B3b).

        Bodies ported from ``orch_api`` unchanged apart from the back
        reference. The state guards are the substance: /estop_orch on an
        already-estopped orchestrator logs rather than re-latching, and
        /clear_estop refuses unless the loop is actually estopped.
        """
        from fastapi import Body

        from helao.core.models.hlostatus import HloStatus
        from helao.core.servers.orch_api import (
            _queue_counts,
            _set_step_flag,
            _status_summary_payload,
            _step_flags_payload,
        )

        @self.post("/start", tags=["private"])
        async def start():
            """Start (or resume) the dispatch loop."""
            await self.start()
            return {}

        @self.post("/stop", tags=["private"])
        async def stop(reset_run_id: bool = False):
            """Request a graceful stop; optionally drop the active run_id."""
            await self.stop(reset_run_id=reset_run_id)
            return {}

        @self.post("/skip_experiment", tags=["private"])
        async def skip_experiment():
            """Skip the current experiment."""
            await self.skip()
            return {}

        @self.post("/clear_actions", tags=["private"])
        async def clear_actions():
            """Empty the action queue."""
            await self.clear_actions()
            return {}

        @self.post("/estop_orch", tags=["private"])
        async def estop_orch():
            """Latch E-STOP if the loop is running; otherwise log and return."""
            if self.globalstatusmodel.loop_state == LoopStatus.started:
                await self.estop_loop()
            elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
                LOGGER.info("orchestrator E-STOP flag already raised")
            else:
                LOGGER.info("orchestrator is not running")
            return {}

        @self.post("/clear_estop", tags=["private"])
        async def clear_estop():
            """Clear the E-STOP latch, only from the estopped state."""
            if self.globalstatusmodel.loop_state != LoopStatus.estopped:
                LOGGER.info("orchestrator is not currently in E-STOP")
            else:
                await self.clear_estop()

        @self.post("/clear_error", tags=["private"])
        async def clear_error():
            """Clear the error state, only from the error state."""
            if self.globalstatusmodel.loop_state != LoopStatus.error:
                LOGGER.info("orchestrator is not currently in ERROR")
            else:
                await self.clear_error()

        @self.post("/update_status", tags=["private"])
        async def update_status(
            actionservermodel: ActionServerModel = Body({}, embed=True),
            regular_task: str = "false",
        ):
            """Fold a remote action server's status into the global model."""
            if actionservermodel is None:
                return False
            if regular_task == "false":
                LOGGER.debug(
                    f"orch '{self.server.server_name}' got status from "
                    f"'{actionservermodel.action_server.server_name}': "
                    f"{actionservermodel.endpoints}"
                )
            return await self.update_status(actionservermodel=actionservermodel)

        @self.post("/update_nonblocking", tags=["private"])
        async def update_nonblocking(
            actionmodel: Action = Body({}, embed=True),
            server_host: str = "",
            server_port: int = 9000,
        ):
            """Record a non-blocking action transition."""
            LOGGER.info(
                f"'{self.server.server_name.upper()}' got nonblocking status from "
                f"'{actionmodel.action_server.server_name}': exec_id: "
                f"{actionmodel.exec_id} -- status: {actionmodel.action_status} on "
                f"{server_host}:{server_port}"
            )
            return await self.update_nonblocking(actionmodel, server_host, server_port)

        @self.post("/clear_actives", tags=["private"])
        async def clear_actives():
            """Move every active action to ``skipped`` and return their uuids."""
            cleared_actives = []
            for actionservermodel in self.globalstatusmodel.server_dict.values():
                for endpointkey, endpointmodel in actionservermodel.endpoints.items():
                    active_items = list(endpointmodel.active_dict.items())
                    for uuid, statusmodel in active_items:
                        endpointmodel.active_dict.pop(uuid)
                        cleared_actives.append(uuid)
                        self.globalstatusmodel.active_dict.pop(uuid)
                        if HloStatus.skipped not in endpointmodel.nonactive_dict:
                            endpointmodel.nonactive_dict[HloStatus.skipped] = {}
                        endpointmodel.nonactive_dict[HloStatus.skipped].update(
                            {uuid: statusmodel}
                        )
                    actionservermodel.endpoints[endpointkey] = endpointmodel
                await self.update_status(actionservermodel=actionservermodel)
            return cleared_actives

        @self.post("/get_active_experiment", tags=["private"])
        def get_active_experiment():
            """The active experiment as a cleaned dict, or {}."""
            if self.active_experiment is None:
                return {}
            return self.active_experiment.clean_dict()

        @self.post("/get_active_sequence", tags=["private"])
        def get_active_sequence():
            """The active sequence as a cleaned dict, or {}."""
            if self.active_sequence is None:
                return {}
            return self.active_sequence.clean_dict()

        @self.post("/active_experiment", tags=["private"])
        def active_experiment():
            """The active experiment object."""
            return self.get_experiment(last=False)

        @self.post("/last_experiment", tags=["private"])
        def last_experiment():
            """The most recently finished experiment."""
            return self.get_experiment(last=True)

        @self.post("/list_active_actions", tags=["private"])
        def list_active_actions():
            """The actions currently running across all servers."""
            return self.list_active_actions()

        @self.post("/list_nonblocking", tags=["private"])
        def list_non_blocking():
            """Tracked non-blocking executor identifiers."""
            return self.nonblocking

        @self.post("/get_orch_state", tags=["private"])
        def get_orch_state() -> dict:
            """Loop state plus the active/last sequence and experiment.

            The queue DEPTHS come from _queue_counts, not from len() of a
            rendered page -- a paged list reports its page size, which read
            as the queue's depth in the operator until it was fixed.
            """
            resp = {
                "orch_state": self.globalstatusmodel.orch_state,
                "loop_state": self.globalstatusmodel.loop_state,
                "loop_intent": self.globalstatusmodel.loop_intent,
            }
            active_seq = self.get_sequence()
            last_seq = self.get_sequence(last=True)
            active_exp = self.get_experiment()
            last_exp = self.get_experiment(last=True)
            resp["active_sequence"] = active_seq.clean_dict() if active_seq else {}
            resp["last_sequence"] = last_seq.clean_dict() if last_seq else {}
            resp["active_experiment"] = active_exp.clean_dict() if active_exp else {}
            resp["last_experiment"] = last_exp.clean_dict() if last_exp else {}
            resp.update(_queue_counts(self))
            resp["current_stop_message"] = self.current_stop_message
            return resp

        @self.post("/get_status_summary", tags=["private"])
        def get_status_summary():
            """The per-server (server_status, driver_status) summary."""
            return _status_summary_payload(self)

        @self.post("/get_step_flags", tags=["private"])
        def get_step_flags():
            """The step-through flags."""
            return _step_flags_payload(self)

        @self.post("/set_step_flag", tags=["private"])
        def set_step_flag(kind: str, value: bool):
            """Set one step-through flag and return its new value."""
            return _set_step_flag(self, kind, value)

        @self.post("/latest_sequence_uuids", tags=["private"])
        def latest_sequence_uuids():
            """The 50 most recent dispatched sequence uuids."""
            return list(self.sequence_history.keys())[-50:]

        @self.post("/latest_experiment_uuids", tags=["private"])
        def latest_experiment_uuids():
            """The 50 most recent dispatched experiment uuids."""
            return list(self.experiment_history.keys())[-50:]
