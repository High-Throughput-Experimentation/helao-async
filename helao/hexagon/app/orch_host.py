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
from typing import Optional
from uuid import UUID

from helao.core.models.server import GlobalStatusModel
from helao.helpers import helao_logging as logging
from helao.helpers.dequedict import DequeDict
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.processors import MetaProcessor
from helao.helpers.zdeque import zdeque
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
