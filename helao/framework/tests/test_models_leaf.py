"""Tests for the 12 ported leaf models (no model-to-model deps beyond support)."""
from pathlib import Path
from uuid import uuid4

import pytest

from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.electrolyte import Electrolyte
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.framework.models.process_contrib import ProcessContrib
from helao.framework.models.run_use import RunUse
from helao.framework.models.s3locator import S3Locator
from helao.framework.models.helaodirs import HelaoDirs
from helao.framework.models.machine import MachineModel
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.framework.models.data import DataModel, DataPackageModel
from helao.framework.models.credentials import HelaoCredentials
from helao.framework.models.errors import ErrorCodes


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
def test_action_start_condition_int_enum():
    assert ActionStartCondition.no_wait == 0
    assert ActionStartCondition.wait_for_previous.value == 5
    assert ActionStartCondition(1) is ActionStartCondition.wait_for_endpoint


def test_action_start_condition_rejects_unknown():
    with pytest.raises(ValueError):
        ActionStartCondition(99)


def test_electrolyte_other_escape_hatch():
    assert Electrolyte.other.value == "other-see-comment"
    assert Electrolyte("SLF10") is Electrolyte.slf10


def test_hlostatus_members():
    assert HloStatus.active.value == "active"
    assert {HloStatus.finished, HloStatus.errored, HloStatus.aborted}.issubset(
        set(HloStatus)
    )


def test_orchstatus_loopstatus_loopintent():
    assert OrchStatus.idle.value == "idle"
    assert LoopStatus.stopped.value == "stopped"
    assert LoopIntent.none.value == "none"
    with pytest.raises(ValueError):
        OrchStatus("not-a-state")


def test_process_contrib_six_members():
    assert {m.name for m in ProcessContrib} == {
        "action_params",
        "files",
        "samples_in",
        "samples_out",
        "run_use",
        "technique_name",
    }
    assert ProcessContrib("technique_name") is ProcessContrib.technique_name


def test_run_use_default_and_refs():
    assert RunUse.data.value == "data"
    assert RunUse(RunUse.ref_light.value) is RunUse.ref_light
    assert {RunUse.ref, RunUse.ref_light, RunUse.ref_dark, RunUse.ref_bkg}.issubset(
        set(RunUse)
    )


# --------------------------------------------------------------------------- #
# S3Locator
# --------------------------------------------------------------------------- #
def test_s3locator_url_property():
    loc = S3Locator(bucket="helao.data", key="action/abcd.json", region="us-east-2")
    assert loc.url == "s3://helao.data/action/abcd.json"


def test_s3locator_requires_all_fields():
    with pytest.raises(Exception):
        S3Locator(bucket="b")


# --------------------------------------------------------------------------- #
# HelaoDirs
# --------------------------------------------------------------------------- #
def test_helaodirs_defaults_none():
    hd = HelaoDirs()
    for k in (
        "root",
        "save_root",
        "log_root",
        "states_root",
        "db_root",
        "user_exp",
        "user_seq",
        "ana_root",
        "process_root",
    ):
        assert getattr(hd, k) is None


def test_helaodirs_path_roundtrip():
    hd = HelaoDirs(
        root=Path("/tmp/helao"),
        save_root=Path("/tmp/helao/RUNS_FINISHED"),
        log_root=Path("/tmp/helao/LOGS"),
    )
    dumped = hd.as_dict()
    assert dumped["root"] == "/tmp/helao"
    assert dumped["save_root"] == "/tmp/helao/RUNS_FINISHED"


# --------------------------------------------------------------------------- #
# MachineModel
# --------------------------------------------------------------------------- #
def test_machine_model_defaults_and_helpers():
    m = MachineModel()
    assert m.server_name is None and m.port is None
    m2 = MachineModel(server_name="orch", machine_name="host1", hostname="1.2.3.4", port=8001)
    assert m2.as_key() == ("orch", "host1")
    assert m2.disp_name() == "orch@host1"


# --------------------------------------------------------------------------- #
# server models
# --------------------------------------------------------------------------- #
def test_endpoint_model_construct_and_clear():
    ep = EndpointModel(endpoint_name="act")
    assert ep.endpoint_name == "act"
    assert ep.active_dict == {}
    ep.clear_finished()
    assert ep.nonactive_dict == {HloStatus.finished: {}}


def test_action_server_model_defaults():
    asm = ActionServerModel(action_server=MachineModel(server_name="s", machine_name="m"))
    assert asm.estop is False
    assert asm.endpoints == {}
    assert asm.last_action_uuid is None
    asm.init_endpoints()  # no-op with no endpoints


def test_global_status_model_defaults():
    gsm = GlobalStatusModel(orchestrator=MachineModel(server_name="o", machine_name="m"))
    assert gsm.loop_intent is LoopIntent.none
    assert gsm.loop_state is LoopStatus.stopped
    assert gsm.orch_state is OrchStatus.idle
    assert gsm.actions_idle() is True
    gsm.new_experiment(uuid4())
    assert len(gsm.counter_dispatched_actions) == 1


# --------------------------------------------------------------------------- #
# data models
# --------------------------------------------------------------------------- #
def test_data_model_defaults():
    conn = uuid4()
    dm = DataModel(data={conn: {"t_s": [0.0], "v": [0.1]}})
    assert dm.status is HloStatus.active
    assert dm.errors == []
    assert dm.data[conn]["v"] == [0.1]


def test_data_package_model_roundtrip():
    act = uuid4()
    dm = DataModel()
    pkg = DataPackageModel(
        action_uuid=act,
        action_name="record",
        datamodel=dm,
        errors=[ErrorCodes.none],
    )
    assert pkg.action_uuid == act
    assert pkg.action_name == "record"
    assert pkg.datamodel is dm
    assert pkg.as_dict()["errors"] == ["none"]


def test_data_package_requires_action_uuid():
    with pytest.raises(Exception):
        DataPackageModel(action_name="x", datamodel=DataModel())


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
def test_credentials_load_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_USER=alice\nAPI_PORT=6000\n", encoding="utf-8")
    creds = HelaoCredentials(_env_file=env)
    assert creds.API_USER == "alice"
    assert creds.API_PORT == 6000
    creds.set_api_port(7000)
    assert creds.API_PORT == 7000


def test_credentials_defaults_when_empty_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    creds = HelaoCredentials(_env_file=env)
    assert creds.API_USER == "postgres"
    assert creds.API_PORT == 5432
    assert creds.API_SCHEMA == "production"


def test_credentials_accepts_str_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_DB=mydb\n", encoding="utf-8")
    creds = HelaoCredentials(_env_file=str(env))
    assert creds.API_DB == "mydb"


def test_credentials_api_dsn_and_display(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_DB=mydb\nAPI_USER=bob\n", encoding="utf-8")
    creds = HelaoCredentials(_env_file=env)
    dsn = creds.api_dsn
    assert dsn.startswith("postgresql://bob")
    assert "search_path" in dsn
    # show_defaults=True avoids the undefined _always_set short-circuit
    rendered = creds.display(show_defaults=True)
    assert "MPS Client Settings" in rendered
    assert "API_USER = bob" in rendered
    # NOTE: display() with defaults references undefined _always_set/_simple_params
    # (a latent bug carried over faithfully from helao/core); only show_defaults=True
    # short-circuits past it, so __str__()/simple=True are intentionally not exercised.


# --------------------------------------------------------------------------- #
# server orchestration behaviour (driven by a tiny duck-typed action stand-in)
# --------------------------------------------------------------------------- #
from typing import Any, List
from pydantic import BaseModel, ConfigDict

from helao.framework.models.helao_dict import HelaoDict


class _FakeAction(BaseModel, HelaoDict):
    """Minimal stand-in for an action model: only the attrs server.py reads."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    action_status: List[HloStatus] = []
    orchestrator: MachineModel = MachineModel()
    experiment_uuid: Any = None


def _orch_machine():
    return MachineModel(server_name="orch", machine_name="omach")


def _server_machine():
    return MachineModel(server_name="srv", machine_name="smach")


def test_endpoint_sort_status_buckets_finished():
    orch = _orch_machine()
    ep = EndpointModel(endpoint_name="act")
    u_active = uuid4()
    u_done = uuid4()
    u_err = uuid4()
    ep.active_dict[u_active] = _FakeAction(action_status=[HloStatus.active], orchestrator=orch)
    ep.active_dict[u_done] = _FakeAction(action_status=[HloStatus.finished], orchestrator=orch)
    ep.active_dict[u_err] = _FakeAction(
        action_status=[HloStatus.finished, HloStatus.errored], orchestrator=orch
    )
    ep.sort_status()
    assert u_active in ep.active_dict
    assert u_done not in ep.active_dict
    assert u_done in ep.nonactive_dict[HloStatus.finished]
    assert u_err in ep.nonactive_dict[HloStatus.finished]
    # __str__/__repr__ cover the summary branches
    assert "active:" in str(ep)
    assert repr(ep).startswith("<")


def test_action_server_get_fastapi_json():
    asm = ActionServerModel(action_server=_server_machine())
    asm.endpoints["act"] = EndpointModel(endpoint_name="act")
    asm.endpoints["other"] = EndpointModel(endpoint_name="other")
    full = asm.get_fastapi_json()
    assert "endpoints" in full
    one = asm.get_fastapi_json(action_name="act")
    assert "act" in one["endpoints"]
    assert asm.get_fastapi_json(action_name="missing") == {}
    asm.init_endpoints()
    assert asm.endpoints["act"].nonactive_dict == {HloStatus.finished: {}}


def _populated_global():
    orch = _orch_machine()
    gsm = GlobalStatusModel(orchestrator=orch)
    asm = ActionServerModel(action_server=_server_machine())
    ep = EndpointModel(endpoint_name="act")
    exp = uuid4()
    u_active = uuid4()
    u_done = uuid4()
    ep.active_dict[u_active] = _FakeAction(
        action_status=[HloStatus.active], orchestrator=orch, experiment_uuid=exp
    )
    ep.active_dict[u_done] = _FakeAction(
        action_status=[HloStatus.finished], orchestrator=orch, experiment_uuid=exp
    )
    asm.endpoints["act"] = ep
    return gsm, asm, exp, u_active, u_done


def test_global_update_and_free_checks():
    gsm, asm, exp, u_active, u_done = _populated_global()
    gsm.update_global_with_acts(asm)
    # the finished action lands directly in this orch's nonactive bucket
    assert u_done in gsm.nonactive_dict[HloStatus.finished]
    assert u_active in gsm.active_dict
    assert gsm.actions_idle() is False
    # server/endpoint not free because one active action belongs to this orch
    assert gsm.server_free(asm.action_server) is False
    assert gsm.endpoint_free(asm.action_server, "act") is False
    assert gsm.endpoint_free(asm.action_server, "nonexistent") is True
    # update again (server already present) exercises the merge branch
    gsm.update_global_with_acts(asm)
    # as_json flattens server_dict keys to server@machine strings
    aj = gsm.as_json()
    assert any("@" in k for k in aj["server_dict"])


def test_global_active_to_finished_transition_records_recent():
    orch = _orch_machine()
    gsm = GlobalStatusModel(orchestrator=orch)
    asm = ActionServerModel(action_server=_server_machine())
    ep = EndpointModel(endpoint_name="act")
    u = uuid4()
    act = _FakeAction(action_status=[HloStatus.active], orchestrator=orch, experiment_uuid=uuid4())
    ep.active_dict[u] = act
    asm.endpoints["act"] = ep
    # first pass: action is active, goes into gsm.active_dict
    gsm.update_global_with_acts(asm)
    assert u in gsm.active_dict
    # action now finishes; same object, status flips
    act.action_status = [HloStatus.finished]
    recent = gsm.update_global_with_acts(asm)
    assert (u, HloStatus.finished.name) in recent
    assert u not in gsm.active_dict
    assert u in gsm.nonactive_dict[HloStatus.finished]


def test_global_finished_lookup_and_clear():
    gsm, asm, exp, u_active, u_done = _populated_global()
    gsm.update_global_with_acts(asm)
    found = gsm.find_hlostatus_in_finished(HloStatus.finished)
    assert u_done in found
    gsm.clear_in_finished(HloStatus.finished)
    assert gsm.find_hlostatus_in_finished(HloStatus.finished) == {}


def test_global_finish_experiment():
    gsm, asm, exp, u_active, u_done = _populated_global()
    gsm.new_experiment(exp)
    gsm.update_global_with_acts(asm)
    finished = gsm.finish_experiment(exp)
    assert any(a.experiment_uuid == exp for a in finished)
    assert exp not in gsm.counter_dispatched_actions
    assert gsm.nonactive_dict == {}


def test_endpoint_free_when_server_absent():
    gsm = GlobalStatusModel(orchestrator=_orch_machine())
    assert gsm.server_free(_server_machine()) is True
    assert gsm.endpoint_free(_server_machine(), "act") is True
