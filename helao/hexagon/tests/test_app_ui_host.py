"""BokehServerUiHost tests (P7d): the one place in helao/hexagon that
constructs ``bokeh.server.server.Server`` directly (test_boundaries.py's
bokeh.server-outside-app/ rule). Starts a real ``Server`` on an ephemeral
port, serves a trivial document, and stops cleanly -- proving the fold-in
actually works, not just that the boundary rule is satisfied on paper.
"""

import socket

from helao.hexagon.app.ui_host import BokehServerUiHost
from helao.hexagon.ports.ui_host import UiHostPort


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _trivial_doc(doc):
    from bokeh.models import Div

    doc.add_root(Div(text="P7d ui_host smoke doc"))


def test_bokeh_server_ui_host_satisfies_the_port():
    assert isinstance(BokehServerUiHost(), UiHostPort)


def test_start_serves_a_document_and_stop_cleans_up():
    host = BokehServerUiHost()
    port = _free_port()
    handle = host.start_document_host(
        {"/Aligner": _trivial_doc}, host="127.0.0.1", port=port
    )
    try:
        # the returned handle is opaque to the caller (GalilAlignerHost
        # never inspects it) -- this test only proves the SERVER side is
        # real by connecting a plain socket to the port it claimed
        sock = socket.socket()
        sock.settimeout(2)
        sock.connect(("127.0.0.1", port))
        sock.close()
    finally:
        host.stop(handle)


def test_document_factory_can_start_asyncio_tasks():
    """Bokeh 3.10 builds FunctionHandler documents in a worker thread; helao
    factories call asyncio.create_task (WsSubscriber, operator backend), so
    the host must run them on the server loop or every page 500s."""
    import asyncio

    from tornado.httpclient import AsyncHTTPClient

    ran = []

    def _task_doc(doc):
        ran.append(asyncio.create_task(asyncio.sleep(0)))
        _trivial_doc(doc)

    host = BokehServerUiHost()
    port = _free_port()
    handle = host.start_document_host(
        {"/Aligner": _task_doc}, host="127.0.0.1", port=port
    )
    try:
        resp = handle.io_loop.run_sync(  # type: ignore[attr-defined]
            lambda: AsyncHTTPClient().fetch(
                f"http://127.0.0.1:{port}/Aligner", raise_error=False
            ),
            timeout=10,
        )
        assert resp.code == 200
        assert ran
    finally:
        host.stop(handle)
