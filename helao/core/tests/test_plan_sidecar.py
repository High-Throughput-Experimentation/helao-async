"""Plan sidecars (spec §3.3): stripped entries, write-once, invisible to record globs."""

import json
from uuid import UUID

import pytest

from helao.core.models.experiment import ShortExperimentModel
from helao.core.models.plan import experiment_plan, plan_name, sequence_plan
from helao.helpers.plan_io import write_plan_once
from helao.helpers.premodels import Action
from helao.hexagon.domain.naming import meta_kind

SU = UUID("00000000-0000-0000-0000-0000000000b1")
EU = UUID("00000000-0000-0000-0000-0000000000c1")
A1 = UUID("00000000-0000-0000-0000-0000000000a1")


def test_plan_name_from_json_and_legacy_yml():
    assert (
        plan_name("/r/s/260101.010101000000-seq.json")
        == "260101.010101000000-seq.plan.json"
    )
    assert (
        plan_name("/r/s/260101.010101000000-exp.yml")
        == "260101.010101000000-exp.plan.json"
    )


def test_plan_files_are_not_records():
    assert meta_kind("260101.010101000000-seq.plan.json") is None
    assert meta_kind("260101.010101000000-exp.plan.json") is None


def test_sequence_plan_strips_params_and_output_dir():
    planned = [
        ShortExperimentModel(
            experiment_name=n,
            experiment_params={"big": list(range(100))},
            experiment_output_dir="x/y",
            orch_key="ORCH",
        )
        for n in ("a", "b")
    ]
    p = sequence_plan(SU, planned)
    assert p["file_type"] == "sequence_plan"
    assert p["sequence_uuid"] == str(SU)
    assert [e["order"] for e in p["planned"]] == [0, 1]
    assert [e["experiment_name"] for e in p["planned"]] == ["a", "b"]
    for e in p["planned"]:
        assert "experiment_params" not in e and "experiment_output_dir" not in e
        assert e["orch_key"] == "ORCH"


def test_experiment_plan_strips_action_params():
    act = Action(
        action_name="acquire",
        action_uuid=A1,
        action_order=3,
        action_params={"huge": list(range(100))},
        process_finish=True,
    )
    act.action_server.server_name = "PSTAT"
    p = experiment_plan(EU, [act])
    assert p["file_type"] == "experiment_plan"
    (e,) = p["planned"]
    assert e["action_uuid"] == str(A1)
    assert e["action_order"] == 3
    assert e["server_name"] == "PSTAT"
    assert e["process_finish"] is True
    assert "action_params" not in e


def test_empty_plan_still_has_a_planned_list():
    assert sequence_plan(SU, [])["planned"] == []


@pytest.mark.asyncio
async def test_write_plan_once_writes_then_never_overwrites(tmp_path):
    async def write_atomic(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    target = tmp_path / "sub" / "260101.010101000000-seq.plan.json"
    first = sequence_plan(SU, [ShortExperimentModel(experiment_name="a")])
    assert await write_plan_once(
        target, first, write_atomic, kind="seq_plan", owner_uuid=SU
    )
    before = target.read_bytes()
    second = sequence_plan(SU, [ShortExperimentModel(experiment_name="other")])
    assert not await write_plan_once(
        target, second, write_atomic, kind="seq_plan", owner_uuid=SU
    )
    assert target.read_bytes() == before
    assert json.loads(before)["planned"][0]["experiment_name"] == "a"
