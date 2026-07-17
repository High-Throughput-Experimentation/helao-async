"""Artifact-content assembly = model -> clean_dict, file_type first (D8/§5.2)."""

from helao.hexagon.domain import assembly
from helao.hexagon.domain.models import Action, Experiment, Sequence


def _mk_action() -> Action:
    act = Action(action_name="acquire", action_params={"rate": 1.5, "n": 3})
    act.action_server.server_name = "SIM"
    act.action_server.machine_name = "testbox"
    return act


def test_assemble_act_has_file_type_first_and_clean_dict_body():
    act = _mk_action()
    act.init_act()  # manual promotion path fills seq/exp synthetics
    out = assembly.assemble_act(act)
    assert list(out.keys())[0] == "file_type"
    assert out["file_type"] == "action"
    # action_params relayed bit-exact (D7)
    assert out["action_params"] == {"rate": 1.5, "n": 3}
    # clean_dict drops Nones: no None values anywhere at top level
    assert all(v is not None for v in out.values())


def test_assemble_exp_and_seq_kinds():
    seq = Sequence(sequence_name="s", sequence_label="l")
    seq.init_seq()
    exp = Experiment(experiment_name="e")
    exp.sequence_output_dir = seq.sequence_output_dir
    exp.sequence_timestamp = seq.sequence_timestamp
    exp.init_exp()
    e = assembly.assemble_exp(exp)
    s = assembly.assemble_seq(seq)
    assert list(e.keys())[0] == "file_type" and e["file_type"] == "experiment"
    assert list(s.keys())[0] == "file_type" and s["file_type"] == "sequence"


def test_assemble_process_strips_private_keys():
    # DRIFT vs brief: sync_driver.py:1698/1726 write
    # `ProcessModel.model_validate(meta).clean_dict(strip_private=True)`
    # directly to the -prc.yml -- there is no `{"file_type": "process"}`
    # prefix step like write_act/write_exp/write_seq have. The legacy bytes
    # win: assemble_process must NOT add a file_type key.
    meta = {
        "process_uuid": "b0e9b5a6-6e50-44d8-8f10-4d54a297c742",
        "technique_name": "CA",
        "_private_note": "dropped",
    }
    out = assembly.assemble_process(meta)
    assert "file_type" not in out
    assert out["technique_name"] == "CA"
    assert "_private_note" not in out
