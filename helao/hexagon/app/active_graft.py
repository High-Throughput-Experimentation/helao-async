"""Active write-path graft (P2b-1) — the analog of dispatch_loop's
graft_hexagon_loop: instance-level rebinding is the sanctioned wrap seam;
NO legacy source is modified.

What it reroutes: ``base.contain_action`` (reproduced 12-line legacy body,
drift-pinned by test_active_graft.PINNED_CONTAIN_ACTION) and
``base.meta_writer`` (one assignment; every Base meta delegator at
``base.py:666-716`` resolves ``self.meta_writer`` at call time). The
reproduced body swaps the three per-Active collaborators
(``data_stream``/``data_file_writer``/``action_finalizer``) for the wired
NativeArtifactStoreAdapter's collaborators BETWEEN ``Active.__init__`` and
``myinit()`` — mandatory window: ``myinit`` creates the ``data_logger``
task (``base.py:1014``) and then awaits (``update_act_file``, manual
metas) before returning, so the task body may resolve ``self.data_stream``
before ``contain_action`` returns; a post-return swap is a race. After the
swap, every call-time-resolving ``Active`` delegator
(``base.py:1149-1459``) routes 100% of write traffic through native code
while drivers/executors keep calling the unchanged ``Active`` surface and
legacy BaseAPI keeps hosting the routes (Q1).
"""

from copy import copy
from dataclasses import dataclass, field
from typing import Dict, cast

from helao.core.servers.base import Active
from helao.helpers import helao_logging as logging
from helao.helpers.active_params import ActiveParams
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.app.wiring import PortWiring

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActiveWriteGraft", "graft_active_write_path"]


@dataclass
class ActiveWriteGraft:
    base: object
    originals: Dict[str, object] = field(default_factory=dict)

    def close(self) -> None:
        """Symmetric unhook: restore the pre-graft bound method + meta writer."""
        self.base.contain_action = self.originals["contain_action"]  # type: ignore[attr-defined]
        self.base.meta_writer = self.originals["meta_writer"]  # type: ignore[attr-defined]


def graft_active_write_path(base, wiring: PortWiring) -> ActiveWriteGraft:
    """Rebind the legacy Base's write construction seam onto the native
    write runtime. Must run after the legacy app's own startup (``app.base``
    live) and before any action is contained."""
    store = wiring.artifact_store
    if store is None or not hasattr(store, "collaborators_for"):
        raise UnwiredPortError(
            "active write graft needs a wired NativeArtifactStoreAdapter "
            "(collaborators_for/meta_writer_for); got "
            f"{type(store).__name__ if store is not None else None}"
        )
    # The guard above proves `store` is a wired native adapter (it has the
    # collaborator-factory surface); narrow the abstract ArtifactStorePort to
    # the concrete type so the extension methods type-check without suppression.
    store = cast(NativeArtifactStoreAdapter, store)

    graft = ActiveWriteGraft(base=base)
    graft.originals["contain_action"] = base.contain_action
    graft.originals["meta_writer"] = base.meta_writer
    store.bind_base(base)
    base.meta_writer = store.meta_writer_for(base)

    async def hex_contain_action(activeparams: ActiveParams):
        # ------------------------------------------------------------------
        # Reproduction of Base.contain_action (base.py:438-456), statement
        # for statement — drift-pinned by test_active_graft.py. The ONLY
        # addition is the native collaborator swap, placed between
        # Active.__init__ and myinit() (see module docstring).
        # NB: the dict key is read AFTER Active() runs (init_act may assign
        # a fresh action_uuid in manual mode) — same evaluation order as the
        # legacy single-statement construct+register.
        # ------------------------------------------------------------------
        if activeparams.action.action_uuid in base.actives:
            await base.actives[activeparams.action.action_uuid].substitute()
        base.actives[activeparams.action.action_uuid] = Active(
            base, activeparams=activeparams
        )
        # --- hexagon swap (the reroute) ---
        active = base.actives[activeparams.action.action_uuid]
        streamer, file_writer, finalizer = store.collaborators_for(active)
        active.data_stream = streamer
        active.data_file_writer = file_writer
        active.action_finalizer = finalizer
        LOGGER.info(
            f"hexagon native collaborators swapped for action "
            f"{activeparams.action.action_uuid}"
        )
        # --- end swap ---
        await base.actives[activeparams.action.action_uuid].myinit()
        cact = copy(base.actives[activeparams.action.action_uuid].action)
        base.history[cact.action_uuid] = cact
        # register action_uuid in local action task queue
        return base.actives[activeparams.action.action_uuid]

    base.contain_action = hex_contain_action
    LOGGER.info(
        "hexagon native write path grafted (contain_action + meta_writer rebound)"
    )
    return graft
