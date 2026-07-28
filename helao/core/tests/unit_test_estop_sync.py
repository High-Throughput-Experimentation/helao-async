"""Unit tests for the e-stop refactor: no fabricated estop artifacts, and
partial/estopped runs stay syncable.

Covers:
  1. Base.estop_actives finalizes only actions that were actually in-flight
     (appending HloStatus.estopped and calling the active's finish path); an idle
     server finalizes nothing and therefore writes no artifact.
  2. HelaoYml.is_estopped reads the yml meta *_status list (robust to both the
     bare "estopped" value and the "HloStatus.estopped" repr form).
  3. The sync_yml active-children gate treats an estopped child stranded in
     RUNS_ACTIVE as terminal (non-blocking), while a genuinely-running
     (non-estopped) active child still blocks the parent.

Hermetic: no AWS/API configured; no network. Base.estop_actives is exercised
against a lightweight fake so no full server needs to be constructed.
"""

__all__ = ["estop_sync_unit_test"]

import asyncio
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from helao.core.tests._test_utils import TestReporter
from helao.core.servers.base import Base
from helao.core.models.hlostatus import HloStatus
from helao.core.models.run_dir import RunDir
from helao.core.drivers.data.sync_driver import HelaoYml
from helao.helpers.yml_tools import yml_dumps


# ---- fakes for Base.estop_actives (avoids constructing a full server) --------
class _FakeAction:
    def __init__(self, uuid):
        self.action_uuid = uuid
        self.action_status = [HloStatus.active]


class _FakeActive:
    def __init__(self, actions):
        self.action_list = actions
        self.finished = False

    def set_estop(self, action=None):
        action.action_status.append(HloStatus.estopped)

    async def finish_all(self):
        self.finished = True
        return self.action_list[-1]


class _FakeBase:
    def __init__(self, actives):
        self.actives = actives


# ---- on-disk helpers for HelaoYml / gate tests ------------------------------
def _write_yml(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yml_dumps(meta)
    if isinstance(dumped, bytes):
        dumped = dumped.decode("utf-8")
    path.write_text(dumped, encoding="utf-8")


def _ts(second: int) -> str:
    return datetime(2026, 6, 10, 12, 0, second, 100).strftime("%y%m%d.%H%M%S%f")


def _exp_dir(root: Path, runs: str) -> Path:
    return (
        root / runs / "26.23" / "0610" / f"{_ts(0)}__test__seq" / f"{_ts(0)}__test_exp"
    )


def _make_exp(root: Path) -> Path:
    exp_yml = _exp_dir(root, RunDir.FINISHED.value) / f"{_ts(0)}-exp.yml"
    _write_yml(
        exp_yml,
        {
            "experiment_uuid": "00000000-0000-0000-0000-000000000001",
            "experiment_name": "test_exp",
            "experiment_status": ["active"],
        },
    )
    return exp_yml


def _make_active_child(root: Path, order: int, status: list) -> Path:
    act_yml = (
        _exp_dir(root, RunDir.ACTIVE.value)
        / f"{order}__0__srv__test_action"
        / f"{_ts(order + 1)}-act.yml"
    )
    _write_yml(
        act_yml,
        {
            "action_uuid": f"00000000-0000-0000-0000-00000000010{order}",
            "action_name": "test_action",
            "action_order": order,
            "action_status": status,
        },
    )
    return act_yml


async def _run_checks() -> dict:
    out = {}

    # --- 1. Base.estop_actives ------------------------------------------------
    out["estop_actives_idle_empty"] = (await Base.estop_actives(_FakeBase({}))) == []

    act = _FakeAction("00000000-0000-0000-0000-000000000abc")
    active = _FakeActive([act])
    res = await Base.estop_actives(_FakeBase({act.action_uuid: active}))
    out["estop_actives_finalized"] = active.finished is True
    out["estop_actives_marked"] = HloStatus.estopped in act.action_status
    out["estop_actives_returns_uuid"] = res == [str(act.action_uuid)]

    # multi-action active (e.g. after split): every action folded + reported
    a1 = _FakeAction("00000000-0000-0000-0000-000000000a01")
    a2 = _FakeAction("00000000-0000-0000-0000-000000000a02")
    multi = _FakeActive([a1, a2])
    res2 = await Base.estop_actives(_FakeBase({a1.action_uuid: multi}))
    out["estop_actives_multi_all_marked"] = (
        HloStatus.estopped in a1.action_status
        and HloStatus.estopped in a2.action_status
    )
    out["estop_actives_multi_all_uuids"] = res2 == [
        str(a1.action_uuid),
        str(a2.action_uuid),
    ]

    # --- 2 & 3. HelaoYml.is_estopped + gate filter ---------------------------
    with tempfile.TemporaryDirectory() as tmp_root:
        root = Path(tmp_root)
        exp_yml = _make_exp(root)
        # one estopped child (bare value) + one estopped child (repr form)
        _make_active_child(root, 0, ["estopped", "finished"])
        _make_active_child(root, 1, ["HloStatus.estopped"])

        exp = HelaoYml(exp_yml)
        active_children = exp.active_children
        out["gate_sees_two_active"] = len(active_children) == 2
        out["is_estopped_bare"] = all(c.is_estopped for c in active_children)
        # the gate's blocking set excludes estopped children -> empty -> no block
        blocking = [c for c in active_children if not c.is_estopped]
        out["estopped_children_nonblocking"] = blocking == []

    with tempfile.TemporaryDirectory() as tmp_root:
        root = Path(tmp_root)
        exp_yml = _make_exp(root)
        # a genuinely running child (no estopped status) must still block
        _make_active_child(root, 0, ["active"])
        exp = HelaoYml(exp_yml)
        active_children = exp.active_children
        blocking = [c for c in active_children if not c.is_estopped]
        out["running_child_blocks"] = len(blocking) == 1
        out["running_child_not_estopped"] = active_children[0].is_estopped is False

    return out


def estop_sync_unit_test() -> bool:
    reporter = TestReporter("estop_sync")
    saved_aws = os.environ.pop("AWS_CONFIG_PATH", None)
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
    finally:
        if saved_aws is not None:
            os.environ["AWS_CONFIG_PATH"] = saved_aws

    reporter.section("Base.estop_actives finalizes only in-flight actions")
    reporter.check(
        "idle server finalizes nothing (no artifact)",
        lambda: res["estop_actives_idle_empty"],
    )
    reporter.check(
        "in-flight active is finalized", lambda: res["estop_actives_finalized"]
    )
    reporter.check(
        "in-flight action marked estopped", lambda: res["estop_actives_marked"]
    )
    reporter.check(
        "returns finalized action uuid", lambda: res["estop_actives_returns_uuid"]
    )
    reporter.check(
        "multi-action active: all marked estopped",
        lambda: res["estop_actives_multi_all_marked"],
    )
    reporter.check(
        "multi-action active: all uuids returned",
        lambda: res["estop_actives_multi_all_uuids"],
    )

    reporter.section("HelaoYml.is_estopped + active-children gate")
    reporter.check(
        "gate sees both active children", lambda: res["gate_sees_two_active"]
    )
    reporter.check(
        "is_estopped matches bare + repr forms", lambda: res["is_estopped_bare"]
    )
    reporter.check(
        "estopped active children are non-blocking",
        lambda: res["estopped_children_nonblocking"],
    )
    reporter.check(
        "running (non-estopped) child still blocks", lambda: res["running_child_blocks"]
    )
    reporter.check(
        "running child is not flagged estopped",
        lambda: res["running_child_not_estopped"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if estop_sync_unit_test() else 1)
