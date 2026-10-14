"""NetbooterDriver against a local stub of the Netbooter ``cmd.cgi`` interface.

The stub speaks the documented contract (Synaccess HTTP API): basic auth in the
header, HTTP 200 with a ``$A0`` body on success and ``$AF`` on failure.
"""

import base64
import http.server
import threading

import pytest

from helao.core.drivers.helao_driver import DriverResponseType
from helao.deploy.hte.drivers.io.synaccess.driver import NetbooterDriver

AUTH = "Basic " + base64.b64encode(b"admin:secret").decode()


class Stub:
    """Scripted replies; ``"drop"`` closes the socket without answering."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                stub.requests.append((self.path, self.headers.get("Authorization")))
                reply = stub.replies.pop(0) if stub.replies else "$A0"
                if reply == "drop":
                    self.close_connection = True
                    self.connection.close()
                    return
                if self.headers.get("Authorization") != AUTH:
                    status, body = 401, b"unauthorized"
                else:
                    status, body = 200, reply.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def driver(self, password="secret"):
        return NetbooterDriver(
            config={
                "hostname": f"127.0.0.1:{self.server.server_port}",
                "username": "admin",
                "password": password,
                "retry_delay": 0.0,
            }
        )


@pytest.fixture
def make_stub():
    stubs = []

    def _make(replies=()):
        stubs.append(Stub(replies))
        return stubs[-1]

    yield _make
    for s in stubs:
        s.server.shutdown()


def test_switch_outlet_sends_auth_and_documented_command(make_stub):
    stub = make_stub()
    resp = stub.driver().switch_outlet(3, True)
    assert resp.response == DriverResponseType.success
    assert stub.requests == [("/cmd.cgi?$A3%203%201", AUTH)]


def test_af_body_is_failure(make_stub):
    stub = make_stub(["$AF"] * 5)
    resp = stub.driver().switch_all(False, repeat=2)
    assert resp.response == DriverResponseType.failed
    assert "$AF" in resp.message
    assert len(stub.requests) == 2


def test_dropped_connection_is_retried(make_stub):
    stub = make_stub(["drop", "$A0"])
    resp = stub.driver().switch_all(True)
    assert resp.response == DriverResponseType.success
    assert len(stub.requests) == 2


def test_bad_credentials_fail(make_stub):
    stub = make_stub()
    resp = stub.driver(password="wrong").switch_outlet(1, False, repeat=1)
    assert resp.response == DriverResponseType.failed
    assert "401" in resp.message


def test_missing_config_fails_instead_of_raising():
    resp = NetbooterDriver(config={}).switch_outlet(1, True)
    assert resp.response == DriverResponseType.failed


def _env_driver(stub, **extra):
    cfg = {
        "hostname": f"127.0.0.1:{stub.server.server_port}",
        "username": "admin",
        "retry_delay": 0.0,
    }
    cfg.update(extra)
    return NetbooterDriver(config=cfg)


@pytest.fixture
def captured_logs(caplog):
    """Route the driver's (possibly non-propagating) logger into caplog."""
    from helao.deploy.hte.drivers.io.synaccess import driver as mod

    caplog.set_level(0)
    mod.LOGGER.addHandler(caplog.handler)
    yield caplog
    mod.LOGGER.removeHandler(caplog.handler)


def test_password_read_from_named_env_var(make_stub, monkeypatch, captured_logs):
    monkeypatch.setenv("TEST_PDU_PW", "secret")
    stub = make_stub()
    resp = _env_driver(stub, password_env="TEST_PDU_PW").switch_outlet(3, True)
    assert resp.response == DriverResponseType.success
    assert stub.requests == [("/cmd.cgi?$A3%203%201", AUTH)]
    assert "secret" not in captured_logs.text
    assert "secret" not in resp.message


def test_env_sourced_bad_credentials_do_not_leak(make_stub, monkeypatch, captured_logs):
    monkeypatch.setenv("TEST_PDU_PW", "hunter2-wrong")
    stub = make_stub()
    drv = _env_driver(stub, password_env="TEST_PDU_PW")
    resp = drv.switch_outlet(1, False, repeat=1)
    assert resp.response == DriverResponseType.failed
    assert "401" in resp.message
    assert "hunter2-wrong" not in captured_logs.text
    assert "hunter2-wrong" not in resp.message


def test_explicit_password_beats_env(make_stub, monkeypatch):
    monkeypatch.setenv("TEST_PDU_PW", "from-env")
    stub = make_stub()
    drv = _env_driver(stub, password="secret", password_env="TEST_PDU_PW")
    assert drv.switch_outlet(3, True).response == DriverResponseType.success
    assert stub.requests[0][1] == AUTH


@pytest.mark.parametrize("value", [None, ""])
def test_named_but_unset_env_is_unconfigured_and_logged(make_stub, monkeypatch, value):
    from helao.deploy.hte.drivers.io.synaccess import driver as mod

    if value is None:
        monkeypatch.delenv("TEST_PDU_PW", raising=False)
    else:
        monkeypatch.setenv("TEST_PDU_PW", value)
    errors = []
    monkeypatch.setattr(mod.LOGGER, "error", lambda msg, *a, **k: errors.append(msg))
    stub = make_stub()
    drv = _env_driver(stub, password_env="TEST_PDU_PW")
    assert drv.client is None
    assert drv.switch_outlet(1, True).response == DriverResponseType.failed
    assert stub.requests == []
    assert any("TEST_PDU_PW" in m for m in errors)
