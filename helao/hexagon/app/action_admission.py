"""Action admission: one decision for the HTTP middleware and the RPC fast path.

An action POST is either run, parked behind a busy endpoint, or recognised as a
repeat of an action this server already took. Both transports ask here, so they
cannot disagree.

**Why repeats exist.** ``async_action_dispatcher`` probes over RPC with a short
timeout and, on timeout, re-sends the same action over HTTP. The RPC handler
does not stop when the client gives up, so without a uuid check the action runs
twice. The orchestrator's own uuid is therefore kept end to end (a parked copy
used to get a fresh one) and a second request carrying a uuid already seen is
answered with the existing record instead of being run or parked.

The record of seen uuids is bounded and per server. It is written at admission,
before the handler opens a session, because the window between the two is where
the RPC and HTTP copies race.

A repeat of an action that is still running waits for the original handler and
is answered with the original's result, not a stub: the orchestrator reads
``to_global_params``/``error_code`` from whichever reply it is holding. If the
original fails, the waiting repeat fails too (:class:`ActionFailed`).

**Failed actions re-run.** After a dispatch error the orchestrator pauses and,
on resume, re-sends the *same* action with the *same* uuid. A request whose uuid
was already taken but whose record is errored or estopped (or whose handler
raised) and has no handler pending is therefore run again, replacing the stale
record, together with any live session it left behind (stopped, not finalized
twice). A uuid that finished without error is never run twice.

**The dispatcher's own copies never re-run.** Each ``async_action_dispatcher``
call has one ``dispatch_id``, sent on its RPC request and again on its HTTP
re-send (``X-Helao-Dispatch-Id``) after a probe timeout. A failed record re-runs
only for a request whose id this uuid has not seen; one already seen (the other
copy of a send that ran) answers :class:`ActionFailed` (a 500, which the
orchestrator pauses on), whichever copy arrives first. A request with no id (an
orchestrator that predates it) re-runs, as before the id existed, so the
two hosts should be updated together. A uuid never seen still runs.

**A failed attempt still stopping is not replaced.** Re-running while the old
session's executor is live would let it finish later into the same output
directory. It is stopped and the request answers :class:`ActionFailed`
("previous attempt still stopping"); the orchestrator's next resume finds the
finished record and re-runs.
"""

import asyncio
from collections import OrderedDict
from typing import Any, Optional

from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActionAdmission", "ActionFailed"]

#: Resolution of a pending record whose handler failed.
_FAILED = object()


class ActionFailed(RuntimeError):
    """The original request for a repeated action uuid failed."""


#: Seen-uuid record size. An action leaves it only after this many newer ones.
SEEN_MAX = 500


class ActionAdmission:
    """Decides run / park / duplicate for one action request on a host."""

    def __init__(self, host, maxlen: int = SEEN_MAX):
        """Hold the host back-reference; the seen-uuid record lives here."""
        self.host = host
        self.maxlen = maxlen
        #: uuid str -> [record, parked?, future, dispatch ids]. ``parked`` is
        #: True until the queued copy is relaunched, so the relaunch is not its
        #: own duplicate.
        #: ``future`` is pending while the handler runs and then holds its
        #: result (``_FAILED`` if it raised); None for a parked copy.
        #: ``dispatch ids`` are every ``dispatch_id`` that reached this uuid.
        #: Memory ceiling: ``maxlen`` (500) entries, each holding the handler's
        #: result, so a server with large results can hold 500 of them.
        self._seen: "OrderedDict[str, list]" = OrderedDict()

    def _remember(
        self, uuid: str, record: dict, parked: bool, ids: Optional[set] = None
    ) -> None:
        fut = None if parked else asyncio.get_running_loop().create_future()
        self._seen[uuid] = [record, parked, fut, ids if ids is not None else set()]
        self._seen.move_to_end(uuid)
        while len(self._seen) > self.maxlen:
            self._seen.popitem(last=False)

    def resolve(self, action_dict: dict, result: Any) -> None:
        """Record the handler's *result* and release repeats waiting on it."""
        entry = self._seen.get(str(action_dict.get("action_uuid")))
        if entry is None:
            return
        if result is not None:
            entry[0] = result
        if entry[2] is not None and not entry[2].done():
            entry[2].set_result(result)

    def forget(self, action_dict: dict, release: bool = False) -> None:
        """Mark a uuid whose handler failed and fail the repeats waiting on it.

        The entry stays, resolved to ``_FAILED``, so the next request for the
        uuid is recognised as a retry and run (see :meth:`admit`). With
        *release* (the request failed before the handler body started, so
        nothing ran) the entry is removed instead, so the other copy of the
        same send runs.
        """
        uuid = action_dict.get("action_uuid")
        entry = self._seen.get(str(uuid)) if uuid else None
        if entry is not None and entry[2] is not None and not entry[2].done():
            entry[2].set_result(_FAILED)
        if release and entry is not None:
            self._seen.pop(str(uuid), None)

    def _is_failed(self, entry: Optional[list], held: Any) -> bool:
        """True if the record *held* for a uuid is a failed, finished action."""
        if entry is not None and entry[2] is not None and entry[2].done():
            if entry[2].result() is _FAILED:
                return True
        status = held.get("action_status") if isinstance(held, dict) else None
        return bool(status) and any(
            s in status for s in (HloStatus.errored, HloStatus.estopped)
        )

    def _stop_live(self, uuid: str) -> bool:
        """Stop sessions of *uuid* whose executor is still running; True if any.

        Such a session will still finish, and its finalizer would write into
        the output directory a re-run shares, so the re-run must wait for it.
        """
        running = {id(s) for s in self.host.executors.values()}
        live = [
            s
            for k, s in self.host.actives.items()
            if str(k) == uuid and id(s) in running
        ]
        for sess in live:
            sess.set_estop()
            sess.stop_action_task()
        return bool(live)

    def _drop(self, uuid: str) -> None:
        """Remove every record of *uuid* so a re-run is the only one left.

        A live session left by a handler that raised is stopped first (as
        ``/estop`` does), so it cannot keep driving hardware or logging once its
        record is gone.
        """
        self._seen.pop(uuid, None)
        for k in [k for k in self.host.actives if str(k) == uuid]:
            sess = self.host.actives.pop(k)
            sess.set_estop()
            sess.stop_action_task()
            if sess.data_logger is not None:
                sess.data_logger.cancel()
        for k in [k for k in self.host.history if str(k) == uuid]:
            del self.host.history[k]

    def _existing(self, uuid: str) -> Optional[dict]:
        """Return the record for *uuid* if this server already took it, else None."""
        host = self.host
        for k, sess in list(host.actives.items()):
            if str(k) == uuid:
                return sess.action.as_dict()
        for k, act in list(host.history.items()):
            if str(k) == uuid:
                return act.as_dict()
        entry = self._seen.get(uuid)
        if entry is not None:
            return entry[0]
        for em in host.actionservermodel.endpoints.values():
            for k, act in list(em.active_dict.items()):
                if str(k) == uuid:
                    return act.as_dict()
        return None

    def _park(self, action_dict: dict, endpoint: str, params: dict, queue, why: str):
        """Build the queued action, announce it, and park it on *queue*."""
        from helao.helpers.eval import eval_val
        from helao.helpers.premodels import Action
        from helao.helpers.time_utils import gen_uuid
        from helao.hexagon.app.action_host import ACTION_PARAM_KEYS

        action_dict["action_params"] = action_dict.get("action_params") or {}
        action_dict["action_params"]["queued_on_actserv"] = True
        extra_params = {}
        action = Action.model_validate(action_dict)
        if not action.action_uuid:
            action.action_uuid = gen_uuid()
        for k, v in params.items():
            if k in ACTION_PARAM_KEYS:
                extra_params[k] = eval_val(v)
            else:
                action.action_params[k] = eval_val(v)
        action.action_name = endpoint
        action.action_server = self.host.server.model_copy()
        LOGGER.info(f"{why}, queuing action {action.action_uuid}")
        queue.append((action, extra_params))
        return action

    async def admit(
        self,
        endpoint: str,
        action_dict: dict,
        params: dict,
        transport: str,
        dispatch_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Decide one action request.

        Args:
            endpoint: Action endpoint name (last path segment).
            action_dict: The request's ``action`` body, ``{}`` if none.
            params: Query/path parameters (HTTP) or the non-``action`` RPC
                arguments, as a flat dict.
            transport: ``"http"`` or ``"rpc"``; only logged.
            dispatch_id: The dispatcher's id for this send, on both its copies;
                None from a caller that predates it.

        Returns:
            None to run the handler (also for a repeat of an errored or
            estopped uuid, which re-runs). Otherwise what to answer with: the
            original's result for a repeat of a running action (waited for), the
            existing record for a later repeat, the parked action's dict for a
            park.

        Raises:
            ActionFailed: A repeat's original request failed while it waited,
                or the other copy of a send that already failed arrived, or a
                failed attempt is still stopping.
        """
        host = self.host
        uuid = action_dict.get("action_uuid")
        uuid = str(uuid) if uuid else None
        queued_launch = bool(
            (action_dict.get("action_params") or {}).get("queued_launch", False)
        )
        #: dispatch ids already seen for this uuid, carried across a re-run
        ids: set = set()

        if uuid is not None:
            entry = self._seen.get(uuid)
            # A parked copy relaunching is the one legitimate second request.
            if queued_launch and entry is not None and entry[1]:
                entry[1] = False
                entry[2] = asyncio.get_running_loop().create_future()
                if dispatch_id is not None:
                    entry[3].add(dispatch_id)
                return None
            if entry is not None and entry[2] is not None and not entry[2].done():
                LOGGER.info(f"duplicate of running {uuid} on {endpoint}, waiting")
                result = await asyncio.shield(entry[2])
                if result is _FAILED:
                    raise ActionFailed(f"original request for {uuid} failed")
                return result if result is not None else entry[0]
            held = self._existing(uuid)
            if held is not None and self._is_failed(entry, held):
                ids = entry[3] if entry is not None else ids
                if dispatch_id is not None and dispatch_id in ids:
                    raise ActionFailed(f"{uuid} already failed, not re-running")
                if self._stop_live(uuid):
                    # this send is refused; its other copy must not run later
                    if entry is not None and dispatch_id is not None:
                        entry[3].add(dispatch_id)
                    raise ActionFailed(f"previous attempt of {uuid} still stopping")
                LOGGER.info(f"re-running failed action {uuid} on {endpoint}")
                self._drop(uuid)
                held = None
            if held is not None:
                LOGGER.info(
                    f"duplicate action request for {uuid} on {endpoint}, "
                    f"returning existing record ({transport})"
                )
                return held

        start_cond = action_dict.get("start_condition", ASC.wait_for_all)
        ep_model = host.actionservermodel.endpoints.get(endpoint)
        busy = bool(ep_model.active_dict) if ep_model is not None else False

        queue: Any = None
        why = ""
        if busy and start_cond != ASC.no_wait and not queued_launch:
            if not host.server_params.get("allow_concurrent_actions", True):
                if any(
                    em.active_dict for em in host.actionservermodel.endpoints.values()
                ):
                    queue = host.local_action_queue
                    why = "action server is busy and does not allow concurrency"
            else:
                queue = host.endpoint_queues[endpoint]
                why = "simultaneous action requests received"

        if queue is None:
            if uuid is not None:
                if dispatch_id is not None:
                    ids.add(dispatch_id)
                self._remember(uuid, action_dict, parked=False, ids=ids)
            return None

        action = self._park(action_dict, endpoint, params, queue, why)
        record = action.as_dict()
        self._remember(str(action.action_uuid), record, parked=True)
        await host.status_q.put(action.get_act())
        return record
