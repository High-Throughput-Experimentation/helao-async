"""Tests for the Reflex UI stack's WebSocket ingest layer."""

import asyncio
import pickle

import numpy as np
import pyzstd
import pytest
import websockets

from helao.core.servers.reflex.ingest import (
    IngestRegistry,
    WsIngest,
    normalize,
    normalize_data_package,
)


def test_normalize_unwraps_value_epoch_tuples():
    cols, rows = normalize([{"co2_ppm": (410.0, 100.0)}])
    assert cols["co2_ppm"] == [410.0]
    assert cols["epoch"] == [100.0]


def test_normalize_flattens_sim_dict():
    cols, _ = normalize([{"sim_dict": ({"series_0": 1.0, "series_1": 2.0}, 5.0)}])
    assert cols["series_0"] == [1.0]
    assert cols["series_1"] == [2.0]
    assert cols["epoch"] == [5.0]


def test_normalize_extends_on_list_values():
    cols, _ = normalize([{"v": ([1.0, 2.0, 3.0], 7.0)}])
    assert cols["v"] == [1.0, 2.0, 3.0]


def test_normalize_uses_max_epoch_per_message():
    cols, _ = normalize([{"a": (1.0, 10.0), "b": (2.0, 30.0)}])
    assert cols["epoch"] == [30.0]


def test_normalize_routes_non_numeric_values_to_rows():
    cols, rows = normalize([{"orchestrator": ("ORCH", 1.0), "v": (2.0, 1.0)}])
    assert "orchestrator" not in cols
    assert rows == [{"orchestrator": "ORCH"}]
    assert cols["v"] == [2.0]


def test_normalize_handles_empty_input():
    cols, rows = normalize([])
    assert cols == {}
    assert rows == []


def test_normalize_ignores_malformed_entries():
    cols, _ = normalize([{"bad": "not a tuple", "good": (1.0, 2.0)}])
    assert cols["good"] == [1.0]
    assert "bad" not in cols


def test_normalize_keeps_intermittent_columns_aligned_with_epoch():
    """The defect this guards: a key absent from a message must consume a row.

    Without a per-message fill, `v`'s second value lands on the second message
    that *contains* `v` rather than the third row, and every later sample plots
    against the wrong timestamp.
    """
    import math

    cols, _ = normalize(
        [
            {"v": (1.0, 1.0)},
            {"a": (10.0, 2.0)},
            {"v": (2.0, 3.0), "a": (20.0, 3.0)},
        ]
    )
    assert cols["epoch"] == [1.0, 2.0, 3.0]
    assert cols["v"][0] == 1.0 and math.isnan(cols["v"][1]) and cols["v"][2] == 2.0
    assert math.isnan(cols["a"][0]) and cols["a"][1] == 10.0 and cols["a"][2] == 20.0


def test_normalize_every_column_has_equal_length():
    """RingBuffer.append rejects a ragged block, so this is a hard invariant."""
    cols, _ = normalize([{"v": (1.0, 1.0)}, {"a": (10.0, 2.0)}, {"v": (2.0, 3.0)}])
    assert len({len(c) for c in cols.values()}) == 1


def test_normalize_repeats_the_epoch_across_a_burst():
    """A burst of N samples shares one timestamp; all N rows need it.

    Leaving the trailing rows with a nan epoch would put them at no x position
    at all, since epoch is the plot's x axis.
    """
    cols, _ = normalize([{"burst": ([1.0, 2.0, 3.0], 5.0)}])
    assert cols["burst"] == [1.0, 2.0, 3.0]
    assert cols["epoch"] == [5.0, 5.0, 5.0]


def test_normalize_pads_a_scalar_alongside_a_burst():
    import math

    cols, _ = normalize([{"burst": ([1.0, 2.0, 3.0], 5.0), "one": (9.0, 5.0)}])
    assert cols["one"][0] == 9.0
    assert all(math.isnan(x) for x in cols["one"][1:])
    assert cols["epoch"] == [5.0, 5.0, 5.0]


def test_normalize_a_row_only_message_still_consumes_a_row():
    """A non-numeric-only message advances epoch, so numeric columns must too."""
    import math

    cols, rows = normalize(
        [{"v": (1.0, 1.0)}, {"label": ("abc", 2.0)}, {"v": (3.0, 3.0)}]
    )
    assert cols["epoch"] == [1.0, 2.0, 3.0]
    assert cols["v"][0] == 1.0 and math.isnan(cols["v"][1]) and cols["v"][2] == 3.0
    assert rows == [{"label": "abc"}]


def test_normalize_skips_a_non_dict_message():
    cols, _ = normalize(["not a dict", {"v": (1.0, 1.0)}])
    assert cols["v"] == [1.0]


def test_normalize_skips_a_wrong_arity_payload():
    cols, _ = normalize([{"bad": (1.0, 2.0, 3.0), "good": (4.0, 5.0)}])
    assert "bad" not in cols
    assert cols["good"] == [4.0]


def test_normalize_treats_epoch_zero_as_a_real_timestamp():
    """Truthiness would drop epoch 0.0 while still admitting its values."""
    cols, _ = normalize([{"v": (1.0, 0.0)}])
    assert cols["epoch"] == [0.0]
    assert cols["v"] == [1.0]


def test_normalize_data_package_unwraps_a_model_object():
    """ws_data carries pickled DataPackageModel objects, not dicts.

    normalize() drops them at its isinstance(message, dict) guard, which left
    the action visualizer permanently empty while its status still read "live".
    """
    import uuid

    from helao.core.models.data import DataModel, DataPackageModel

    pkg = DataPackageModel(
        action_uuid=uuid.uuid4(),
        action_name="measure_cp",
        datamodel=DataModel(
            data={uuid.uuid4(): {"t_s": [0.1, 0.2, 0.3], "erhe_v": [1.2, 1.3, 1.4]}},
            errors=[],
        ),
    )
    cols, rows = normalize_data_package([pkg])
    assert cols["t_s"] == [0.1, 0.2, 0.3]
    assert cols["erhe_v"] == [1.2, 1.3, 1.4]
    assert rows[0]["action_uuid"] == str(pkg.action_uuid)


def test_normalize_would_have_dropped_the_same_packet():
    """Pins why a second normalizer exists rather than one shared one."""
    import uuid

    from helao.core.models.data import DataModel, DataPackageModel

    pkg = DataPackageModel(
        action_uuid=uuid.uuid4(),
        action_name="measure_cp",
        datamodel=DataModel(data={uuid.uuid4(): {"t_s": [0.1]}}, errors=[]),
    )
    assert normalize([pkg]) == ({}, [])


def test_normalize_data_package_keeps_columns_aligned_across_packets():
    import math
    import uuid

    from helao.core.models.data import DataModel, DataPackageModel

    def _pkg(cols):
        return DataPackageModel(
            action_uuid=uuid.uuid4(),
            action_name="a",
            datamodel=DataModel(data={uuid.uuid4(): cols}, errors=[]),
        )

    cols, _ = normalize_data_package([_pkg({"t_s": [1.0]}), _pkg({"erhe_v": [9.0]})])
    assert len({len(c) for c in cols.values()}) == 1
    assert cols["t_s"][0] == 1.0 and math.isnan(cols["t_s"][1])
    assert math.isnan(cols["erhe_v"][0]) and cols["erhe_v"][1] == 9.0


def test_normalize_data_package_skips_non_numeric_columns():
    import uuid

    from helao.core.models.data import DataModel, DataPackageModel

    pkg = DataPackageModel(
        action_uuid=uuid.uuid4(),
        action_name="a",
        datamodel=DataModel(
            data={uuid.uuid4(): {"t_s": [1.0], "atfracs": ["Co0.5-Ni0.5"]}}, errors=[]
        ),
    )
    cols, _ = normalize_data_package([pkg])
    assert cols["t_s"] == [1.0]
    assert "atfracs" not in cols


def test_normalize_data_package_tolerates_junk():
    assert normalize_data_package(["nope", {}, {"datamodel": None}]) == ({}, [])


def test_wsingest_selects_its_normalizer_by_ws_path():
    live = WsIngest("127.0.0.1", 1, "ws_live")
    data = WsIngest("127.0.0.1", 1, "ws_data")
    assert live._normalize is normalize
    assert data._normalize is normalize_data_package


@pytest.mark.asyncio
async def test_wsingest_fills_buffer_from_a_live_server():
    async def handler(ws):
        for i in range(5):
            payload = {"v": (float(i), 100.0 + i)}
            await ws.send(pyzstd.compress(pickle.dumps(payload)))
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            for _ in range(200):
                if ing.buffer.length >= 5:
                    break
                await asyncio.sleep(0.02)
            snap = ing.buffer.snapshot()
            np.testing.assert_allclose(snap["v"], [0.0, 1.0, 2.0, 3.0, 4.0])
            assert ing.status.state == "live"
            assert ing.status.message_count >= 5
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_wsingest_recovers_after_the_server_restarts():
    sent = {"n": 0}

    async def handler(ws):
        sent["n"] += 1
        await ws.send(pyzstd.compress(pickle.dumps({"v": (float(sent["n"]), 1.0)})))
        await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            # WsSubscriber backs off 1s after a drop, so allow several seconds
            # for a second connection to land.
            for _ in range(400):
                if ing.buffer.length >= 2:
                    break
                await asyncio.sleep(0.02)
            assert ing.buffer.length >= 2, "subscriber did not reconnect"
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_stop_propagates_a_cancellation_of_stop_itself():
    """Tearing down our own tasks is not a failure; being cancelled is.

    Guards a subtle wrong fix: discriminating on ``task.cancelled()`` cannot
    work here, because ``stop()`` cancels the tasks itself before awaiting them,
    so that flag reads ``True`` no matter who cancelled the caller.
    """
    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.start()

    async def stubborn():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)  # slow to finish cancelling
            raise

    assert ing._task is not None
    ing._task.cancel()
    ing._task = asyncio.create_task(stubborn())
    await asyncio.sleep(0.05)

    stopper = asyncio.create_task(ing.stop())
    await asyncio.sleep(0.05)  # let stop() reach its await
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert ing._task is None and ing._wss is None


@pytest.mark.asyncio
async def test_wsingest_stop_is_idempotent():
    ing = WsIngest("127.0.0.1", 1, "")
    ing.start()
    await ing.stop()
    await ing.stop()


def test_registry_discovers_targets_from_vis_config_keys():
    cfg = {
        "servers": {
            "SIM": {"host": "127.0.0.1", "port": 8002, "live_vis": "wssim_panel"},
            "OER": {"host": "127.0.0.1", "port": 8003, "action_vis": "oersim_panel"},
            "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        }
    }
    reg = IngestRegistry(cfg)
    assert sorted(reg.targets()) == [("OER", "ws_data"), ("SIM", "ws_live")]


def test_registry_accepts_a_list_of_vis_modules_without_duplicating_targets():
    cfg = {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "live_vis": ["wssim_panel", "gpsim_panel"],
            }
        }
    }
    assert IngestRegistry(cfg).targets() == [("SIM", "ws_live")]


def test_registry_skips_servers_missing_host_or_port():
    cfg = {"servers": {"BAD": {"live_vis": "wssim_panel"}}}
    assert IngestRegistry(cfg).targets() == []


def test_registry_get_returns_none_for_unknown_target():
    reg = IngestRegistry({"servers": {}})
    assert reg.get("NOPE", "ws_live") is None
