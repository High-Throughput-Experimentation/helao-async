"""Info-box builders for graph nodes (spec: Info box)."""

from helao.ui.reflex.node_info import config_info, endpoint_rows, server_info
from helao.ui.shared.mask import MASK

STATUS = {
    "estop": False,
    "_driver_status": "ok",
    "endpoints": {
        "acquire_data": {
            "active_dict": {
                "u1": {
                    "action_name": "acquire_data",
                    "action_uuid": "u1",
                    "action_timestamp": "2026-11-16 10:00:00",
                }
            },
            "nonactive_dict": {},
        },
        "wait": {
            "active_dict": {},
            "nonactive_dict": {
                "finished": {
                    "u2": {"action_finished_timestamp": "2026-11-16 09:00:00"}
                },
                "errored": {"u3": {"action_finished_timestamp": "2026-11-16 09:30:00"}},
            },
        },
        "never": {"active_dict": {}, "nonactive_dict": {}},
    },
}


def test_endpoint_rows_counts_and_statuses():
    rows = {r["name"]: r for r in endpoint_rows(STATUS)}
    assert rows["acquire_data"]["status"] == "busy"
    assert rows["acquire_data"]["non_idle"] == 1
    assert rows["acquire_data"]["active"] == [
        {"name": "acquire_data", "uuid": "u1", "start": "2026-11-16 10:00:00"}
    ]
    assert rows["wait"]["status"] == "errored" and rows["wait"]["non_idle"] == 0
    assert rows["never"]["status"] == "idle"


def test_estop_overrides_every_endpoint():
    rows = endpoint_rows({**STATUS, "estop": True})
    assert {r["status"] for r in rows} == {"estop"}


def test_server_info_masks_config_and_labels_rows():
    info = server_info({"host": "h", "params": {"api_key": "k"}}, STATUS)
    assert info["config"]["params"]["api_key"] == MASK
    assert info["driver_status"] == "ok"
    assert "acquire_data — busy, 1 non-idle" in info["endpoints"]


def test_server_info_without_status():
    info = server_info({"host": "h"}, None)
    assert info["endpoints"] == "unavailable"


def test_config_info_masks():
    assert config_info({"token": "t", "port": 1}) == {
        "config": {"token": MASK, "port": 1}
    }
