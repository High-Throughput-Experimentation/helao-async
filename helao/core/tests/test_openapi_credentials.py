"""Metadata-API auth: ``OPENAPI_KEY`` goes out as ``X-Api-Key``, like ``PLATE_API_KEY``.

No test here hits the network.
"""

import asyncio

import httpx
import pytest

from helao.core.models.credentials import DEFAULT_OPENAPI_JSON, HelaoCredentials
from helao.helpers import openapi_client
from helao.ui.shared.composition import api

SPEC = "https://meta.test/api/openapi.json"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / "creds.env"
    path.write_text(
        f"OPENAPI_JSON={SPEC}\nOPENAPI_KEY=k123\nOPENAPI=https://base.test/api\n"
        "PLATE_API_KEY=p\nPLATE_API=https://plate.test\n"
    )
    monkeypatch.setenv("HELAO_CREDENTIALS", str(path))
    for key in ("OPENAPI_JSON", "OPENAPI_KEY", "OPENAPI"):
        monkeypatch.delenv(key, raising=False)
    api.reset_client()
    yield path
    api.reset_client()


def test_credentials_accept_openapi_keys(env_file):
    hcred = HelaoCredentials(_env_file=env_file)
    assert hcred.openapi_json_url == SPEC
    assert hcred.openapi_base_url == "https://base.test/api"
    assert hcred.openapi_headers == {"X-Api-Key": "k123"}


def test_base_url_ignores_spec_location(tmp_path):
    path = tmp_path / "c.env"
    path.write_text("OPENAPI_JSON=https://meta.test/openapi.json\n")
    assert HelaoCredentials(_env_file=path).openapi_base_url == "https://meta.test/api"


def test_credentials_defaults(tmp_path, monkeypatch):
    for key in ("OPENAPI_JSON", "OPENAPI_KEY", "OPENAPI"):
        monkeypatch.delenv(key, raising=False)
    hcred = HelaoCredentials(_env_file=tmp_path / "missing.env")
    assert hcred.openapi_json_url == DEFAULT_OPENAPI_JSON
    assert hcred.openapi_base_url == "https://helao-api.caltech-hte.modelyst.com/api"
    assert hcred.openapi_headers == {}


def test_composition_client_gets_key(env_file, monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, url, api_key=""):
            seen.update(url=url, api_key=api_key)

    monkeypatch.setattr(openapi_client, "AsyncOpenAPIClient", FakeClient)
    api.get_client()
    assert seen == {"url": SPEC, "api_key": "k123"}


def test_lookup_key_sends_header(env_file, monkeypatch):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers.get("x-api-key"))
        return httpx.Response(200, json={"file_name": "raw_data/u/f.hlo"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    assert asyncio.run(api._lookup_key("u", "f.hlo")) == "raw_data/u/f.hlo"
    assert seen == {"url": "https://base.test/api/file/metadata", "key": "k123"}
