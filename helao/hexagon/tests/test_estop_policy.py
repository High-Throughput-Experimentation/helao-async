"""EstopPolicy: (declarative topology + trigger) -> ordered command list."""

import pytest

from helao.hexagon.domain import estop_policy as ep
from helao.hexagon.domain.models import HloStatus
from helao.hexagon.domain.orchestration import EstopFanout, FinishActiveEstopped

SERVERS_CFG = {
    "ORCH": {"group": "orchestrator", "host": "h", "port": 8001},
    "RECORD1": {"group": "action", "estop_roles": ["recorder"]},
    "RECORD2": {"group": "action", "estop_roles": ["recorder"]},
    "PSTAT1": {"group": "action", "estop_roles": ["stop_private"]},
    "MOTOR": {"group": "action"},
    "VIS": {"group": "visualizer", "bokeh": "x"},
}


def topo() -> ep.EstopTopology:
    return ep.derive_estop_topology(SERVERS_CFG)


def test_derive_topology_roles():
    t = topo()
    assert t.orch_keys == ("ORCH",)
    assert t.recorder_keys == ("RECORD1", "RECORD2")
    assert t.stop_private_keys == ("PSTAT1",)
    # fanout targets every non-visualizer server (server_dict members)
    assert set(t.all_server_keys) == {"ORCH", "RECORD1", "RECORD2", "PSTAT1", "MOTOR"}


def test_derive_topology_rejects_unknown_role():
    bad = {"X": {"group": "action", "estop_roles": ["recroder"]}}
    with pytest.raises(ValueError):
        ep.derive_estop_topology(bad)


def test_driver_fault_edge_orders_orch_recorders_private():
    """A private deployment's driver-resident emergency-stop cascade, now
    policy-emitted: ORCH* /stop -> recorder keys /stop_record -> PSTAT keys
    /stop_private."""
    p = ep.EstopPolicy(topo())
    cmds = p.commands_for(ep.DriverFaultEdge(source="opcua_monitor"))
    assert [type(c) for c in cmds] == [ep.StopOrch, ep.StopRecorders, ep.StopPrivate]
    assert cmds[0].key == "ORCH"
    assert cmds[1].keys == ("RECORD1", "RECORD2")
    assert cmds[2].keys == ("PSTAT1",)


def test_ui_button_same_cascade_as_fault_edge():
    """The visualizer's duplicate buttons feed the SAME policy (spec §4.2.5)."""
    p = ep.EstopPolicy(topo())
    assert p.commands_for(ep.UiEstopButton(source="vis")) == p.commands_for(
        ep.DriverFaultEdge(source="vis")
    )


def test_orch_estop_request_full_sequence():
    """/estop_orch and status-ingested estop drive the orch-side sequence:
    fanout to every server then finalize actives (core-01 §7)."""
    p = ep.EstopPolicy(topo())
    cmds = p.commands_for(ep.OrchEstopRequest(reason="operator"))
    assert [type(c) for c in cmds] == [EstopFanout, FinishActiveEstopped]
    assert cmds[0].switch is False


def test_status_ingested_matches_orch_request():
    p = ep.EstopPolicy(topo())
    assert [
        type(c) for c in p.commands_for(ep.StatusEstopIngested(reason="uuid estopped"))
    ] == [EstopFanout, FinishActiveEstopped]


def test_multiple_orchestrators_each_get_stop():
    cfg = dict(SERVERS_CFG)
    cfg["ORCH2"] = {"group": "orchestrator"}
    p = ep.EstopPolicy(ep.derive_estop_topology(cfg))
    cmds = p.commands_for(ep.DriverFaultEdge(source="x"))
    assert [c.key for c in cmds if isinstance(c, ep.StopOrch)] == ["ORCH", "ORCH2"]


def test_empty_role_groups_emit_no_commands_for_them():
    cfg = {"ORCH": {"group": "orchestrator"}, "A": {"group": "action"}}
    p = ep.EstopPolicy(ep.derive_estop_topology(cfg))
    cmds = p.commands_for(ep.DriverFaultEdge(source="x"))
    assert [type(c) for c in cmds] == [ep.StopOrch]


# --- the estopped-artifact-shape constraint ---


def test_mark_estopped_replaces_active_and_appends_estopped():
    out = ep.mark_estopped([HloStatus.active])
    assert out == [HloStatus.finished, HloStatus.estopped]


def test_mark_estopped_idempotent():
    once = ep.mark_estopped([HloStatus.active])
    assert ep.mark_estopped(once) == once


def test_mark_estopped_never_bare_estopped():
    assert ep.mark_estopped([]) == [HloStatus.finished, HloStatus.estopped]
