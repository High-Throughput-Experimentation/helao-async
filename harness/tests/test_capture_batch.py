"""Batch-conversion capture scenario: staging, submission, and the quiesce probe.

The scenario family exists for Deployment-C, whose action server converts
third-party instrument exports dropped into per-family folders. Two properties
are what these tests exist to pin:

  1. Submission goes through ``/run_directory`` on an explicit path, never the
     filesystem watchdog, whose settle heuristics make a capture
     non-deterministic.
  2. The quiesce predicate is NON-VACUOUS: it must be observed false at least
     once while a conversion is in flight. A predicate that is true on its very
     first poll proves nothing -- it would snapshot a half-written tree (or an
     empty one, when the submission silently errored) and no other check in the
     rig would notice.

The fake server below answers the same three quiesce routes the real servers
do, with the response shapes read off the live code, so the predicate is
exercised end to end without a launched group.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from harness.capture import (
    DEFAULT_ROLE_KEYS,
    CaptureEndpoints,
    Endpoint,
    QuiesceObservation,
    UnsafeDropDirError,
    VacuousQuiesceError,
    batch_quiesced,
    make_batch_scenario,
    observe_quiesce,
    stage_fixture,
)


# --- fake batch + db server -------------------------------------------------
class FakeGroup:
    """One HTTP server answering the batch and DB quiesce routes.

    ``convert_seconds`` is how long ``/run_directory`` blocks while reporting
    itself busy; 0 makes the conversion instantaneous, which is the vacuous
    case the probe has to catch.
    """

    def __init__(self, convert_seconds: float = 0.0, error: str = ""):
        self.convert_seconds = convert_seconds
        self.error = error
        self.active = 0
        self.n_queue = 0
        self.running: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep pytest output clean
                pass

            def do_POST(self):
                parsed = urlparse(self.path)
                route = parsed.path.lstrip("/")
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                with outer._lock:
                    outer.calls.append((route, params))
                body = outer.dispatch(route, params)
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def dispatch(self, route: str, params: dict):
        if route == "run_directory":
            return self.run_directory(params)
        if route == "watchdog_status":
            # shape per the real /watchdog_status body
            return {
                "running": True,
                "paused": True,
                "busy": self.active > 0,
                "active_sources": self.active,
                "jobs": ["family"],
            }
        if route == "list_conversions":
            convs = [
                {"source_dir": "in-flight", "started": 0.0, "elapsed_seconds": 1.0}
            ] * self.active
            return {"count": len(convs), "conversions": convs}
        if route == "n_queue":
            return self.n_queue
        if route == "tasks":
            return {"running": list(self.running), "num_queued": self.n_queue}
        raise AssertionError(f"unexpected route {route}")

    def run_directory(self, params: dict):
        if self.error:
            return {"error": self.error}
        with self._lock:
            self.active += 1
        try:
            time.sleep(self.convert_seconds)
        finally:
            with self._lock:
                self.active -= 1
        return {
            "instrument": "family",
            "source": "SRC",
            "results": {params["source_dir"]: "0" * 32},
        }

    @property
    def endpoint(self) -> Endpoint:
        host, port = self.httpd.server_address[:2]
        return Endpoint(str(host), int(port))

    def endpoints(self) -> CaptureEndpoints:
        return CaptureEndpoints(batch=self.endpoint, db=self.endpoint)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def make_fixture(tmp_path: Path, name: str = "0000_sample") -> Path:
    fixture = tmp_path / "fixtures" / name
    (fixture / "raw").mkdir(parents=True)
    (fixture / "raw" / "scan.dat").write_text("1 2 3\n")
    (fixture / "meta.txt").write_text("sanitized\n")
    return fixture


# --- the observation loop ---------------------------------------------------
def test_observe_quiesce_records_the_false_observations_before_settling():
    states = iter([False, False, True, True, True])
    obs = observe_quiesce(
        lambda: next(states), settle_polls=3, poll_s=0, sleep=lambda _s: None
    )
    assert obs == QuiesceObservation(polls=5, observed_busy=True, settled=True)


def test_observe_quiesce_resets_the_settle_run_on_a_late_false():
    states = iter([True, True, False, True, True, True])
    obs = observe_quiesce(
        lambda: next(states), settle_polls=3, poll_s=0, sleep=lambda _s: None
    )
    assert obs.settled and obs.polls == 6


def test_observe_quiesce_reports_a_never_false_predicate_as_vacuous():
    obs = observe_quiesce(lambda: True, settle_polls=3, poll_s=0, sleep=lambda _s: None)
    assert obs.settled is True
    assert obs.observed_busy is False  # nothing was ever seen in flight


def test_observe_quiesce_reports_not_settled_on_timeout():
    clock = iter([0.0, 1.0, 2.0, 3.0, 99.0])
    obs = observe_quiesce(
        lambda: False,
        settle_polls=3,
        poll_s=0,
        timeout_s=10.0,
        sleep=lambda _s: None,
        clock=lambda: next(clock),
    )
    assert obs.settled is False


# --- the predicate itself ---------------------------------------------------
def test_quiesce_predicate_reads_all_three_signals():
    with FakeGroup() as fake:
        eps = fake.endpoints()
        assert batch_quiesced(eps) is True

        fake.active = 1  # watchdog busy + a live conversion row
        assert batch_quiesced(eps) is False
        fake.active = 0

        fake.n_queue = 2  # DB sync queue still draining
        assert batch_quiesced(eps) is False
        fake.n_queue = 0

        fake.running = ["a-seq"]  # a sync task still running
        assert batch_quiesced(eps) is False
        fake.running = []

        assert batch_quiesced(eps) is True


def test_quiesce_predicate_needs_both_endpoints():
    with FakeGroup() as fake:
        with pytest.raises(RuntimeError, match="batch"):
            batch_quiesced(CaptureEndpoints(db=fake.endpoint))
        with pytest.raises(RuntimeError, match="db"):
            batch_quiesced(CaptureEndpoints(batch=fake.endpoint))


# --- the scenario ------------------------------------------------------------
def test_batch_scenario_stages_the_fixture_and_posts_run_directory(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    drop = root / "drop" / "family"
    with FakeGroup(convert_seconds=0.4) as fake:
        driver = make_batch_scenario(
            family="family",
            fixture_dir=fixture,
            drop_dir=drop,
            poll_s=0.05,
            settle_polls=2,
        )
        name, params = driver(root, fake.endpoints())

    staged = drop / fixture.name
    assert (staged / "raw" / "scan.dat").read_text() == "1 2 3\n"
    assert (fixture / "raw" / "scan.dat").exists()  # source untouched

    routes = [r for r, _ in fake.calls]
    assert "run_directory" in routes
    # the watchdog is never driven from the rig
    assert "resume_watchdog" not in routes and "run_family" not in routes
    submitted = [p for r, p in fake.calls if r == "run_directory"][0]
    assert submitted["source_dir"] == str(staged)

    assert name == "batch__family"
    assert params["family"] == "family"
    assert params["quiesce_observed_busy"] is True
    assert params["results"] == {str(staged): "0" * 32}


def test_batch_scenario_raises_when_the_quiesce_predicate_is_never_false(tmp_path):
    """The vacuity probe: an instant conversion proves nothing about quiesce."""
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    with FakeGroup(convert_seconds=0.0) as fake:
        driver = make_batch_scenario(
            family="family",
            fixture_dir=fixture,
            drop_dir=root / "drop" / "family",
            poll_s=0.05,
            settle_polls=2,
        )
        with pytest.raises(VacuousQuiesceError, match="never observed"):
            driver(root, fake.endpoints())


def test_batch_scenario_can_opt_out_of_the_vacuity_guard(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    with FakeGroup(convert_seconds=0.0) as fake:
        driver = make_batch_scenario(
            family="family",
            fixture_dir=fixture,
            drop_dir=root / "drop" / "family",
            poll_s=0.05,
            settle_polls=2,
            require_observed_busy=False,
        )
        _, params = driver(root, fake.endpoints())
    assert params["quiesce_observed_busy"] is False


def test_batch_scenario_raises_when_run_directory_reports_an_error(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    with FakeGroup(error="could not resolve a drop source") as fake:
        driver = make_batch_scenario(
            family="family",
            fixture_dir=fixture,
            drop_dir=root / "drop" / "family",
            poll_s=0.05,
            settle_polls=2,
        )
        with pytest.raises(RuntimeError, match="could not resolve a drop source"):
            driver(root, fake.endpoints())


def test_batch_scenario_raises_when_a_folder_converts_to_no_sequence(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    with FakeGroup(convert_seconds=0.4) as fake:
        fake.run_directory = lambda params: {  # type: ignore[method-assign]
            "instrument": "family",
            "source": "SRC",
            "results": {params["source_dir"]: None},
        }
        driver = make_batch_scenario(
            family="family",
            fixture_dir=fixture,
            drop_dir=root / "drop" / "family",
            poll_s=0.05,
            settle_polls=2,
            require_observed_busy=False,
        )
        with pytest.raises(RuntimeError, match="produced no sequence"):
            driver(root, fake.endpoints())


# --- staging safety ----------------------------------------------------------
def test_stage_fixture_refuses_a_drop_dir_outside_the_allowed_roots(tmp_path):
    fixture = make_fixture(tmp_path)
    outside = tmp_path / "elsewhere" / "drop"
    with pytest.raises(UnsafeDropDirError):
        stage_fixture(fixture, outside, allowed_roots=[tmp_path / "root"])
    assert not outside.exists()


def test_stage_fixture_refuses_to_overwrite_an_existing_staged_folder(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    drop = root / "drop"
    stage_fixture(fixture, drop, allowed_roots=[root])
    with pytest.raises(FileExistsError):
        stage_fixture(fixture, drop, allowed_roots=[root])


def test_stage_fixture_copies_rather_than_moves(tmp_path):
    fixture = make_fixture(tmp_path)
    root = tmp_path / "root"
    staged = stage_fixture(fixture, root / "drop", allowed_roots=[root])
    assert staged.is_dir() and fixture.is_dir()
    assert (staged / "meta.txt").read_text() == (fixture / "meta.txt").read_text()


# --- endpoints are config-derived, not module constants ----------------------
def test_endpoints_come_from_the_config_servers_block():
    config = {
        "servers": {
            "ORCH": {"host": "10.0.0.1", "port": 9001},
            "SIM": {"host": "10.0.0.2", "port": 9002},
            "SYNC": {"host": "10.0.0.3", "port": 9010},
            "BATCH": {"host": "10.0.0.4", "port": 9020},
        }
    }
    eps = CaptureEndpoints.from_config(config, {"batch": "BATCH"})
    assert eps.orch == Endpoint("10.0.0.1", 9001)
    assert eps.sim == Endpoint("10.0.0.2", 9002)
    assert eps.db == Endpoint("10.0.0.3", 9010)
    assert eps.batch == Endpoint("10.0.0.4", 9020)


def test_absent_optional_roles_are_none_and_required_roles_raise():
    config = {"servers": {"SYNC": {"host": "127.0.0.1", "port": 8010}}}
    eps = CaptureEndpoints.from_config(config, {"orch": None, "sim": None})
    assert eps.orch is None and eps.batch is None
    assert eps.require("db") == Endpoint("127.0.0.1", 8010)
    with pytest.raises(RuntimeError, match="orch"):
        eps.require("orch")
    with pytest.raises(KeyError):
        CaptureEndpoints.from_config(config, {"batch": "BATCH"}, optional=())


def test_resolve_endpoints_leaves_the_public_capture_config_where_it_was():
    """The refactor must not move GM-1..GM-5, which reach their servers
    through the module globals `resolve_endpoints` now writes."""
    from harness import capture

    before = (
        capture.ORCH_HOST,
        capture.ORCH_PORT,
        capture.SIM_HOST,
        capture.SIM_PORT,
        capture.DB_HOST,
        capture.DB_PORT,
    )
    try:
        capture.resolve_endpoints("golden")
        after = (
            capture.ORCH_HOST,
            capture.ORCH_PORT,
            capture.SIM_HOST,
            capture.SIM_PORT,
            capture.DB_HOST,
            capture.DB_PORT,
        )
        assert after == before
    finally:
        (
            capture.ORCH_HOST,
            capture.ORCH_PORT,
            capture.SIM_HOST,
            capture.SIM_PORT,
            capture.DB_HOST,
            capture.DB_PORT,
        ) = before


def test_resolve_endpoints_actually_moves_the_globals_for_another_config(monkeypatch):
    """The guard on the test above: it would pass just as well if
    `resolve_endpoints` did nothing at all."""
    from harness import capture
    from helao.helpers import config_loader

    before = (capture.ORCH_HOST, capture.ORCH_PORT, capture.DB_HOST, capture.DB_PORT)
    monkeypatch.setattr(
        config_loader,
        "read_config",
        lambda *a, **k: {
            "servers": {
                "ORCH": {"host": "10.9.9.9", "port": 9101},
                "SYNC": {"host": "10.9.9.9", "port": 9110},
            }
        },
    )
    try:
        eps = capture.resolve_endpoints("whatever")
        assert (capture.ORCH_HOST, capture.ORCH_PORT) == ("10.9.9.9", 9101)
        assert (capture.DB_HOST, capture.DB_PORT) == ("10.9.9.9", 9110)
        assert eps.sim is None  # absent from this config, not defaulted
    finally:
        (
            capture.ORCH_HOST,
            capture.ORCH_PORT,
            capture.DB_HOST,
            capture.DB_PORT,
        ) = before


def test_default_role_keys_reproduce_the_previous_hardcoded_ports():
    """The port refactor is a no-op for the existing public capture config."""
    from helao.helpers.config_loader import read_config

    config = read_config("golden")
    eps = CaptureEndpoints.from_config(config)
    assert DEFAULT_ROLE_KEYS == {"orch": "ORCH", "sim": "SIM", "db": "SYNC"}
    assert eps.orch == Endpoint("127.0.0.1", 8001)
    assert eps.sim == Endpoint("127.0.0.1", 8002)
    assert eps.db == Endpoint("127.0.0.1", 8010)
