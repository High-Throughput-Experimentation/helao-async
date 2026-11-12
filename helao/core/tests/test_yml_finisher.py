"""``yml_finisher`` posts without parsing the yml.

It used to ``yml_load`` the whole file only to name its type in a log line. A
9.7 MB XRFS ``-seq.yml`` took ~25 s to load, synchronously, so every finish
stalled the caller's event loop before the POST was even sent.
"""

import asyncio

import httpx

from helao.helpers import yml_tools


def _recording_client(posts):
    """An ``httpx.AsyncClient`` factory that records each POST and answers 200."""
    real = httpx.AsyncClient

    def _handler(request):
        posts.append((str(request.url.copy_with(query=None)), dict(request.url.params)))
        return httpx.Response(200)

    def _client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(_handler), **kwargs)

    return _client


def test_finisher_posts_without_loading_the_yml(tmp_path, monkeypatch):
    yml = tmp_path / "260922.115221000000-seq.yml"
    yml.write_text("{{{ not yaml", encoding="utf-8")

    def no_load(*args, **kwargs):
        raise AssertionError("yml_finisher must not parse the yml")

    monkeypatch.setattr(yml_tools, "yml_load", no_load)
    posts: list = []
    monkeypatch.setattr(httpx, "AsyncClient", _recording_client(posts))

    sync_cfg = {"host": "localhost", "port": 8010}
    assert asyncio.run(yml_tools.yml_finisher(str(yml), sync_cfg)) is True
    assert posts == [("http://localhost:8010/finish_yml", {"yml_path": str(yml)})]


def _client_with(handler):
    real = httpx.AsyncClient

    def _client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    return _client


async def _no_sleep(_s):
    return None


def test_finisher_retries_a_non_200_and_a_timeout(tmp_path, monkeypatch):
    yml = tmp_path / "260922.115221000000-seq.yml"
    yml.write_text("x", encoding="utf-8")
    replies = iter(["timeout", 503, 200])

    def _handler(request):
        r = next(replies)
        if r == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(r)

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(_handler))
    monkeypatch.setattr(yml_tools.asyncio, "sleep", _no_sleep)
    sync_cfg = {"host": "localhost", "port": 8010}
    assert asyncio.run(yml_tools.yml_finisher(str(yml), sync_cfg, retry=3)) is True


def test_finisher_lets_a_connect_error_reach_the_caller(tmp_path, monkeypatch):
    """micro_orch catches it; swallowing it here would hide an unreachable SYNC."""
    import pytest

    yml = tmp_path / "260922.115221000000-seq.yml"
    yml.write_text("x", encoding="utf-8")

    def _handler(request):
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(_handler))
    with pytest.raises(httpx.ConnectError):
        asyncio.run(
            yml_tools.yml_finisher(str(yml), {"host": "localhost", "port": 8010})
        )
