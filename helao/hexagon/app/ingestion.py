"""Hexagon status ingestion (P2a): native replacement for the legacy
``StatusIngester`` short-circuit (helao/core/servers/orch_status_sync.py).

``HexStatusIngestion.update_status``/``update_nonblocking`` own the endpoint
bodies once ``graft_hexagon_loop`` rebinds them onto the live legacy ``Orch``
(instance rebind — the sanctioned wrap seam; NO legacy source edit). The
fold still lands in the legacy ``GlobalStatusModel`` via
``update_global_with_acts`` (replacing the status model is NOT P2a); the
inline estop/error/idle/busy REACTION (orch_status_sync.py:265-285) moves
into domain events — ``EstoppedUuidIngested`` / ``ErroredUuidIngested`` /
``StatusChanged`` — handled by the pure reducer, whose ``apply_state_delta``
is the sole ``orch_state`` writer (DD-2). The legacy elif chain is
replicated HERE with live ``loop_state`` so exactly ONE event fires per fold
(the reducer's own started-guards are a second net, not the selector).

Lock/queue ownership (two-owner invariant; the orch_status_sync.py:23-43 map
carries over): ``aiolock`` is acquired by ``update_status`` (ingestion) and
the dispatch critical section — nobody else; events are emitted INSIDE the
lock exactly where the legacy inline block ran, so the interleaving
guarantees (and the estop cascade running under the lock, as legacy
``estop_loop`` did) are unchanged. ``interrupt_q`` is written here (the
unconditional trailing ``globalstatusmodel`` put) and by the health monitor;
``globstat_q`` stays on the legacy broadcaster (``ws_globstat``/
``globstat_broadcast_task`` are NOT rebound). ``clear_nonblocking`` is NOT
rebound either — its wire behavior is untouched.

Wire quirks reproduced, not fixed (spec §7.4): ``update_nonblocking``'s
%-format f-string raises ``TypeError`` on a ``None`` ``action_timestamp``
(the status-adapter "third drift"), and ``list.remove`` raises ``ValueError``
on an unknown exec_id. Like the legacy ``StatusIngester``, this class caches
no shared mutable state — it holds only the ``orch``/``runtime`` refs and
resolves every attribute at call time (``import_queues`` reassignment of
``globalstatusmodel`` is always observed)."""

import asyncio

from helao.hexagon.app.orch_effects import _LazyServerLogger
from helao.hexagon.domain.models import HloStatus, LoopStatus
from helao.hexagon.domain.orchestration import (
    ErroredUuidIngested,
    EstoppedUuidIngested,
    HeartbeatFailed,
    StatusChanged,
)

LOGGER = _LazyServerLogger()

__all__ = ["HexStatusIngestion", "HexHealthMonitor", "action_history_meta"]


def action_history_meta(orch, act_model) -> dict:
    """The legacy register_action_uuid meta dict, byte-identical output
    (orch_status_sync.py duplicated this block in update_nonblocking and
    update_status; factored once here, also reused by the PruneDeadActions
    executor). Deliberately keeps the legacy %-format f-string: a ``None``
    ``action_timestamp`` raises TypeError, same as the legacy endpoint."""
    matching_experiment = (
        orch.active_experiment is not None
        and orch.active_experiment.experiment_uuid == act_model.experiment_uuid
    )
    return {
        "action_name": act_model.action_name,
        "action_params": act_model.action_params,
        "action_status": act_model.action_status,
        "action_server": act_model.action_server.server_name,
        "action_timestamp": f"{act_model.action_timestamp: %m-%d %H:%M:%S}",
        "action_finished_timestamp": (
            f"{act_model.action_finished_timestamp: %m-%d %H:%M:%S}"
            if act_model.action_finished_timestamp is not None
            else None
        ),
        "experiment_name": (
            orch.active_experiment.experiment_name
            if orch.active_experiment is not None and matching_experiment
            else None
        ),
        "experiment_uuid": act_model.experiment_uuid,
        "sequence_name": (
            orch.active_sequence.sequence_name
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
        "sequence_label": (
            orch.active_sequence.sequence_label
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
        "sequence_uuid": (
            orch.active_sequence.sequence_uuid
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
    }


class HexStatusIngestion:
    """Owns the rebound ``update_status``/``update_nonblocking`` bodies."""

    def __init__(self, orch, runtime):
        self.orch = orch
        self.runtime = runtime

    async def update_nonblocking(
        self, actionmodel, server_host: str, server_port: int
    ) -> dict:
        """Verbatim port of StatusIngester.update_nonblocking (no aiolock,
        same as legacy): register the uuid, append/remove the executor
        registry entry (ValueError quirk propagates), wake the loop."""
        orch = self.orch
        orch.register_action_uuid(
            actionmodel.action_uuid, action_history_meta(orch, actionmodel)
        )
        server_key = actionmodel.action_server.server_name
        server_exec_id = (server_key, actionmodel.exec_id, server_host, server_port)
        if "active" in actionmodel.action_status:
            orch.nonblocking.append(server_exec_id)
        else:
            orch.nonblocking.remove(server_exec_id)
        # put an empty object in interrupt_q to trigger orch dispatch loop
        await orch.interrupt_q.put(orch.globalstatusmodel)
        return {"success": True}

    async def update_status(self, actionservermodel=None) -> bool:
        """Fold + register (verbatim legacy), then emit exactly one domain
        event per the legacy elif chain instead of mutating orch_state."""
        orch = self.orch

        if actionservermodel is None:
            return False

        async with orch.aiolock:
            if actionservermodel.last_action_uuid is not None:
                # find last action uuid in action server model:
                for (
                    endpoint_name,
                    endpoint_model,
                ) in actionservermodel.endpoints.items():
                    for status, act_dict in endpoint_model.nonactive_dict.items():
                        for act_uuid, act_model in act_dict.items():
                            if act_uuid == actionservermodel.last_action_uuid:
                                orch.register_action_uuid(
                                    act_uuid, action_history_meta(orch, act_model)
                                )
                                break

            recent_nonactive = orch.globalstatusmodel.update_global_with_acts(
                actionservermodel=actionservermodel
            )
            for act_uuid, act_status in recent_nonactive:
                await orch.put_lbuf({act_uuid: {"status": act_status}})

            estop_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.estopped,
            )
            error_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.errored,
            )

            if estop_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started:
                # message shape matches the grafted hex_estop_loop's
                # "E-STOP <reason>" (legacy: estop_loop(reason=...))
                await self.runtime.handle(
                    EstoppedUuidIngested(
                        reason=f"E-STOP due to action uuid(s): {estop_uuids}"
                    )
                )
            elif (
                error_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started
            ):
                await self.runtime.handle(ErroredUuidIngested())
            else:
                any_active = bool(orch.globalstatusmodel.active_dict)
                if any_active:
                    LOGGER.info(f"running_states: {orch.globalstatusmodel.active_dict}")
                await self.runtime.handle(StatusChanged(any_active=any_active))

            # now push it to the interrupt_q (unconditional legacy tail wake)
            await orch.interrupt_q.put(orch.globalstatusmodel)

            return True


class HexHealthMonitor:
    """Replaces the legacy heartbeat task (ServerMonitor.active_action_
    monitor): same probe cadence (orch.heartbeat_interval), same active-url
    collection, same last-two-path-segment trim + ignore_heartbeats filter,
    same "<ends> endpoints are unavailable" stop-message wording. The
    REACTION differs by design (P2a sanctioned delta): instead of a direct
    orch.stop() + LOGGER.alert, it emits HeartbeatFailed (reducer T12: stop
    intent + SetStopMessage + AlertOperator) carrying the dead endpoints'
    active uuids so PruneDeadActions can clear them; then a StatusChanged
    fold (apply_state_delta writes orch_state=idle, DD-2) and an interrupt
    wake, in THAT order, so a parked orch_wait_for_all_actions wakes to an
    already-idle orch_state (no hot-spin in WaitAllActionsIdle). Never
    acquires aiolock (two-owner invariant): every mutation happens in the
    synchronous PruneDeadActions executor on this event loop."""

    def __init__(self, orch, runtime, health):
        self.orch = orch
        self.runtime = runtime
        self.health = health
        self._task = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(
            self.run_forever(), name="hexagon_health_monitor"
        )

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def run_forever(self) -> None:
        orch = self.orch
        while True:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.error("health monitor probe failed", exc_info=True)
            await asyncio.sleep(orch.heartbeat_interval)

    async def probe_once(self) -> None:
        orch = self.orch
        gsm = orch.globalstatusmodel
        if gsm.loop_state != LoopStatus.started:
            return
        active_items = list(gsm.active_dict.items())
        active_endpoints = [actmod.url for _uuid, actmod in active_items]
        if not active_endpoints:
            return
        unique_endpoints = list(set(active_endpoints))
        results = await self.health.endpoints_available(unique_endpoints)
        bad_urls = [url for url, ok in results if not ok]
        # legacy trim + ignore filter (orch_monitor.py:117-119)
        kept_bad_urls = [
            url
            for url in bad_urls
            if "/".join(url.strip("/").split("/")[-2:]) not in orch.ignore_heartbeats
        ]
        if not kept_bad_urls:
            return
        bad_ends = ["/".join(url.strip("/").split("/")[-2:]) for url in kept_bad_urls]
        dead_uuids = tuple(
            str(act_uuid)
            for act_uuid, actmod in active_items
            if actmod.url in kept_bad_urls
        )
        msg = f"{', '.join(bad_ends)} endpoints are unavailable"
        LOGGER.warning(msg)
        await self.runtime.handle(
            HeartbeatFailed(message=msg, dead_action_uuids=dead_uuids)
        )
        if dead_uuids:
            # post-prune fold BEFORE the wake: apply_state_delta (sole
            # orch_state writer, DD-2) must land idle before a parked
            # orch_wait_for_all_actions re-checks it
            await self.runtime.handle(StatusChanged(any_active=bool(gsm.active_dict)))
            await orch.interrupt_q.put(orch.globalstatusmodel)
