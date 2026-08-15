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
