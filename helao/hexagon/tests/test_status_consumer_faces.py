"""The Reflex ingest normalizers: behaviour over real frames, the ``ws_path``
edge, and the measured absence of a ``ws_status`` consumer.

The normalizers in ``helao.ui.reflex.ingest.NORMALIZERS`` are keyed by
``ws_path``, not uniform across channels: ``ws_live`` relays a
``{datalab: (value, epoch)}`` dict while ``ws_data`` carries a pickled
``DataPackageModel``. A single normalizer silently drops the other endpoint's
messages with no error on either side.

Every behavioral assertion here runs over the P7b frame substrate
(``harness.ws_frames``), which drives the two *real* production encoders --
no frame is hand-rolled here, and no decoder is re-implemented.
"""

import asyncio

import pytest

from harness import ws_frames as wf
from helao.ui.reflex import ingest
from helao.ui.reflex.app import declared_ws_path
from helao.ui.reflex.ingest import (
    NORMALIZERS,
    VIS_KEY_TO_WS_PATH,
    IngestRegistry,
)

# --------------------------------------------------------------------------
# The real ingest normalizers
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalizer_face_is_behavioral_over_real_frames():
    """Each normalizer produces content for its own channel's frame
    and *nothing* for the other's -- the emptiness asserted explicitly beside
    a non-empty right-pair, never on its own."""
    _, live_msg = await wf.roundtrip("ws_live", "base_api")
    _, data_msg = await wf.roundtrip("ws_data", "base_api")
    frames = {"ws_live": live_msg, "ws_data": data_msg}

    results = {}
    for channel, normalizer in NORMALIZERS.items():
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

    This is the edge that makes the normalizers non-uniform: the key says which *page*
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
    key_default_normalizer = NORMALIZERS["ws_live"]
    declared_normalizer = NORMALIZERS[declared_ws_path("nidaqmx_vis", "ws_live")]
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
    assert "ws_status" in wf.CHANNELS  # the channel exists; only the consumer does not

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
