# helao/core/tests/test_composition_api.py
"""The metadata-API layer, against a stub client. No test here hits the network.

The response shapes are transcribed from real calls against the production API
for plate 10244 on 2026-09-22.
"""

import asyncio

import pytest

from helao.ui.shared.composition import api


@pytest.fixture(autouse=True)
def _reset_quant_cache():
    """Every test gets an empty quant cache: two tests below use the same
    ``(action_uuid, file_name)`` key, and an entry surviving from an earlier
    test would make a later one stop issuing the request it asserts on."""
    api.reset_quant_cache()
    yield
    api.reset_quant_cache()


class StubClient:
    """Records calls and replays canned responses."""

    def __init__(self, search=None, raw=None, plottable=None, action=None):
        self.calls = []
        self._search = list(search or [])
        self._raw = raw or {}
        self._plottable = plottable or {}
        self._action = action or {"action_name": "run_XRF"}

    async def search(self, request_body=None, **kwargs):
        self.calls.append(("search", request_body))
        return self._search.pop(0)

    async def read_raw_data(self, request_body=None, **kwargs):
        self.calls.append(("read_raw_data", request_body))
        key = (request_body or {}).get("key")
        if key not in self._raw:
            raise RuntimeError(f"404 for {key}")
        return self._raw[key]

    async def read_plottable_data(self, request_body=None, **kwargs):
        self.calls.append(("read_plottable_data", request_body))
        return self._plottable

    async def read_action(self, action_uuid=None, **kwargs):
        self.calls.append(("read_action", action_uuid))
        return self._action


def run(coro):
    return asyncio.run(coro)


def test_search_processes_filters_on_the_numeric_plate_id() -> None:
    """Not on a source_csv_label prefix: the filter Operation enum has no
    `like`, and plate_id is an exact match that needs no label convention."""
    client = StubClient(search=[{"total": 1, "items": [{"process_uuid": "a"}]}])
    run(api.search_processes(client, 10244))
    _, body = client.calls[0]
    assert {
        "field": "process_params.plate_id",
        "operation": "eq",
        "value": 10244,
    } in body["filters"]
    assert {
        "field": "entity_type",
        "operation": "in",
        "value": ["PROCESS"],
    } in body["filters"]


def test_search_processes_pages_until_total() -> None:
    """A plate with more processes than one page must not silently truncate."""
    client = StubClient(
        search=[
            {"total": 3, "items": [{"process_uuid": "a"}, {"process_uuid": "b"}]},
            {"total": 3, "items": [{"process_uuid": "c"}]},
        ]
    )
    items = run(api.search_processes(client, 10244, size=2))
    assert [i["process_uuid"] for i in items] == ["a", "b", "c"]
    assert [body["page"] for _, body in client.calls] == [1, 2]


def test_search_processes_stops_on_an_empty_page() -> None:
    """A total the server cannot actually deliver must not spin forever."""
    client = StubClient(
        search=[
            {"total": 99, "items": [{"process_uuid": "a"}]},
            {"total": 99, "items": []},
        ]
    )
    items = run(api.search_processes(client, 10244, size=1))
    assert len(items) == 1


def test_fetch_sequences_keys_by_uuid() -> None:
    client = StubClient(
        search=[
            {
                "total": 1,
                "items": [
                    {"sequence_uuid": "u1", "sequence_timestamp": "2026-08-13T11:54:21"}
                ],
            }
        ]
    )
    out = run(api.fetch_sequences(client, ["u1"]))
    assert out["u1"]["sequence_timestamp"] == "2026-08-13T11:54:21"


def test_fetch_sequences_on_an_empty_list_makes_no_request() -> None:
    client = StubClient()
    assert run(api.fetch_sequences(client, [])) == {}
    assert client.calls == []


def test_fetch_quant_derives_the_s3_key() -> None:
    """One request per process rather than two. The metadata endpoint returns
    exactly this key, verified against the production API."""
    client = StubClient(
        raw={
            "raw_data/act-1/quant.hlo.json": {
                "data": {"data": {"transition": ["Co.K"]}}
            }
        }
    )
    out = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert out["transition"] == ["Co.K"]
    assert client.calls[0][1] == {"key": "raw_data/act-1/quant.hlo.json"}


def test_fetch_quant_falls_back_to_the_metadata_endpoint(monkeypatch) -> None:
    """OpenAPIClient cannot reach POST /api/file/metadata -- its name collides
    with the output-file GET and the GET wins -- so the fallback is httpx."""
    client = StubClient(
        raw={"other/key.json": {"data": {"data": {"transition": ["Y.K"]}}}}
    )

    async def fake_lookup(action_uuid, file_name):
        assert (action_uuid, file_name) == ("act-1", "quant.hlo.json")
        return "other/key.json"

    monkeypatch.setattr(api, "_lookup_key", fake_lookup)
    out = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert out["transition"] == ["Y.K"]


def test_fetch_quant_caches_by_action_and_file_and_issues_no_second_request() -> None:
    """A second Retrieve for the same plate must not re-issue ~499 requests --
    the cost this cache removes. Re-grouping and re-selecting a unit are
    already free without it, since `plot()` reads `_records` out of state and
    does no I/O; only a repeat Retrieve regresses."""
    client = StubClient(
        raw={
            "raw_data/act-1/quant.hlo.json": {
                "data": {"data": {"transition": ["Co.K"]}}
            }
        }
    )
    first = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert first["transition"] == ["Co.K"]
    assert len(client.calls) == 1

    second = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert second["transition"] == ["Co.K"]
    assert len(client.calls) == 1, "a cache hit must not issue another request"


def test_fetch_spectrum_asks_the_action_for_its_name() -> None:
    """action_name is required by /file/plottable-data and is not on the
    process record."""
    client = StubClient(
        plottable={
            "plot_type": "line",
            "data": {"series": {"ev": [0, 10], "intensity": [1.0, 2.0]}},
        },
        action={"action_name": "run_XRF"},
    )
    out = run(api.fetch_spectrum(client, "act-1", "spec.hlo.json"))
    assert out["ev"] == [0, 10]
    assert ("read_action", "act-1") in client.calls
    _, body = [c for c in client.calls if c[0] == "read_plottable_data"][0]
    assert body["action_name"] == "run_XRF"
    assert body["file_type"] == "xrfspec_helao__json_file"


def test_fetch_spectrum_on_a_response_with_no_series() -> None:
    client = StubClient(plottable={"plot_type": "table", "data": None})
    assert run(api.fetch_spectrum(client, "act-1", "spec.hlo.json")) == {}
