"""UiHostPort contract tests (P7d).

Linux, no Bokeh/Reflex required: the port itself must be vendor-free (the
ports import ban, test_boundaries.py:78-82) and a fake must satisfy it and
round-trip a handle through start/stop. The real adapter
(``app/ui_host.py``, which DOES construct a real Bokeh ``Server``) has its
own test module, ``test_app_ui_host.py``.
"""

import ast
import inspect

import helao.hexagon.ports.ui_host as ui_host_mod
from helao.hexagon.ports.ui_host import UiHostPort


class _FakeUiHost:
    """Stands in for BokehServerUiHost/a future Reflex adapter -- proves the
    Protocol is satisfiable without ever importing bokeh or reflex."""

    def __init__(self):
        self.started: list[tuple] = []
        self.stopped: list[object] = []

    def start_document_host(self, routes, host, port, allow_websocket_origin=None):
        handle = object()
        self.started.append((routes, host, port, allow_websocket_origin, handle))
        return handle

    def stop(self, handle):
        self.stopped.append(handle)

    def build_ui_app(self, config):
        return object()


def test_fake_satisfies_ui_host_port():
    assert isinstance(_FakeUiHost(), UiHostPort)


def test_start_and_stop_round_trip_an_opaque_handle():
    host = _FakeUiHost()
    routes = {"/Aligner": lambda doc: doc}
    handle = host.start_document_host(routes, host="127.0.0.1", port=12345)
    assert handle is not None
    host.stop(handle)
    assert host.stopped == [handle]
    _, seen_host, seen_port, seen_origin, seen_handle = host.started[0]
    assert (seen_host, seen_port, seen_origin, seen_handle) == (
        "127.0.0.1",
        12345,
        None,
        handle,
    )


def test_build_ui_app_returns_an_opaque_object():
    host = _FakeUiHost()
    result = host.build_ui_app({"some": "config"})
    assert result is not None


def test_port_module_has_no_vendor_imports():
    """Ports import ban (test_boundaries.py:78-82): no import statement in
    this module may name bokeh or reflex."""
    tree = ast.parse(inspect.getsource(ui_host_mod))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    for module in names:
        top = module.split(".")[0]
        assert top not in ("bokeh", "reflex"), f"{module!r} leaked into ui_host port"


def test_port_annotations_return_object_not_a_vendor_type():
    """Every UiHostPort member returns `object` -- an opaque handle, not a
    bokeh.server.server.Server or a Reflex App -- so the port seam never
    leaks a vendor type into ports/ or domain/."""
    for name in ("start_document_host", "build_ui_app"):
        method = getattr(UiHostPort, name)
        assert method.__annotations__.get("return") is object, name
