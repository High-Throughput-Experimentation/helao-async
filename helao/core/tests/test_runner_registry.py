"""Runner registry: registration, 409 rules, deregister, expiry."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helao.ui.reflex.runner_registry import (
    EXPIRE_S,
    STALE_S,
    RunnerRegistry,
    make_runner_router,
)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def rig():
    clock = Clock()
    reg = RunnerRegistry(clock=clock)
    reg.reserve(["ORCH", "SIM"])
    app = FastAPI()
    app.include_router(make_runner_router(reg))
    return reg, TestClient(app), clock


def frame(instance="a", **kw):
    return {"kind": "runner", "instance": instance, "seq_no": 1, **kw}


def test_register_then_append():
    reg, c, _ = rig()
    assert c.post("/runners/R1/frame", json=frame()).status_code == 200
    assert c.post("/runners/R1/frame", json=frame()).status_code == 200
    feed = reg.get("R1")
    assert feed.n_batches == 2 and feed.status.message_count == 2
    assert reg.keys() == ["R1"]


def test_live_duplicate_is_409_and_reserved_key_is_409():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    assert c.post("/runners/R1/frame", json=frame("b")).status_code == 409
    assert c.post("/runners/SIM/frame", json=frame("a")).status_code == 409
    assert reg.get("R1").instance == "a"


def test_lost_entry_is_replaced_by_new_instance():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    clock.t += STALE_S + 0.1
    assert c.post("/runners/R1/frame", json=frame("b")).status_code == 200
    assert reg.get("R1").instance == "b" and reg.get("R1").n_batches == 1


def test_delete_right_and_wrong_instance():
    reg, c, _ = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    assert c.delete("/runners/R1", params={"instance": "x"}).status_code == 404
    assert c.delete("/runners/R1", params={"instance": "a"}).status_code == 200
    assert reg.get("R1").ended


def test_silent_runner_goes_lost_then_removed():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    feed = reg.get("R1")
    assert clock.t - feed.status.last_epoch <= STALE_S
    clock.t += EXPIRE_S - 1
    assert reg.sweep(clock.t) == [] and reg.get("R1") is feed
    clock.t += 2
    assert reg.sweep(clock.t) == [feed] and reg.get("R1") is None


def test_bad_body_is_400():
    _, c, _ = rig()
    assert c.post("/runners/R1/frame", json={"kind": "runner"}).status_code == 400


def test_repost_after_delete_revives_the_entry_and_keeps_the_key():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    c.delete("/runners/R1", params={"instance": "a"})
    clock.t += 1
    assert c.post("/runners/R1/frame", json=frame("a")).status_code == 200
    assert not reg.get("R1").ended and not reg.get("R1").lost(clock.t)
    assert c.post("/runners/R1/frame", json=frame("b")).status_code == 409


def test_runners_busy_follows_proc_states(monkeypatch):
    from helao.ui.reflex import runner_procs

    _, c, _ = rig()
    monkeypatch.setattr(runner_procs, "PROCS", {})
    assert c.get("/runners_busy").json() == {"busy": False}
    for state, want in [
        ("running", True),
        ("stopping", True),
        ("exited", False),
        ("stopped", False),
        ("killed", False),
    ]:
        monkeypatch.setattr(
            runner_procs,
            "PROCS",
            {"K": runner_procs.RunnerProc("K", "m", "l", None, state=state)},
        )
        assert c.post("/runners_busy").json() == {"busy": want}, state


def test_runners_busy_while_a_runner_is_spawning(monkeypatch):
    from helao.ui.reflex import runner_procs

    monkeypatch.setattr(runner_procs, "PROCS", {})
    monkeypatch.setattr(runner_procs, "_LAUNCHING", {"K"})
    assert runner_procs.busy() is True


def test_ended_runner_reads_ended_in_group_selector():
    from helao.ui.reflex.group import feed_label

    class F:
        ended = True

    assert feed_label(F(), 0.0) == "ended"
