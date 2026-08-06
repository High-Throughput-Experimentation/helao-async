"""P7b substrate proof: every canonical frame round-trips through the REAL
transport decoders (`WsSubscriber`, `WsSyncClient`), for both producer
families.

`helao/hexagon/tests/test_ws_publish_bridge.py` already proves this for the
`base_api` family via `WsSubscriber` alone -- exactly the single-decoder
coverage §10.1(3) names as insufficient. This file is the substrate every
later consumer-parity test (`test_ws_consumer_parity.py`, and the per-
deployment `add_points` conformance suites) builds on: `harness/ws_frames.py`
produces frame bytes through the real encoder, this file proves those bytes
decode back to the right *type* and *value* through the real decoder -- not
just "does not raise" (the vacuity trap named in the plan): an empty dict
would pass a bare "decodes without error" check, so every assertion below
pins a sentinel value from the payload, not merely its shape.
"""

import pytest

from harness import ws_frames as wf

# 3 channels x 2 families = 6 combinations; this constant is asserted non-empty
# and of the expected size below so an inert product() call can't pass quietly.
_COMBOS = [(c, f) for c in wf.CHANNELS for f in wf.FAMILIES]


def test_combo_matrix_is_not_empty():
    """Anti-vacuity guard for the parametrization below."""
    assert len(_COMBOS) == 6, _COMBOS


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,family", _COMBOS)
async def test_frames_roundtrip_via_wssubscriber(channel, family):
    """Every (channel, family) frame decodes through the real WsSubscriber."""
    raw, decoded = await wf.roundtrip(channel, family, via="wssubscriber")
    assert raw, "encoder produced no bytes"

    if channel == "ws_status":
        if family == "base_api":
            from helao.core.models.action import ActionModel

            assert isinstance(decoded, ActionModel), type(decoded)
            assert decoded.action_uuid == wf.ACTION_UUID
        else:  # orch_api: StatusBroadcaster relays msg.as_dict()
            assert isinstance(decoded, dict), type(decoded)
            # as_dict() serializes UUID -> str (helaodict.py); the orch family
            # carries the string form on the wire, unlike base_api's object.
            assert decoded["action_uuid"] == str(wf.ACTION_UUID)
    elif channel == "ws_data":
        if family == "base_api":
            from helao.core.models.data import DataPackageModel

            assert isinstance(decoded, DataPackageModel), type(decoded)
            assert decoded.action_uuid == wf.ACTION_UUID
            row = next(iter(decoded.datamodel.data.values()))
            assert row[wf.NUMERIC_COLUMN] == wf.NUMERIC_VALUES
            assert row[wf.STRING_COLUMN] == wf.STRING_VALUES
        else:  # orch_api: dict, not a DataPackageModel
            assert isinstance(decoded, dict), type(decoded)
            assert decoded["action_uuid"] == str(wf.ACTION_UUID)
            row = next(iter(decoded["datamodel"]["data"].values()))
            assert row[wf.NUMERIC_COLUMN] == wf.NUMERIC_VALUES
            assert row[wf.STRING_COLUMN] == wf.STRING_VALUES
    else:  # ws_live: dict-native in both families
        assert isinstance(decoded, dict), type(decoded)
        assert decoded[wf.LIVE_FLOAT_LABEL] == (wf.LIVE_FLOAT_VALUE, wf.LIVE_EPOCH)
        assert decoded[wf.LIVE_STRING_LABEL] == (wf.LIVE_STRING_VALUE, wf.LIVE_EPOCH)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,family", _COMBOS)
async def test_frames_roundtrip_via_wssyncclient(channel, family):
    """The blocking WsSyncClient decoder face (ws_utils.py:95) also decodes
    every combination -- the second of the two transport decoder faces named
    in the P7b problem statement, so the substrate is not WsSubscriber-only
    either (the exact insufficiency this slice exists to close)."""
    raw, decoded = await wf.roundtrip(channel, family, via="wssyncclient")
    assert raw
    assert decoded != {}, "WsSyncClient returned its empty-retry sentinel"
    # A light-touch check (full type assertions are covered by the
    # WsSubscriber variant above): the same sentinel value must be present
    # regardless of which decoder unpickled it.
    if channel == "ws_live":
        assert decoded[wf.LIVE_FLOAT_LABEL][0] == wf.LIVE_FLOAT_VALUE
    elif channel == "ws_status":
        if family == "base_api":
            assert decoded.action_uuid == wf.ACTION_UUID
        else:
            assert decoded["action_uuid"] == str(wf.ACTION_UUID)
    else:
        get_data = (
            decoded.datamodel.data
            if family == "base_api"
            else decoded["datamodel"]["data"]
        )
        row = next(iter(get_data.values()))
        assert row[wf.NUMERIC_COLUMN] == wf.NUMERIC_VALUES


@pytest.mark.asyncio
async def test_mutation_probe_wrong_bytes_decode_to_different_value():
    """Proves the byte-comparison technique used elsewhere (P7b task 2's
    byte-identical test) can actually fail: two frames built from different
    payloads must decode to different sentinel values, not the same one."""
    raw_a, decoded_a = await wf.roundtrip(
        "ws_live", "base_api", payload=wf.build_live_payload(numeric={"x": 1.0})
    )
    raw_b, decoded_b = await wf.roundtrip(
        "ws_live", "base_api", payload=wf.build_live_payload(numeric={"x": 2.0})
    )
    assert raw_a != raw_b, "different payloads produced byte-identical frames"
    assert decoded_a["x"][0] != decoded_b["x"][0]
