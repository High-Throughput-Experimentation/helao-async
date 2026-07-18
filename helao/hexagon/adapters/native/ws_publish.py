"""Native WS publish bridge (P2b-2): functional publish_status/data/live.

Discharges the DD-7 HexagonDeferred on DispatcherStatusAdapter.publish_*
by putting each payload onto the composition's legacy fan-out queues
(base.status_q / data_q / live_q) — the queues the legacy-hosted
WsPublisher routes (/ws_status /ws_data /ws_live, base_api.py:677-708)
broadcast from. Frame bytes are then produced by the untouched legacy
``pyzstd.compress(pickle.dumps(...))`` path (helao/helpers/ws_utils.py) —
wire parity by construction, certified by the round-trip test.

Port-vs-wire drift resolved HERE, adapter-local (P2b-2 D1): the StatusPort
publish_* members are dict-typed (Protocol unchanged — fakes and other
adapters share it), but the legacy consumers expect typed objects on the
wire: status_q carries ActionModel (log_status_task does attribute access),
data_q carries DataPackageModel, live_q is dict-native. Each put
model_validates its payload back to the channel's wire type; a malformed
payload fails loud with pydantic.ValidationError, never a silent bad frame.

The queue refs live on the legacy Base, which only exists once the app has
started — the bridge is therefore constructed and bound in makeActionApp's
startup hook (D3: ACTION apps only; orch WS stays on legacy relays, Q1).

This module is HAND-WRITTEN (not a verbatim re-body copy) and is
black-enforced (pyproject force-exclude narrowed in P2b-2, D2).
"""

from helao.core.models.action import ActionModel
from helao.core.models.data import DataPackageModel
from helao.helpers.multisubscriber_queue import MultisubscriberQueue

__all__ = ["WsPublishBridge"]


class WsPublishBridge:
    """Holds the three legacy fan-out queue refs and converts each dict
    payload to its channel's wire type at put time (D1)."""

    def __init__(
        self,
        status_q: MultisubscriberQueue,
        data_q: MultisubscriberQueue,
        live_q: MultisubscriberQueue,
    ):
        self._status_q = status_q
        self._data_q = data_q
        self._live_q = live_q

    async def publish_status(self, payload: dict) -> None:
        await self._status_q.put(ActionModel.model_validate(payload))

    async def publish_data(self, payload: dict) -> None:
        await self._data_q.put(DataPackageModel.model_validate(payload))

    async def publish_live(self, payload: dict) -> None:
        await self._live_q.put(payload)
