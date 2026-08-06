"""P7b task 2: wire-consumer parity tests over the `harness/ws_frames`
substrate.

Extends `test_ws_publish_bridge.py` past its WsSubscriber-only, base_api-only
coverage (§10.1(3)'s named insufficiency) with:

1. The hexagon's `WsPublishBridge` produces byte-identical frames to the
   legacy `WsPublisher` for identical inputs.
2. The orch `_ws_relay` encoding (no wire test at all before this slice) is
   pinned: it carries dicts, never the typed model `BaseAPI` sends.
3. The Reflex ingest normalizers are proven correct per-channel AND proven to
   yield nothing when handed the *other* channel's frame -- the emptiness is
   asserted explicitly, not inferred from a right-pair pass (the plan's named
   vacuity trap: "returns empty" must never read as a pass on its own).
4. `/ws_globstat` has no route registration on either API class (Corrections
   §C1b) -- extracted statically via `harness.endpoints`, the same tool the
   repo already uses for its endpoint-parity checklist, so this isn't a
   hand-rolled route scan either.
5. The operator's `RemoteBackend._ws_loop` is shape-blind: it fires the same
   `on_change` callback for both producer families' ws_status frames,
   documented so nobody cites it as evidence of ws_status parity.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from harness import ws_frames as wf
from harness.endpoints import extract_routes
from helao.core.servers.reflex.ingest import normalize, normalize_data_package
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge

BASE_API_PATH = Path("helao/core/servers/base_api.py")
ORCH_API_PATH = Path("helao/core/servers/orch_api.py")


@pytest.mark.asyncio
async def test_ws_publish_bridge_frames_byte_identical_to_legacy():
    """For identical inputs, WsPublishBridge's frame == the legacy
    WsPublisher's frame, byte-compared -- extends test_ws_publish_bridge.py
    past its type-restoration-only assertions."""
    status_q = MultisubscriberQueue()
    legacy_pub = WsPublisher(status_q)
    bridge_q = MultisubscriberQueue()
    bridge = WsPublishBridge(bridge_q, bridge_q, bridge_q)

    legacy_ws = wf.FakeWebSocket()
    bridge_ws = wf.FakeWebSocket()
    # FakeWebSocket deliberately duck-types the two methods WsPublisher.broadcast
    # calls (accept/send_bytes) instead of being a real starlette WebSocket, so
    # the real encode step runs without a live socket per frame (see ws_frames.py).
    legacy_task = asyncio.ensure_future(
        legacy_pub.broadcast(legacy_ws)  # type: ignore[arg-type]
    )
    bridge_pub = WsPublisher(bridge_q)
    bridge_task = asyncio.ensure_future(
        bridge_pub.broadcast(bridge_ws)  # type: ignore[arg-type]
    )

    for q in (status_q, bridge_q):
        for _ in range(200):
            if q.subscribers:
                break
            await asyncio.sleep(0.01)
        assert q.subscribers

    status_dict = wf.build_status_payload().as_dict()
    # Both sides must reconstruct via ActionModel.model_validate(dict) --
    # WsPublishBridge always does (that is its whole job); the legacy path
    # normally pickles a *live* Base-owned object instead, whose
    # __pydantic_fields_set__ differs from one rebuilt from a full dict (all
    # keys "set" vs. only the two kwargs originally passed), which pickles
    # to different bytes despite equal field *values*. Reconstructing both
    # from the identical dict is the honest "for identical inputs" control.
    from helao.core.models.action import ActionModel

    await status_q.put(ActionModel.model_validate(status_dict))  # legacy path
    await bridge.publish_status(status_dict)  # bridge: model_validate then put

    for ws in (legacy_ws, bridge_ws):
        for _ in range(200):
            if ws.frames:
                break
            await asyncio.sleep(0.01)
        assert ws.frames, "no frame produced"

    await status_q.close()
    await bridge_q.close()
    await asyncio.wait_for(legacy_task, timeout=5)
    await asyncio.wait_for(bridge_task, timeout=5)

    assert legacy_ws.frames[0] == bridge_ws.frames[0], (
        "hexagon WsPublishBridge frame diverged from the legacy WsPublisher "
        "frame for an identical ActionModel payload"
    )
    # Mutation probe: a *different* payload must NOT collide -- proves the
    # byte-comparison above can actually fail, not just always pass.
    other = wf.build_status_payload(action_name="different_action").as_dict()
    other_ws = wf.FakeWebSocket()
    # Same intentional duck-typed double as above.
    other_task = asyncio.ensure_future(
        bridge_pub.broadcast(other_ws)  # type: ignore[arg-type]
    )
    for _ in range(200):
        if bridge_q.subscribers:
            break
        await asyncio.sleep(0.01)
    await bridge.publish_status(other)
    for _ in range(200):
        if other_ws.frames:
            break
        await asyncio.sleep(0.01)
    await bridge_q.close()
    await asyncio.wait_for(other_task, timeout=5)
    assert other_ws.frames[0] != legacy_ws.frames[0]


@pytest.mark.asyncio
async def test_orch_relay_encoding_pinned():
    """First wire test for _ws_relay (base_status.py): the orch family
    carries plain dicts on /ws_status and /ws_data, never the typed model
    base_api's WsPublisher.broadcast sends. A future phase that silently
    converges the two encodings would blank every remote subscriber that
    expects the dict shape (or crash the ones expecting an object)."""
    for channel in ("ws_status", "ws_data"):
        _, decoded = await wf.roundtrip(channel, "orch_api")
        assert type(decoded) is dict, (
            f"{channel} via orch_api decoded to {type(decoded)}, expected a "
            "plain dict (StatusBroadcaster._ws_relay calls msg.as_dict())"
        )
        # And the base_api sibling is NOT a dict for these two channels --
        # the two families are provably different, not just differently
        # spelled.
        _, base_decoded = await wf.roundtrip(channel, "base_api")
        assert type(base_decoded) is not dict, (
            f"{channel} via base_api decoded to a dict too; the two "
            "producer families are supposed to diverge here"
        )


@pytest.mark.asyncio
async def test_reflex_normalize_per_channel():
    """normalize() (ws_live) and normalize_data_package() (ws_data) each
    handle their own channel's frame correctly, AND each yields nothing for
    the *other* channel's frame -- asserted explicitly so "returns empty"
    can never be mistaken for a pass on its own (it is only meaningful next
    to the right-pair assertions below, which require non-empty content)."""
    _, live_msg = await wf.roundtrip("ws_live", "base_api")
    _, data_msg = await wf.roundtrip("ws_data", "base_api")

    # Right pair: normalize() over ws_live.
    cols, rows = normalize([live_msg])
    assert cols[wf.LIVE_FLOAT_LABEL] == [wf.LIVE_FLOAT_VALUE]
    assert rows == [{wf.LIVE_STRING_LABEL: wf.LIVE_STRING_VALUE}]

    # Right pair: normalize_data_package() over ws_data.
    cols2, rows2 = normalize_data_package([data_msg])
    assert cols2[wf.NUMERIC_COLUMN] == [float(v) for v in wf.NUMERIC_VALUES]
    # The string column is silently dropped (ingest.py:204-209), NOT routed
    # to rows the way normalize() would -- the two normalizers' semantics
    # are deliberately different, pinned here by name.
    assert wf.STRING_COLUMN not in cols2
    assert not any(wf.STRING_COLUMN in r for r in rows2)

    # Cross pair: normalize() is dict-only and drops the DataPackageModel
    # object outright (it is not a dict).
    cross_cols, cross_rows = normalize([data_msg])
    assert cross_cols == {} and cross_rows == []

    # Cross pair: normalize_data_package() finds no `.datamodel` on a plain
    # ws_live dict and yields nothing either.
    cross_cols2, cross_rows2 = normalize_data_package([live_msg])
    assert cross_cols2 == {} and cross_rows2 == []


def test_ws_globstat_is_dead():
    """No route registration for /ws_globstat exists on either API class --
    Corrections §C1b. Uses the repo's own static AST route extractor
    (harness.endpoints), not a hand-rolled grep, so a future dynamic-route
    addition is exactly as visible here as to the endpoint-parity checklist
    that tool already gates."""
    base_routes = extract_routes(BASE_API_PATH)
    orch_routes = extract_routes(ORCH_API_PATH)
    assert base_routes, "extractor found nothing in base_api.py -- inert glob?"
    assert orch_routes, "extractor found nothing in orch_api.py -- inert glob?"

    base_paths = {r["path"] for r in base_routes}
    orch_paths = {r["path"] for r in orch_routes}
    # The three routes that DO carry a live producer, as a sanity check that
    # the extractor is actually seeing this file's websocket decorators.
    for expected in ("/ws_status", "/ws_data", "/ws_live"):
        assert expected in orch_paths, (expected, orch_paths)

    assert "/ws_globstat" not in base_paths
    assert "/ws_globstat" not in orch_paths


def test_operator_ws_face_is_shape_blind():
    """RemoteBackend._ws_loop (orch_backend.py:337-346) decodes nothing --
    truthiness only -- so it fires on_change identically no matter which
    producer family's ws_status frame arrived. Documented so nobody cites the
    operator as evidence of ws_status parity between the two families."""
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    class _FakeSelf:
        """Stands in for a RemoteBackend, carrying only the one attribute
        _ws_loop actually reads (self._wss) -- declared so the assignment
        below type-checks rather than needing per-assignment ignores."""

        _wss: Any = None

    async def _run():
        for family in wf.FAMILIES:
            raw = await wf.frame("ws_status", family)
            async with wf.replay_server({"ws_status": raw}) as (host, port):
                fake_self = _FakeSelf()
                from helao.helpers.ws_utils import WsSubscriber

                fake_self._wss = WsSubscriber(host, port, "ws_status")
                on_change_calls: list[int] = []
                # _FakeSelf duck-types RemoteBackend for this call -- _ws_loop
                # only ever touches self._wss, so a full RemoteBackend (which
                # needs a live world config + action libraries to construct)
                # is unnecessary here.
                loop_task = asyncio.ensure_future(
                    RemoteBackend._ws_loop(
                        fake_self,  # type: ignore[arg-type]
                        lambda: on_change_calls.append(1),
                    )
                )
                for _ in range(200):
                    if on_change_calls:
                        break
                    await asyncio.sleep(0.02)
                loop_task.cancel()
                import contextlib

                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await loop_task
                fake_self._wss.subscriber_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await fake_self._wss.subscriber_task
                calls.append((family, len(on_change_calls)))

    asyncio.run(_run())

    assert len(calls) == len(wf.FAMILIES) == 2
    for family, count in calls:
        assert count > 0, (
            f"_ws_loop never fired on_change for the {family} ws_status "
            "frame -- it should fire for BOTH families identically, since "
            "it never inspects the decoded message's shape"
        )
