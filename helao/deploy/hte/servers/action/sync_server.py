# shell: uvicorn motion_server:app --reload
"""Data packaging server.

Wraps :class:`HelaoSyncer` and exposes private endpoints used by other servers
(and operators) to enqueue finished YAML records for upload to S3 / the API,
inspect the syncer's pending queue and progress, and reset partially synced
runs.

A pending sweep also runs once at startup, because the syncer's work queue does
not survive the process that holds it. See :func:`sweep_pending`.
"""

__all__ = ["makeApp", "sweep_pending", "SWEEP_PARAM"]

import asyncio
import contextlib
import time
from typing import Any, Optional

from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.core.servers.base_api import BaseAPI
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Server ``params`` key that disarms the startup sweep (default: armed).
SWEEP_PARAM = "sync_pending_on_startup"


async def sweep_pending(driver: Any, enabled: bool = True, logger: Any = None) -> dict:
    """Enqueue everything still sitting in ``RUNS_FINISHED``, once, at startup.

    **Why this is needed at all.** :class:`HelaoSyncer` keeps its work queue in
    an in-memory ``asyncio.PriorityQueue``, and action servers get no
    ``--restore``, so the queue dies with the process — ``HelaoSyncer.shutdown``
    is a ``pass``, so even a *graceful* stop discards it. Anything queued but
    not yet uploaded is then simply forgotten: the ymls stay in
    ``RUNS_FINISHED`` and nothing ever looks at them again. The durable half of
    the mechanism has always worked (an unsynced yml stays in ``RUNS_FINISHED``,
    where :meth:`HelaoSyncer.list_pending` finds it) and
    :meth:`HelaoSyncer.finish_pending` has always been the recovery method —
    but nothing called it automatically, so recovery depended on someone
    noticing and POSTing ``/finish_pending`` by hand. On the production share
    that left 179 sequence ymls unswept.

    **Why re-enqueueing everything is safe and cheap.** :class:`Progress` writes
    a ``.prg`` sidecar per yml under ``RUNS_SYNCED`` recording which S3 objects
    and API rows already landed, and ``sync_yml`` gates on it — ``prog.s3_done``
    / ``prog.api_done`` short-circuit the upload and the API post, and
    ``list_unfinished_procs`` narrows process work to what is not already in
    ``process_s3`` / ``process_api``. A yml that fully synced is no longer in
    ``RUNS_FINISHED`` at all, so the sweep never picks it up; a partially synced
    one resumes from its ``.prg`` rather than re-uploading. So the worst case for
    a yml this sweep picks up needlessly is a cheap no-op pass, never a duplicate
    upload.

    **Known limitation: nothing resets a diverged sidecar.** A ``.prg`` whose
    bookkeeping has drifted out of agreement with itself is re-enqueued in
    exactly that state. The shape that bites is an experiment whose
    ``process_actions_done`` records an action as folded in while the
    ``process_metas`` entry it was supposed to produce is gone. The completion
    gate still requires a ``process_metas`` entry for that process index, and
    there are two ways the rebuild fails to supply one: the contributing action
    yml has left the trees ``HelaoYml.children`` scans, so
    ``reconcile_processes`` has nothing to replay (the common case — the action
    synced and moved on); or the action carries no ``action_uuid``, in which case
    ``update_process``'s order-keyed guard short-circuits on the surviving
    ``process_actions_done`` entry and declines to re-fold (legacy ymls only).
    Either way the yml can never finish and returns to ``RUNS_FINISHED`` for the
    next pass. This sweep does not make
    that worse and cannot repair it — it only surfaces it more often, because it
    retries such a yml at every start instead of only when someone POSTs
    ``/finish_pending`` by hand. Repairing it belongs to ``sync_driver.py`` and
    is tracked as a separate change (see also ``reconcile_processes``); note that
    ``finish_pending``'s ``reset_sync`` branch is *not* that repair — it keys on a
    ``*.progress`` sibling, a legacy sidecar name nothing in this build writes
    (``Progress`` writes ``.prg``), so it is dead for anything the current code
    produces.

    **Why this lives in the server and not the driver.**
    ``helao/hexagon/tests/test_native_sync_pins.py`` pins
    ``SyncDriver.__init__``, ``syncer``, ``enqueue_yml``, ``finish_pending``,
    ``shutdown`` and ``list_pending*`` to be *byte-identical* between
    ``helao/core/drivers/data/sync_driver.py`` and
    ``helao/hexagon/adapters/native/sync_driver.py``, plus a contiguous
    verbatim-region check. Adding a startup hook to the driver would mean
    mirroring both copies byte-for-byte, for a concern (server lifecycle) the
    server already owns. So the sweep composes the driver's existing method
    instead of changing it.

    Args:
        driver: The :class:`HelaoSyncer` instance, or ``None`` when the server
            has no driver (driver construction failed, or a composition that
            never built one). ``None`` is a skip, not an error.
        enabled: ``False`` when the server's ``params`` set
            ``sync_pending_on_startup: false``. The sweep then does nothing but
            say so; ``/finish_pending`` remains available for a manual pass.
        logger: Logger to report through; defaults to this module's ``LOGGER``.
            Injectable so tests can read back what was logged.

    Returns:
        A JSON-serialisable summary, because it is served over HTTP on
        ``/tasks``: ``{"enabled", "ran", "enqueued", "reason", "error",
        "finished_at"}``. ``enqueued`` is ``None`` unless the sweep actually
        ran, so "found nothing" (``0``) stays distinguishable from "did not
        run". It counts *sequences* — ``finish_pending`` returns only its
        pending-sequence list even though ``actions_first=True`` enqueues the
        pending actions and experiments ahead of them, so the real number of
        queued ymls is larger. Watch ``num_queued`` for that.

    Never raises. A failure here must not take the server down: the ymls are
    still in ``RUNS_FINISHED`` for the next start or for ``/finish_pending``.
    ``asyncio.CancelledError`` does propagate, so a shutdown mid-sweep is not
    mistaken for a failure — a cancelled sweep records no summary at all, even
    though the ymls it got to are queued.
    """
    log = logger if logger is not None else LOGGER
    summary: dict = {
        "enabled": enabled,
        "ran": False,
        "enqueued": None,
        "reason": None,
        "error": None,
        "finished_at": None,
    }
    if not enabled:
        summary["reason"] = f"suppressed by {SWEEP_PARAM}=false"
        log.info(
            f"startup sync sweep suppressed by {SWEEP_PARAM}=false; ymls in "
            "RUNS_FINISHED stay untouched until /finish_pending"
        )
    elif driver is None:
        summary["reason"] = "no syncer driver on this server"
        log.info("startup sync sweep skipped: no syncer driver on this server")
    else:
        try:
            # actions_first drains a partially synced run bottom-up: an exp
            # cannot sync before its actions, so queueing actions ahead of
            # sequences is what stops the sequences from bouncing off
            # incomplete children.
            pending = await driver.finish_pending(actions_first=True)
            summary["ran"] = True
            summary["enqueued"] = len(pending)
            log.info(
                f"startup sync sweep enqueued {len(pending)} pending "
                "sequence(s) from RUNS_FINISHED"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            summary["error"] = f"{type(exc).__name__}: {exc}"
            log.error("startup sync sweep failed", exc_info=True)
    summary["finished_at"] = time.time()
    return summary


def makeApp(server_key) -> BaseAPI:
    """Build the data-packaging FastAPI app.

    Constructs a :class:`BaseAPI` backed by :class:`HelaoSyncer` and registers
    the private syncer-management endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Data packaging server",
        version=0.1,
        driver_classes=[HelaoSyncer],
    )

    # ``None`` until the startup sweep finishes, which is what keeps "never ran"
    # distinguishable from "ran and found nothing" on /tasks.
    app.last_startup_sweep = None  # type: ignore[attr-defined]
    app.startup_sweep_task = None  # type: ignore[attr-defined]

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str) -> str:
        """Enqueue a finished YAML for upload and move to ``RUNS_SYNCED``.

        Determines the rank from the file suffix (``-seq.yml``, ``-exp.yml``,
        ``-act.yml``) and forwards to :meth:`HelaoSyncer.enqueue_yml`.
        """
        clean_path = yml_path.strip('"').strip("'")
        if clean_path.endswith("-seq.yml"):
            rank = 2
        elif clean_path.endswith("-exp.yml"):
            rank = 1
        elif clean_path.endswith("-act.yml"):
            rank = 0
        else:
            rank = -1
        await app.driver.enqueue_yml(clean_path, rank)
        return yml_path

    @app.post("/list_pending", tags=["private"])
    def list_pending():
        """List sequence YAML files in ``RUNS_FINISHED`` awaiting sync."""
        return app.driver.list_pending()

    @app.post("/finish_pending", tags=["private"])
    async def finish_pending(actions_first: bool = True):
        """Discover ``RUNS_FINISHED`` YAML files and enqueue them for sync.

        Args:
            actions_first: When ``True`` queue action YAMLs before experiment
                and sequence YAMLs.
        """
        return await app.driver.finish_pending(actions_first=actions_first)

    @app.post("/reset_sync", tags=["private"])
    def reset_sync(sync_path: str) -> str:
        """Reset a synced sequence zip or a partially-synced folder for re-sync."""
        app.driver.reset_sync(sync_path.strip('"').strip("'"))
        return sync_path

    @app.post("/tasks", tags=["private"])
    async def running() -> dict:
        """Return running sync tasks, the queued count, and the startup sweep.

        ``last_startup_sweep`` is the summary from :func:`sweep_pending`, or
        ``null`` while the sweep has not finished yet (so "never ran" stays
        distinguishable from "ran and found nothing", which reports
        ``enqueued: 0``). This is deliberately folded into an existing response
        rather than given a route of its own: ``/tasks`` is already what an
        operator polls, and the frozen endpoint checklist for this module
        (``helao/hexagon/tests/checklists/hte/sync_server.json``) pins the route
        set, so a new route would break that gate.
        """
        return {
            "running": list(app.driver.running_tasks.keys()),
            "num_queued": (app.driver.task_queue.qsize()),
            "last_startup_sweep": app.last_startup_sweep,  # type: ignore[attr-defined]
        }

    @app.post("/list_exceptions", tags=["private"])
    async def list_exceptions() -> dict:
        """Return exceptions captured on currently running sync tasks."""
        return {k: d.exception() for k, d in app.driver.running_tasks.items()}

    @app.post("/n_queue", tags=["private"])
    async def n_queue() -> int:
        """Return the number of items waiting in the sync task queue."""
        return app.driver.task_queue.qsize()

    @app.post("/current_progress", tags=["private"])
    async def current_progress():
        """Return the syncer's progress dictionary."""
        return app.driver.progress

    # Hot-reload safety: defer restart while the syncer has queued or running
    # tasks. Both ``app.base`` and ``app.driver`` are created in BaseAPI's own
    # startup event, so wire the hook from a startup handler (registered after
    # BaseAPI's, hence run after it). The hook still reads app.driver lazily.
    @app.on_event("startup")
    def _wire_hotreload_busy():
        app.base.hotreload_busy_hook = lambda: (
            app.driver is not None and app.driver.has_pending_work()
        )

    async def _startup_sweep(enabled: bool) -> None:
        """Run one sweep and record its summary for ``/tasks``."""
        app.last_startup_sweep = await sweep_pending(  # type: ignore[attr-defined]
            app.driver, enabled=enabled
        )

    # Startup recovery: enqueue whatever the last process left in
    # RUNS_FINISHED. Registered as a startup handler (so it runs after
    # BaseAPI's own, which is what creates ``app.base`` and ``app.driver`` —
    # same reasoning as ``_wire_hotreload_busy`` above), and dispatched as a
    # task rather than awaited: the sweep enqueues potentially hundreds of
    # ymls, and blocking startup on it would hold the server's health
    # endpoints down for that whole time.
    @app.on_event("startup")
    def _arm_startup_sweep():
        """Dispatch the pending sweep onto the server event loop."""
        enabled = bool(app.server_params.get(SWEEP_PARAM, True))
        app.startup_sweep_task = app.base.aloop.create_task(  # type: ignore[attr-defined]
            _startup_sweep(enabled)
        )

    @app.on_event("shutdown")
    async def _cancel_startup_sweep():
        """Cancel the sweep if it is still enqueueing when the server stops.

        Safe to cut short: whatever it queued is queued, and whatever it did
        not is still in ``RUNS_FINISHED`` for the next start to pick up.
        """
        task = app.startup_sweep_task  # type: ignore[attr-defined]
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            app.startup_sweep_task = None  # type: ignore[attr-defined]

    return app
