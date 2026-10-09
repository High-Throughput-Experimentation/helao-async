"""``yml_finisher`` posts without parsing the yml.

It used to ``yml_load`` the whole file only to name its type in a log line. A
9.7 MB XRFS ``-seq.yml`` took ~25 s to load, synchronously, so every finish
stalled the caller's event loop before the POST was even sent.
"""

import asyncio

from helao.helpers import yml_tools


class _Resp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    posts: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, params):
        _Session.posts.append((url, params))
        return _Resp()


def test_finisher_posts_without_loading_the_yml(tmp_path, monkeypatch):
    yml = tmp_path / "260922.115221000000-seq.yml"
    yml.write_text("{{{ not yaml", encoding="utf-8")

    def no_load(*args, **kwargs):
        raise AssertionError("yml_finisher must not parse the yml")

    monkeypatch.setattr(yml_tools, "yml_load", no_load)
    monkeypatch.setattr(yml_tools.aiohttp, "ClientSession", _Session)
    _Session.posts = []

    sync_cfg = {"host": "localhost", "port": 8010}
    assert asyncio.run(yml_tools.yml_finisher(str(yml), sync_cfg)) is True
    assert _Session.posts == [
        ("http://localhost:8010/finish_yml", {"yml_path": str(yml)})
    ]
