"""Tests for helao.helpers.openapi_client.

Uses httpx.MockTransport injected into the clients' internally-created
httpx.Client / httpx.AsyncClient, so no network or live server is required.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest

from helao.helpers.openapi_client import AsyncOpenAPIClient, OpenAPIClient

SPEC = {
    "openapi": "3.0.0",
    "servers": [{"url": "/"}],
    "paths": {
        "/items/{item_id}": {
            "get": {
                "operationId": "get_item",
                "summary": "Get Item",
                "description": "Fetch one item.",
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "q",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "The requested item."}},
            }
        },
        "/items": {
            "post": {
                "operationId": "create_item",
                "summary": "Create Item",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {"201": {"description": "Created item."}},
            }
        },
        "/boom": {"get": {"operationId": "boom", "summary": "Boom", "responses": {}}},
        # A delete shaped like the metadata API's ``delete_command``: path params
        # plus an optional query flag, declared security, and no request body.
        "/command/{entity_type}/{primary_id}": {
            "delete": {
                "operationId": "delete_command",
                "summary": "Delete Command",
                "security": [{"APIKeyHeader": []}],
                "parameters": [
                    {
                        "name": "entity_type",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "primary_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "delete_connected_processes",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "boolean"},
                    },
                ],
                "responses": {"200": {"description": "Acknowledged."}},
            }
        },
    },
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/openapi.json"):
        return httpx.Response(200, json=SPEC)
    if path == "/boom":
        return httpx.Response(500, json={"detail": "kaboom"})
    if request.method == "GET" and path.startswith("/items/"):
        item_id = path.rsplit("/", 1)[-1]
        return httpx.Response(
            200, json={"item_id": item_id, "q": dict(request.url.params).get("q")}
        )
    if request.method == "POST" and path == "/items":
        body = json.loads(request.content or b"{}")
        return httpx.Response(201, json={"created": body})
    if request.method == "DELETE" and path.startswith("/command/"):
        entity_type, primary_id = path.split("/")[2:4]
        return httpx.Response(
            200,
            json={
                "deleted": entity_type,
                "id": primary_id,
                "flag": dict(request.url.params).get("delete_connected_processes"),
                # A DELETE must not carry a body.
                "had_body": bool(request.content),
            },
        )
    return httpx.Response(404, json={"detail": "nope"})


URL = "http://testhost/openapi.json"


@pytest.fixture(autouse=True)
def _mock_transport(monkeypatch):
    """Route the clients' internally-created httpx clients through MockTransport."""
    orig_client, orig_async = httpx.Client, httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(_handler))
        return orig_client(*args, **kwargs)

    def patched_async(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(_handler))
        return orig_async(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)
    monkeypatch.setattr(httpx, "AsyncClient", patched_async)


def test_sync():
    client: Any = OpenAPIClient(URL)
    assert client.get_item(item_id=5, q="hello") == {"item_id": "5", "q": "hello"}
    assert client.create_item(request_body={"name": "x"}) == {"created": {"name": "x"}}
    with pytest.raises(ValueError):
        client.get_item(q="hello")
    with pytest.raises(ValueError):
        client.create_item()
    with pytest.raises(RuntimeError):
        client.boom()
    assert "Get Item" in (client.get_item.__doc__ or "")
    assert client.delete_command(
        entity_type="SEQUENCE", primary_id="abc-123", delete_connected_processes=True
    ) == {"deleted": "SEQUENCE", "id": "abc-123", "flag": "true", "had_body": False}
    with pytest.raises(ValueError):
        client.delete_command(entity_type="SEQUENCE")
    client.close()


def test_async():
    async def run():
        client: Any = AsyncOpenAPIClient(URL)
        assert await client.get_item(item_id=5, q="hello") == {
            "item_id": "5",
            "q": "hello",
        }
        assert await client.create_item(request_body={"name": "x"}) == {
            "created": {"name": "x"}
        }
        assert await client.delete_command(
            entity_type="SEQUENCE", primary_id="abc-123"
        ) == {"deleted": "SEQUENCE", "id": "abc-123", "flag": None, "had_body": False}
        client.close()

    asyncio.run(run())
