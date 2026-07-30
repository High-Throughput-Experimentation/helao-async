"""Standalone tests for helao.helpers.openapi_client.

Run: python helao/core/tests/openapi_client_test.py

No pytest dependency. Uses httpx.MockTransport injected into the clients'
internally-created httpx.Client / httpx.AsyncClient via monkeypatching, so no
network or live server is required.
"""

import asyncio
import contextlib
import io
import json

import httpx

from helao.helpers.openapi_client import AsyncOpenAPIClient, OpenAPIClient
from helao.helpers.openapi_pagination import CursorPagination

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
        "/things": {
            "get": {
                "operationId": "list_things",
                "summary": "List Things",
                "responses": {"200": {"description": "A page of things."}},
            }
        },
        "/loop": {
            "get": {
                "operationId": "list_loop",
                "summary": "List Loop",
                "responses": {"200": {"description": "Never-ending page."}},
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
    if request.method == "GET" and path == "/things":
        cursor = int(dict(request.url.params).get("cursor", 0))
        page = list(range(cursor, min(cursor + 10, 25)))
        nxt = cursor + 10
        return httpx.Response(
            200,
            json={"items": page, "next_cursor": str(nxt) if nxt < 25 else None},
        )
    if request.method == "GET" and path == "/loop":
        return httpx.Response(200, json={"items": [1], "next_cursor": "x"})
    return httpx.Response(404, json={"detail": "nope"})


def _install_mock_transport():
    """Patch httpx.Client / httpx.AsyncClient to use a MockTransport.

    Returns a restore() callable.
    """
    orig_client = httpx.Client
    orig_async = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(_handler))
        return orig_client(*args, **kwargs)

    def patched_async(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(_handler))
        return orig_async(*args, **kwargs)

    httpx.Client = patched_client
    httpx.AsyncClient = patched_async

    def restore():
        httpx.Client = orig_client
        httpx.AsyncClient = orig_async

    return restore


URL = "http://testhost/openapi.json"

_failures = []


@contextlib.contextmanager
def capture_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def check(cond, msg):
    if cond:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        _failures.append(msg)


def expect_raises(exc_type, fn, msg):
    try:
        fn()
    except exc_type:
        print(f"  PASS: {msg}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {msg} (raised {type(e).__name__}, not {exc_type.__name__})")
        _failures.append(msg)
        return
    print(f"  FAIL: {msg} (no exception)")
    _failures.append(msg)


def test_sync():
    print("test_sync")
    client = OpenAPIClient(URL)
    check(
        client.get_item(item_id=5, q="hello") == {"item_id": "5", "q": "hello"},
        "sync GET resolves path param + query",
    )
    check(
        client.create_item(request_body={"name": "x"}) == {"created": {"name": "x"}},
        "sync POST sends request_body",
    )
    expect_raises(
        ValueError,
        lambda: client.get_item(q="hello"),
        "sync missing required path param raises ValueError",
    )
    expect_raises(
        ValueError,
        lambda: client.create_item(),
        "sync missing required request_body raises ValueError",
    )
    expect_raises(
        RuntimeError, lambda: client.boom(), "sync 500 response raises RuntimeError"
    )
    check(
        "Get Item" in (client.get_item.__doc__ or ""),
        "sync method has generated docstring from summary",
    )
    check(
        "limit (" in (client.get_item.__doc__ or ""),
        "generated docstring documents the limit parameter",
    )
    client.close()


def test_async():
    print("test_async")

    async def run():
        client = AsyncOpenAPIClient(URL)
        r1 = await client.get_item(item_id=5, q="hello")
        check(
            r1 == {"item_id": "5", "q": "hello"},
            "async GET resolves path param + query",
        )
        r2 = await client.create_item(request_body={"name": "x"})
        check(r2 == {"created": {"name": "x"}}, "async POST sends request_body")
        check(
            "Get Item" in (client.get_item.__doc__ or ""),
            "async method has generated docstring from summary",
        )
        client.close()

    asyncio.run(run())


def test_sync_pagination():
    print("test_sync_pagination")
    client = OpenAPIClient(URL, pagination=CursorPagination())
    with capture_stdout() as out:
        res = client.list_things()  # default limit=100, fewer than cap
    check(res == list(range(25)), "sync default limit returns all 25 items")
    check(
        "Pagination detected for 'list_things'" in out.getvalue(),
        "sync prints pagination-detected message",
    )

    with capture_stdout() as out:
        res = client.list_things(limit=15)
    check(res == list(range(15)), "sync limit=15 caps to 15 items")
    check(
        "Reached limit=15 for 'list_things'" in out.getvalue(),
        "sync prints more-results-available message at cap",
    )

    with capture_stdout():
        res = client.list_things(limit=None)
    check(res == list(range(25)), "sync limit=None fetches all items")

    with capture_stdout():
        res = client.list_loop(limit=None)
    check(res == [1, 1], "sync constant-cursor loop terminates via repeat guard")

    plain = OpenAPIClient(URL)
    res = plain.list_things()
    check(
        res == {"items": list(range(10)), "next_cursor": "10"},
        "sync no-strategy returns raw first page",
    )
    plain.close()
    client.close()


def test_async_pagination():
    print("test_async_pagination")

    async def run():
        client = AsyncOpenAPIClient(URL, pagination=CursorPagination())
        with capture_stdout() as out:
            res = await client.list_things()
        check(res == list(range(25)), "async default limit returns all 25 items")
        check(
            "Pagination detected for 'list_things'" in out.getvalue(),
            "async prints pagination-detected message",
        )

        with capture_stdout() as out:
            res = await client.list_things(limit=15)
        check(res == list(range(15)), "async limit=15 caps to 15 items")
        check(
            "Reached limit=15 for 'list_things'" in out.getvalue(),
            "async prints more-results-available message at cap",
        )

        res = await client.list_things(limit=None)
        check(res == list(range(25)), "async limit=None fetches all items")
        client.close()

    asyncio.run(run())


def main():
    restore = _install_mock_transport()
    try:
        test_sync()
        test_async()
        test_sync_pagination()
        test_async_pagination()
    finally:
        restore()
    if _failures:
        print(f"\n{len(_failures)} FAILED")
        raise SystemExit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
