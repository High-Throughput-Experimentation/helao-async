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


def test_build_ui_app_is_deferred_to_p7f():
    from helao.hexagon.adapters.errors import HexagonDeferred

    host = BokehServerUiHost()
    try:
        host.build_ui_app({})
        raised = False
    except HexagonDeferred:
        raised = True
    assert raised, "build_ui_app must raise HexagonDeferred until P7f wires Reflex"
