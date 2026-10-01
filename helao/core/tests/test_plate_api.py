"""Plate API client: a 404 is "not found", an outage is "unavailable".

Nothing here touches the network: ``httpx.get`` is monkeypatched.
"""

import pickle
from types import SimpleNamespace

import httpx
import pytest

from helao.helpers import plate_api as plate_api_mod
from helao.helpers.plate_api import HTEPlateAPI, PlateAPIUnavailable

PLATE = 12345
SERIAL = 123455  # plate id + check digit (1+2+3+4+5) mod 10 = 5


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv("HELAO_CREDENTIALS", raising=False)
    a = HTEPlateAPI(env_file=None)
    a.loader = SimpleNamespace(  # type: ignore[assignment]
        hcred=SimpleNamespace(PLATE_API="http://plate.invalid", PLATE_API_KEY="k")
    )
    return a


def _respond(monkeypatch, status=200, body=None, raises=None, content=None):
    """Patch ``httpx.get`` to answer one canned response (or raise)."""

    def fake_get(url, **kwargs):
        if raises is not None:
            raise raises
        request = httpx.Request("GET", url)
        if content is not None:
            return httpx.Response(status, content=content, request=request)
        return httpx.Response(status, json=body, request=request)

    monkeypatch.setattr(plate_api_mod.httpx, "get", fake_get)


def test_get_info_200_returns_record(api, monkeypatch):
    rec = {"plate_id": PLATE, "serial_no": SERIAL}
    _respond(monkeypatch, 200, rec)
    assert api.get_info(PLATE) == rec


def test_get_info_404_returns_none(api, monkeypatch):
    _respond(monkeypatch, 404, {"detail": "Not Found"})
    assert api.get_info(PLATE) is None


def test_check_plateid_false_for_missing_live_id(api, monkeypatch):
    _respond(monkeypatch, 404, {"detail": "Not Found"})
    assert api.check_plateid(99999) is False


def test_check_plateid_false_for_a_serial(api, monkeypatch):
    # the incident's shape: a serial recorded where a plate id belongs
    _respond(monkeypatch, 404, {"detail": "Not Found"})
    assert api.check_plateid(SERIAL) is False


def test_legacy_id_reaches_legacy_api(api, monkeypatch):
    _respond(monkeypatch, 404, {"detail": "Not Found"})
    calls = []

    def fake_legacy(plateid):
        calls.append(plateid)
        return True

    monkeypatch.setattr(api.legacy_api, "check_plateid", fake_legacy)
    assert api.check_plateid(5) is True
    assert calls == [5]


_OUTAGES = [
    pytest.param({"raises": httpx.ConnectError("down")}, id="connect-error"),
    pytest.param({"status": 500, "body": {"detail": "boom"}}, id="http-500"),
    pytest.param({"status": 401, "body": {"detail": "no"}}, id="http-401"),
    pytest.param({"loader_none": True}, id="no-credentials"),
    pytest.param({"loader_no_plate_api": True}, id="loader-without-plate-api"),
    pytest.param(
        {"status": 200, "content": b"<html>gateway</html>"}, id="non-json-200"
    ),
]


@pytest.mark.parametrize("case", _OUTAGES)
def test_lookup_raises_unavailable(api, monkeypatch, case):
    if case.get("loader_none"):
        api.loader = None
    elif case.get("loader_no_plate_api"):
        api.loader = SimpleNamespace(hcred=SimpleNamespace())  # type: ignore[assignment]
    else:
        _respond(
            monkeypatch,
            case.get("status", 200),
            case.get("body"),
            case.get("raises"),
            case.get("content"),
        )
    with pytest.raises(PlateAPIUnavailable):
        api.lookup_plate(PLATE)
    assert api.get_info(PLATE) is None


def test_lookup_mismatched_plate_id_is_not_found(api, monkeypatch):
    _respond(monkeypatch, 200, {"plate_id": PLATE + 1})
    assert api.lookup_plate(PLATE) is None
    # the API may hand the id back as a string: still the same plate
    _respond(monkeypatch, 200, {"plate_id": str(PLATE)})
    assert api.lookup_plate(PLATE) == {"plate_id": str(PLATE)}


def test_printrecord_and_elements_on_404(api, monkeypatch):
    _respond(monkeypatch, 404, {"detail": "Not Found"})
    assert api.check_printrecord_plateid(99999) is False
    assert api.get_elements_plateid(99999) is None


def test_legacy_printrecord_false_not_none(api, monkeypatch):
    monkeypatch.setattr(api.legacy_api, "importinfo", lambda plateid: None)
    assert api.legacy_api.check_printrecord_plateid(5) is False
    assert api.legacy_api.check_annealrecord_plateid(5) is False


def test_unavailable_pickles():
    err = pickle.loads(pickle.dumps(PlateAPIUnavailable("HTTP 500")))
    assert isinstance(err, PlateAPIUnavailable)
    assert str(err) == "HTTP 500"
