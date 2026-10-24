"""``spec_server``: the host connects the SM303; a raising connect keeps the server up.

The server no longer connects in its ``dyn_endpoints``. If the host's startup connect
raises (no DLL, no device), startup still completes, the failure is logged at ERROR,
and the routes register against the disconnected driver.
"""

from helao.deploy.hte.drivers.spec.spectral_products_driver import SM303
from helao.hexagon.tests.hosted_server import start_with_raising_connect


def test_a_raising_connect_keeps_the_server_up(monkeypatch, tmp_path, caplog):
    out = start_with_raising_connect(
        monkeypatch,
        tmp_path,
        caplog,
        module="spec_server",
        prefix="eche10",
        server_key="SPEC_T",
        driver_class=SM303,
        ready=lambda app: any(
            getattr(r, "path", "").endswith("/acquire_spec") for r in app.routes
        ),
    )
    assert len(out.startup_errors) == 1
    assert "SM303" in out.startup_errors[0].getMessage()
    assert out.get_status_code == 200
    assert any(p.endswith("/acquire_spec") for p in out.route_paths if p)
