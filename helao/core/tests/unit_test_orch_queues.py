"""Unit tests for the ``RunQueues`` collaborator extracted from ``Orch``
(CARDS P5, Stage S5): queue CRUD + uuid tracking cluster ("cluster A").

Queue CRUD is partly exercised (byte-for-byte) by
``test_orch_dispatch_golden_master.py --check`` via the dispatch loop's own
appends/pops of ``sequence_dq``/``experiment_dq``/``action_dq``, but that
harness never drives the operator-facing surface directly: ``move_*``/
``remove_*``/``prepend_sequences``/``drop_experiment_inds``/
``supplement_error_action``/``replace_action``, or the uuid-history helpers.
This module is the S5-specific behavior-preservation gate for that surface.

Mirrors the ``Orch.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch`` (and the S3/S4
sibling unit tests): a bare ``Orch`` built without ``Base.__init__`` (no
FastAPI app, no disk I/O, no NTP), populated only with the attributes
``RunQueues`` methods touch, then ``_init_collaborators()`` is called so
``orch.run_queues`` exists exactly as it would after the real ``__init__``.

Hermetic: no network, no disk I/O, real ``zdeque``/``DequeDict``/
``GlobalStatusModel``/``Sequence``/``Experiment``/``Action`` model instances
(same premodels the production code uses) so the CRUD invariants are checked
against genuine model behavior, not stand-ins.
"""

__all__ = ["orch_queues_unit_test"]

import asyncio
import traceback
from uuid import uuid4

from helao.core.tests._test_utils import TestReporter
from helao.core.servers.orch import Orch
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import GlobalStatusModel
from helao.helpers.dequedict import DequeDict
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.zdeque import zdeque

ORCH_SERVER_NAME = "ORCH"
ORCH_MACHINE = "test-machine"


def _make_orch() -> Orch:
    """Build a bare ``Orch`` with every attribute ``RunQueues`` methods touch."""
    orch = Orch.__new__(Orch)

    orch.server = MachineModel(
        server_name=ORCH_SERVER_NAME, machine_name=ORCH_MACHINE, hostname="127.0.0.1", port=8000
    )
    orch.server_params = {}

    orch.sequence_lib = {}
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}

    orch.sequence_dq = zdeque([])
    orch.experiment_dq = zdeque([])
    orch.action_dq = zdeque([])

    orch.action_history = DequeDict(maxlen=1000)
    orch.experiment_history = DequeDict(maxlen=1000)
    orch.sequence_history = DequeDict(maxlen=1000)
    orch.last_dispatched_action_uuid = None

    orch.active_run_id = None
    orch.active_experiment = None
    orch.last_experiment = None
    orch.active_sequence = None
    orch.last_sequence = None

    orch.globalstatusmodel = GlobalStatusModel(orchestrator=orch.server)

    orch._init_collaborators()
    return orch


def _mk_sequence(name: str) -> Sequence:
    return Sequence(sequence_name=name, sequence_params={})


def _mk_experiment(name: str) -> Experiment:
    return Experiment(experiment_name=name, experiment_params={})


def _mk_action(orch: Orch, name: str, order: int = 0) -> Action:
    return Action(
        action_name=name,
        action_params={},
        action_server=MachineModel(server_name="SRV1", machine_name=ORCH_MACHINE),
        orchestrator=orch.server,
        action_order=order,
    )


# ---------------------------------------------------------------------------
# uuid tracking
# ---------------------------------------------------------------------------


def _check_uuid_tracking() -> bool:
    orch = _make_orch()
    u1 = uuid4()
    orch.register_action_uuid(u1, {"action_name": "a1"})
    orch.register_action_uuid(u1, {"action_status": "finished"})
    orch.track_action_uuid(u1)
    return (
        orch.action_history[u1] == {"action_name": "a1", "action_status": "finished"}
        and orch.last_dispatched_action_uuid == u1
    )


# ---------------------------------------------------------------------------
# sequence CRUD
# ---------------------------------------------------------------------------


async def _check_sequence_crud() -> bool:
    orch = _make_orch()

    u1 = await orch.add_sequence(_mk_sequence("seq1"))
    u2 = await orch.add_sequence(_mk_sequence("seq2"))
    u3 = await orch.add_sequence(_mk_sequence("seq3"))
    add_order_ok = [s.sequence_uuid for s in orch.list_sequences()] == [u1, u2, u3]
    # first add on an empty queue mints a fresh run_id; subsequent adds reuse it
    run_id_ok = (
        orch.sequence_dq[0].run_id == orch.active_run_id
        and orch.sequence_dq[1].run_id == orch.active_run_id
        and orch.sequence_dq[2].run_id == orch.active_run_id
    )

    await orch.move_sequence(0, 2)
    move_ok = [s.sequence_uuid for s in orch.list_sequences()] == [u2, u3, u1]

    await orch.remove_sequence(1)
    remove_ok = [s.sequence_uuid for s in orch.list_sequences()] == [u2, u1]

    await orch.clear_sequences()
    clear_ok = len(orch.sequence_dq) == 0

    # prepend_sequences: stamps meta + shares the (now-reset) run_id, LIFO->front insert order
    pu = await orch.prepend_sequences([_mk_sequence("p1"), _mk_sequence("p2")])
    prepend_ok = (
        [s.sequence_uuid for s in orch.list_sequences()] == pu
        and orch.sequence_dq[0].run_id == orch.sequence_dq[1].run_id
    )

    return add_order_ok and run_id_ok and move_ok and remove_ok and clear_ok and prepend_ok


# ---------------------------------------------------------------------------
# experiment CRUD
# ---------------------------------------------------------------------------


async def _check_experiment_crud() -> bool:
    orch = _make_orch()
    seq = _mk_sequence("seq1")

    u1 = await orch.add_experiment(seq, _mk_experiment("exp1"))
    u2 = await orch.add_experiment(seq, _mk_experiment("exp2"))
    u3 = await orch.add_experiment(seq, _mk_experiment("exp3"))
    add_order_ok = [e.experiment_uuid for e in orch.list_experiments()] == [u1, u2, u3]
    # every enqueued experiment inherits the sequence's fields (e.g. orchestrator)
    inherited_ok = all(e.orchestrator == orch.server for e in orch.experiment_dq)

    await orch.move_experiment(0, 2)
    move_ok = [e.experiment_uuid for e in orch.list_experiments()] == [u2, u3, u1]

    await orch.remove_experiment(idx=1)
    remove_idx_ok = [e.experiment_uuid for e in orch.list_experiments()] == [u2, u1]

    await orch.remove_experiment(by_uuid=u1)
    remove_uuid_ok = [e.experiment_uuid for e in orch.list_experiments()] == [u2]

    # rebuild drop_experiment_inds against a fresh 3-item queue
    await orch.clear_experiments()
    u4 = await orch.add_experiment(seq, _mk_experiment("exp4"))
    u5 = await orch.add_experiment(seq, _mk_experiment("exp5"))
    u6 = await orch.add_experiment(seq, _mk_experiment("exp6"))
    remaining = orch.drop_experiment_inds([1])
    drop_ok = [name for _, name in remaining] == ["exp4", "exp6"] and [
        e.experiment_uuid for e in orch.experiment_dq
    ] == [u4, u6]

    await orch.clear_experiments()
    clear_ok = len(orch.experiment_dq) == 0

    return (
        add_order_ok
        and inherited_ok
        and move_ok
        and remove_idx_ok
        and remove_uuid_ok
        and drop_ok
        and clear_ok
    )


# ---------------------------------------------------------------------------
# action CRUD
# ---------------------------------------------------------------------------


async def _check_action_crud() -> bool:
    orch = _make_orch()
    # append_action's empty-queue branch reads the dispatched-action counter
    # off the active experiment; a counter of 0 floors `last_action_order` to
    # 0 (since counter - 1 < 0), so the first-ever append lands at order 1,
    # not 0 -- a genuine pre-existing quirk of the moved formula, preserved
    # verbatim here rather than "fixed" to a more intuitive 0-based order.
    orch.active_experiment = _mk_experiment("host_exp")
    orch.globalstatusmodel.counter_dispatched_actions[
        orch.active_experiment.experiment_uuid
    ] = 0

    orch.append_action(_mk_action(orch, "act1"))
    orch.append_action(_mk_action(orch, "act2"))
    orch.append_action(_mk_action(orch, "act3"))
    names = [a.action_name for a in orch.list_actions()]
    add_order_ok = names == ["act1", "act2", "act3"]
    orders_ok = [a.action_order for a in orch.action_dq] == [1, 2, 3]

    await orch.move_action(0, 2)
    move_ok = [a.action_name for a in orch.list_actions()] == ["act2", "act3", "act1"]

    await orch.remove_action(1)
    remove_ok = [a.action_name for a in orch.list_actions()] == ["act2", "act1"]

    await orch.clear_actions()
    clear_ok = len(orch.action_dq) == 0

    # replace_action by index -- note the preserved `if by_index:` truthiness
    # quirk means index 0 is indistinguishable from "no index given", so this
    # exercises index 1 (the only way `by_index` is exercised as truthy).
    orch.append_action(_mk_action(orch, "orig1"))
    orch.append_action(_mk_action(orch, "orig2"))
    replacement = _mk_action(orch, "replaced")
    orch.replace_action(replacement, by_index=1)
    replace_ok = [a.action_name for a in orch.action_dq] == ["orig1", "replaced"] and (
        orch.action_dq[1].action_order == 2
    )

    return add_order_ok and orders_ok and move_ok and remove_ok and clear_ok and replace_ok


async def _check_supplement_error_action() -> bool:
    """P5b fix: the errored-action-retry path copied ``EA_act.actual_order`` onto
    ``new_action.actual_order``, but the real declared field on ``Action`` is
    ``action_actual_order`` (``actual_order`` was never a field) -- against real
    pydantic model instances that raised ``AttributeError`` and no retry was ever
    queued. Now corrected to ``action_actual_order``. This asserts the fixed
    behavior: the replacement is queued to the front of ``action_dq`` with the
    errored action's ``action_order``/``action_actual_order`` copied and
    ``action_retry`` incremented, with no exception.
    """
    orch = _make_orch()
    errored = _mk_action(orch, "errored_act", order=5)
    errored.action_actual_order = 3
    errored.action_retry = 1
    check_uuid = errored.action_uuid
    orch.globalstatusmodel.nonactive_dict[HloStatus.errored] = {check_uuid: errored}

    replacement = _mk_action(orch, "retry_act")
    orch.supplement_error_action(check_uuid, replacement)

    # zdeque stores by value, so assert on the queued action's fields (not identity)
    if len(orch.action_dq) != 1:
        return False
    queued = orch.action_dq[0]
    return (
        queued.action_name == "retry_act"
        and queued.action_order == 5
        and queued.action_actual_order == 3
        and queued.action_retry == 2
    )


# ---------------------------------------------------------------------------
# get_sequence / get_experiment
# ---------------------------------------------------------------------------


def _check_get_active_and_last() -> bool:
    orch = _make_orch()
    empty_ok = orch.get_sequence() == {} and orch.get_experiment() == {}

    active_seq = _mk_sequence("active_seq")
    last_seq = _mk_sequence("last_seq")
    orch.active_sequence = active_seq
    orch.last_sequence = last_seq
    seq_ok = (
        orch.get_sequence().sequence_name == "active_seq"
        and orch.get_sequence(last=True).sequence_name == "last_seq"
    )

    active_exp = _mk_experiment("active_exp")
    last_exp = _mk_experiment("last_exp")
    orch.active_experiment = active_exp
    orch.last_experiment = last_exp
    exp_ok = (
        orch.get_experiment().experiment_name == "active_exp"
        and orch.get_experiment(last=True).experiment_name == "last_exp"
    )

    return empty_ok and seq_ok and exp_ok


def _check_base_collaborator_seam() -> bool:
    """Regression: Orch._init_collaborators must call super() so the Base
    collaborators (live_buffer_mgr, status_broadcaster; CARDS P6) exist on
    Orch instances -- otherwise every inherited status/live delegator raises
    AttributeError at Orch.myinit (found in P6-S2 review)."""
    orch = _make_orch()
    return all(
        hasattr(orch, a)
        for a in (
            "live_buffer_mgr",
            "status_broadcaster",
            "queue_persister",
            "status_ingester",
            "run_queues",
            "dispatch_runner",
        )
    )


async def _run_checks() -> dict:
    return {
        "uuid_tracking": _check_uuid_tracking(),
        "sequence_crud": await _check_sequence_crud(),
        "experiment_crud": await _check_experiment_crud(),
        "action_crud": await _check_action_crud(),
        "supplement_error_action": await _check_supplement_error_action(),
        "get_active_and_last": _check_get_active_and_last(),
        "base_collaborator_seam": _check_base_collaborator_seam(),
    }


def orch_queues_unit_test() -> bool:
    reporter = TestReporter("orch_queues")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("uuid tracking")
    reporter.check(
        "register_action_uuid merges into action_history; track_action_uuid records last dispatched",
        lambda: res["uuid_tracking"],
    )

    reporter.section("sequence CRUD")
    reporter.check(
        "add_sequence appends in order, shares run_id, move/remove/clear/prepend behave",
        lambda: res["sequence_crud"],
    )

    reporter.section("experiment CRUD")
    reporter.check(
        "add_experiment inherits sequence fields; move/remove(idx|uuid)/drop_inds/clear behave",
        lambda: res["experiment_crud"],
    )

    reporter.section("action CRUD")
    reporter.check(
        "append_action assigns increasing action_order; move/remove/clear/replace_action behave",
        lambda: res["action_crud"],
    )

    reporter.section("supplement_error_action")
    reporter.check(
        "P5b fix: queues the retry to the front with action_order/action_actual_order"
        " copied and action_retry incremented (no AttributeError)",
        lambda: res["supplement_error_action"],
    )

    reporter.section("get_sequence / get_experiment")
    reporter.check(
        "return {} when unset, else the active/last summary per the `last` flag",
        lambda: res["get_active_and_last"],
    )

    reporter.section("Base collaborator seam")
    reporter.check(
        "Orch._init_collaborators calls super() -> Base live_buffer_mgr/status_broadcaster built on Orch",
        lambda: res["base_collaborator_seam"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_queues_unit_test() else 1)
