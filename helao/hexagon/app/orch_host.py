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
from helao.core.models.server import GlobalStatusModel
from helao.core.servers import orch_unpack
from helao.helpers import helao_logging as logging
from helao.helpers.dequedict import DequeDict
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Experiment, Sequence
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
        self._register_orch_loop_routes()

    # -- names the API layer and the collaborators reach through ---------

    @property
    def orch(self) -> "OrchHost":
        """``app.orch`` and ``app`` are the same object here."""
        return self

    def _init_orch_collaborators(self) -> None:
        """Construct the B3a collaborators. B3b adds dispatch/status/monitor."""
        from helao.hexagon.app.orch_estop import EstopController
        from helao.hexagon.app.orch_lifecycle import RunLifecycle
        from helao.hexagon.app.orch_persist import QueuePersister
        from helao.hexagon.app.orch_queues import RunQueues

        self.queue_persister = QueuePersister(self)
        self.run_queues = RunQueues(self)
        self.run_lifecycle = RunLifecycle(self)
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

    def _register_orch_loop_routes(self) -> None:
        """Register B3b's routes so the surface is complete and honest.

        They raise rather than 404. A 404 reads as a missing server and
        sends a caller looking at config and ports; a NotImplementedError
        naming B3b says what is actually true. Same choice B1 made for
        start_executor/oneoff_executor before its Task 6.
        """
        loop_routes = (
            "/start",
            "/stop",
            "/estop_orch",
            "/clear_estop",
            "/clear_error",
            "/skip_experiment",
            "/clear_actions",
            "/clear_actives",
            "/update_status",
            "/update_nonblocking",
            "/get_active_experiment",
            "/get_active_sequence",
            "/active_experiment",
            "/last_experiment",
            "/list_active_actions",
            "/list_nonblocking",
            "/get_orch_state",
            "/get_status_summary",
            "/get_step_flags",
            "/set_step_flag",
            "/latest_sequence_uuids",
            "/latest_experiment_uuids",
        )
        for path in loop_routes:
            self._register_loop_stub(path)

    def _register_loop_stub(self, path: str) -> None:
        """Register one raising stub.

        A separate method so each closure binds its OWN ``path``. Defining
        them in the loop body would close over the loop variable, and every
        stub would report the last path in the tuple.
        """

        @self.post(path, tags=["private"])
        async def _loop_stub():
            raise NotImplementedError(f"{path} is the dispatch loop; lands in B3b")

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
