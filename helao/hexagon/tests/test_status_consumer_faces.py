"""P7c: the Status port's three consumer faces (Amendment §8).

``ports/status.py`` was publish-side only. Amendment §8 requires it to
enumerate three *consumer* faces, of which the third (the Reflex ingest
normalizers) is keyed by ``ws_path`` rather than uniform across channels.
This module pins that enumeration, proves each face is satisfied by the
concrete consumer the tree actually runs, and pins the measured absence of a
``ws_status`` consumer on the Reflex side.

Every behavioral assertion here runs over the P7b frame substrate
(``harness.ws_frames``), which drives the two *real* production encoders --
no frame is hand-rolled here, and no decoder is re-implemented.

The vacuity trap this file is written against: ``@runtime_checkable``
``isinstance`` only checks method *presence*, and for a callback Protocol
that means *any* function passes. :func:`test_isinstance_alone_is_vacuous_
for_a_callback_protocol` demonstrates that directly, which is why every face
check below is paired with a signature check and a behavioral call.
"""

import ast
import asyncio
import inspect
from typing import Any

import pytest

from harness import ws_frames as wf
from helao.ui.reflex import ingest
from helao.ui.reflex.app import declared_ws_path
from helao.ui.reflex.ingest import (
    NORMALIZERS,
    VIS_KEY_TO_WS_PATH,
    IngestRegistry,
    normalize,
    normalize_data_package,
)
from helao.hexagon.adapters.vis.ws_consumer import CHANNEL_NORMALIZERS, WsConsumer
from helao.hexagon.ports import status as status_port
from helao.hexagon.ports.status import (
    CHANNELS,
    CONSUMER_FACES,
    ChannelNormalizerPort,
    StatusStreamPort,
)

EXPECTED_FACES = {
    "bokeh_ws_subscriber": "StatusStreamPort",
    "relay_pickle_stream": "StatusStreamPort",
    "reflex_ingest_normalizer": "ChannelNormalizerPort",
}


# --------------------------------------------------------------------------
# Face 0: the enumeration itself
# --------------------------------------------------------------------------


def test_three_faces_enumerated():
    """The port names exactly three consumer faces, each pointing at a
    Protocol this module actually defines."""
    assert len(CONSUMER_FACES) == 3, CONSUMER_FACES
    assert CONSUMER_FACES == EXPECTED_FACES
    # Each named port must be a real, runtime-checkable Protocol on the
    # module -- a face pointing at a typo'd name would otherwise read as an
    # enumerated face while naming nothing.
    for face, port_name in CONSUMER_FACES.items():
        port = getattr(status_port, port_name, None)
        assert port is not None, f"{face} names {port_name!r}, which does not exist"
        assert getattr(port, "_is_runtime_protocol", False), port_name
    # Both Protocols are reachable from the enumeration (faces 1+2 share one).
    assert set(CONSUMER_FACES.values()) == {
        "StatusStreamPort",
        "ChannelNormalizerPort",
    }


def test_port_channel_vocabulary_matches_the_frame_substrate():
    """``CHANNELS`` is the same three routes ``harness.ws_frames`` encodes
    for -- pinned across the two modules so a channel added to one and not
    the other is a failure, not a silently untested route."""
    assert len(CHANNELS) == 3
    assert set(CHANNELS) == set(wf.CHANNELS) == {"ws_status", "ws_data", "ws_live"}


def test_port_module_names_no_vendor_type():
    """Ports may import only domain/ports/``helao_driver``
    (test_boundaries.py:78-82), so the two new Protocols must be expressible
    without naming a vendor type. Checked structurally: no import in the
    module names a banned top-level package, and every annotation on the two
    consumer Protocols is a builtin."""
    tree = ast.parse(inspect.getsource(status_port))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported, "no imports parsed -- inert AST walk"
    for module in imported:
        top = module.split(".")[0]
        assert top not in (
            "bokeh",
            "reflex",
            "fastapi",
            "websockets",
            "pyzstd",
        ), f"{module!r} leaked into the status port"

    builtins_only = {"str", "int", "list", "object", "None", "bool", "dict", "tuple"}
    for port in (StatusStreamPort, ChannelNormalizerPort):
        for name, member in vars(port).items():
            if not callable(member) or name.startswith("_") and name != "__call__":
                continue
            for arg, annotation in getattr(member, "__annotations__", {}).items():
                rendered = getattr(annotation, "__name__", str(annotation))
                assert rendered in builtins_only, (
                    f"{port.__name__}.{name}({arg}) is annotated {rendered!r}, "
                    "which is not a builtin -- the seam would leak a type"
                )


# --------------------------------------------------------------------------
# Faces 1+2: StatusStreamPort over the real WsSubscriber
# --------------------------------------------------------------------------


def test_ws_consumer_satisfies_status_stream_port():
    """Presence check. Weak on its own (see the vacuity test below); the
    teeth are in ``test_ws_consumer_decodes_every_channel_and_family``."""
    assert isinstance(WsConsumer(), StatusStreamPort)


@pytest.mark.asyncio
async def test_ws_consumer_decodes_every_channel_and_family():
    """The adapter reads back what each real encoder wrote, for all three
    channels of *both* producer families -- the six combinations Amendment
    §8(2) says a WsSubscriber-only test does not cover.

    The per-combination expectations are deliberately type-discriminating:
    ``/ws_status`` and ``/ws_data`` carry a typed model from base_api and a
    plain dict from orch_api, and asserting only "something arrived" would
    pass even if the two families had silently converged.
    """
    consumer = WsConsumer()
    seen: dict[tuple[str, str], Any] = {}

    for channel in CHANNELS:
        for family in wf.FAMILIES:
            raw = await wf.frame(channel, family)
            messages: list = []
            async with wf.replay_server({channel: raw}) as (host, port):
                subscription = consumer.subscribe(host, port, channel)
                try:
                    for _ in range(200):
                        messages.extend(await consumer.read(subscription))
                        if messages:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await consumer.close(subscription)
            assert messages, f"nothing decoded for {channel}/{family}"
            seen[(channel, family)] = messages[0]

    assert len(seen) == len(CHANNELS) * len(wf.FAMILIES) == 6, sorted(seen)

    # base_api sends the object; orch_api sends msg.as_dict() -- except on
    # ws_live, which is a dict on both sides by construction.
    assert seen[("ws_status", "base_api")].action_uuid == wf.ACTION_UUID
    assert type(seen[("ws_status", "orch_api")]) is dict
    assert seen[("ws_data", "base_api")].action_uuid == wf.ACTION_UUID
    assert type(seen[("ws_data", "orch_api")]) is dict
    for family in wf.FAMILIES:
        live = seen[("ws_live", family)]
        assert type(live) is dict
        assert live[wf.LIVE_FLOAT_LABEL] == (wf.LIVE_FLOAT_VALUE, wf.LIVE_EPOCH)

    # The two families are provably distinct on the two typed channels --
    # this is the assertion that fails if a future phase converges them.
    for channel in ("ws_status", "ws_data"):
        assert type(seen[(channel, "base_api")]) is not dict, channel


@pytest.mark.asyncio
async def test_ws_consumer_rejects_an_unknown_channel():
    """A typo'd path would otherwise reconnect forever with a warning line
    and no error, leaving a permanently empty panel.

    Runs inside a loop throughout: ``WsSubscriber.__init__`` creates a task,
    so a guard removed from :meth:`WsConsumer.subscribe` must surface as
    "DID NOT RAISE" here rather than as an unrelated "no running event loop".
    """
    consumer = WsConsumer()
    with pytest.raises(ValueError, match="unknown status channel"):
        consumer.subscribe("127.0.0.1", 1, "ws_stats")
    # Mutation probe for the guard itself: every legitimate channel must get
    # past it (a guard that rejected everything would also pass the line
    # above). Port 9 is never connected to -- the subscriber task is torn
    # down before its first connect attempt completes.
    accepted = []
    for channel in CHANNELS:
        subscription = consumer.subscribe("127.0.0.1", 9, channel)
        accepted.append(channel)
        await consumer.close(subscription)
    assert accepted == list(CHANNELS)


# --------------------------------------------------------------------------
# Face 3: ChannelNormalizerPort over the real ingest normalizers
# --------------------------------------------------------------------------


def test_isinstance_alone_is_vacuous_for_a_callback_protocol():
    """Named vacuity trap, demonstrated rather than asserted in prose.

    ``isinstance(x, ChannelNormalizerPort)`` checks only that ``x`` has a
    ``__call__`` -- so a function with an incompatible signature, and even
    one with no relationship to normalization at all, passes. Every face
    check in this file therefore pairs it with the signature check exercised
    here and with a behavioral call over a real frame.
    """

    def wrong_signature(a, b, c):
        return None

    assert isinstance(wrong_signature, ChannelNormalizerPort)  # vacuous, as shown
    assert not _matches_normalizer_signature(wrong_signature)
    # ...and the real ones do match, so the check is not simply always-false.
    for normalizer in (normalize, normalize_data_package):
        assert _matches_normalizer_signature(normalizer), normalizer.__name__


def _matches_normalizer_signature(candidate) -> bool:
    """True when ``candidate`` takes exactly the one positional parameter
    ``ChannelNormalizerPort.__call__`` declares (``messages``)."""
    declared = list(inspect.signature(ChannelNormalizerPort.__call__).parameters)
    declared.remove("self")
    try:
        actual = list(inspect.signature(candidate).parameters)
    except (TypeError, ValueError):
        return False
    return actual == declared


def test_hexagon_normalizer_declaration_mirrors_the_reflex_map():
    """The hexagon's typed declaration and the Reflex stack's own map hold
    the *same function objects* for the same channels -- a copy, not a
    reimplementation, so drift is impossible rather than merely unlikely."""
    assert NORMALIZERS, "ingest.NORMALIZERS is empty -- nothing to conform to"
    assert len(CHANNEL_NORMALIZERS) == len(NORMALIZERS) == 2
    assert CHANNEL_NORMALIZERS == NORMALIZERS
    for channel, normalizer in CHANNEL_NORMALIZERS.items():
        assert normalizer is NORMALIZERS[channel]
        assert isinstance(normalizer, ChannelNormalizerPort)
        assert _matches_normalizer_signature(normalizer)


@pytest.mark.asyncio
async def test_normalizer_face_is_behavioral_over_real_frames():
    """Each declared normalizer produces content for its own channel's frame
    and *nothing* for the other's -- the emptiness asserted explicitly beside
    a non-empty right-pair, never on its own."""
    _, live_msg = await wf.roundtrip("ws_live", "base_api")
    _, data_msg = await wf.roundtrip("ws_data", "base_api")
    frames = {"ws_live": live_msg, "ws_data": data_msg}

    results = {}
    for channel, normalizer in CHANNEL_NORMALIZERS.items():
        right_cols, _ = normalizer([frames[channel]])
        other = next(c for c in frames if c != channel)
        wrong_cols, wrong_rows = normalizer([frames[other]])
        results[channel] = (right_cols, wrong_cols, wrong_rows)

    assert len(results) == 2
    assert results["ws_live"][0][wf.LIVE_FLOAT_LABEL] == [wf.LIVE_FLOAT_VALUE]
    assert results["ws_data"][0][wf.NUMERIC_COLUMN] == [
        float(v) for v in wf.NUMERIC_VALUES
    ]
    for channel, (_, wrong_cols, wrong_rows) in results.items():
        assert wrong_cols == {} and wrong_rows == [], (
            f"{channel}'s normalizer produced output for the other channel's "
            "frame; the two payload shapes are supposed to be mutually "
            "unreadable"
        )


# --------------------------------------------------------------------------
# The ws_path edge, and the measured absence
# --------------------------------------------------------------------------


def test_ws_path_override_edge():
    """A panel module's own ``WS_PATH`` wins over its config key's default
    (``app.declared_ws_path``), in both directions, exercised against the
    real modules and the real discovery -- not a stub.

    This is the edge that makes face 3 non-uniform: the key says which *page*
    a panel belongs on, the module says which *socket* it reads. A panel
    declared under ``live_vis`` while reading ``ws_data`` exists in a private
    deployment today; ``nidaqmx_vis`` is used here because it is a tracked
    module carrying the divergent ``WS_PATH``, driven with the key default
    the divergent case supplies.
    """
    # module says ws_data, key default says ws_live -> module wins
    assert declared_ws_path("nidaqmx_vis", "ws_live") == "ws_data"
    # ...and the opposite direction, so the assertion is not one-sided
    assert declared_ws_path("mfc_vis", "ws_data") == "ws_live"
    # an unresolvable module keeps the key's default rather than raising
    assert declared_ws_path("no_such_panel_module", "ws_live") == "ws_live"

    # Behavioral consequence, which is the whole reason the override exists:
    # routing by the key default alone would hand ws_data frames to the
    # ws_live normalizer, which drops them silently.
    key_default_normalizer = CHANNEL_NORMALIZERS["ws_live"]
    declared_normalizer = CHANNEL_NORMALIZERS[
        declared_ws_path("nidaqmx_vis", "ws_live")
    ]
    assert declared_normalizer is not key_default_normalizer

    data_msg = asyncio.run(wf.roundtrip("ws_data", "base_api"))[1]
    dropped_cols, dropped_rows = key_default_normalizer([data_msg])
    kept_cols, _ = declared_normalizer([data_msg])
    assert dropped_cols == {} and dropped_rows == []
    assert kept_cols[wf.NUMERIC_COLUMN] == [float(v) for v in wf.NUMERIC_VALUES]


def test_registry_has_no_ws_status_consumer(monkeypatch):
    """Measured: the Reflex stack has no ``ws_status`` consumer at all.

    ``VIS_KEY_TO_WS_PATH`` maps only ``live_vis``→``ws_live`` and
    ``action_vis``→``ws_data``, and ``NORMALIZERS`` is keyed to match, so
    ``IngestRegistry`` never subscribes to ``/ws_status``. Pinned so adding
    one is a deliberate act accompanied by a test change, not drift.
    """
    assert set(VIS_KEY_TO_WS_PATH) == {"live_vis", "action_vis"}
    assert set(VIS_KEY_TO_WS_PATH.values()) == {"ws_live", "ws_data"}
    assert set(NORMALIZERS) == {"ws_live", "ws_data"}
    assert "ws_status" in CHANNELS  # the channel exists; only the consumer does not

    world_cfg = {
        "servers": {
            "LIVE": {"host": "127.0.0.1", "port": 8001, "live_vis": "some_panel"},
            "ACT": {"host": "127.0.0.1", "port": 8002, "action_vis": "other_panel"},
        }
    }
    targets = IngestRegistry(world_cfg).targets()
    assert len(targets) == 2, targets
    assert set(targets) == {("LIVE", "ws_live"), ("ACT", "ws_data")}
    assert not [t for t in targets if t[1] == "ws_status"]

    # Mutation probe: the absence is a property of the mapping, not of the
    # registry being incapable of producing such a target. With a ws_status
    # vis key present, the registry does produce one -- so the assertions
    # above would catch a future addition instead of passing regardless.
    monkeypatch.setitem(ingest.VIS_KEY_TO_WS_PATH, "status_vis", "ws_status")
    probe_cfg = {
        "servers": {
            "ORCH": {"host": "127.0.0.1", "port": 8003, "status_vis": "a_panel"}
        }
    }
    probe_targets = IngestRegistry(probe_cfg).targets()
    assert probe_targets == [("ORCH", "ws_status")], probe_targets
