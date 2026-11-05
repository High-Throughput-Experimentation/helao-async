"""Config surface of the finish hooks (spec §3): shapes, refusals."""

import pytest

from helao.core.hooks import FinishHook, HookConfigError, HookSet, LEVELS
from helao.core.hooks.config import (
    find_orchestrator_entry,
    normalize_hook_map,
    postfinish_config,
    prefinish_config,
)


class _Noop(FinishHook):
    async def run(self, ctx):
        return None


def test_list_value_expands_to_none_args_in_order():
    out = normalize_hook_map({"b": ["x", "*"], "a": ["y"]}, key="k")
    assert list(out) == ["b", "a"]
    assert out == {"b": {"x": None, "*": None}, "a": {"y": None}}


def test_mapping_value_keeps_per_name_args():
    out = normalize_hook_map({"h": {"seq1": {"p": 1}}}, key="k")
    assert out == {"h": {"seq1": {"p": 1}}}


def test_none_is_empty():
    assert normalize_hook_map(None, key="k") == {}


@pytest.mark.parametrize(
    "raw",
    [
        ["not", "a", "dict"],
        {"h": "x"},
        {"h": [1]},
        {"h": []},
        {"h": {"n": 1}},
        {"": ["*"]},
    ],
)
def test_bad_shapes_raise_naming_the_key(raw):
    with pytest.raises(HookConfigError) as ei:
        normalize_hook_map(raw, key="SPEC_R.prefinish_hooks")
    assert "SPEC_R.prefinish_hooks" in str(ei.value)


def test_prefinish_key_is_normalized():
    out = prefinish_config(
        {"prefinish_hooks": {"hlo_to_csv": ["acquire"]}},
        "prefinish_hooks",
        "SPEC_R",
    )
    assert out == {"hlo_to_csv": {"acquire": None}}


def test_prefinish_absent_is_empty():
    assert prefinish_config({}, "prefinish_hooks", "X") == {}


def test_postfinish_default_chain_without_analysis():
    out = postfinish_config(None, "SYNC")
    assert tuple(out) == LEVELS
    assert out == {level: {"s3_upload": {"*": None}} for level in LEVELS}


def test_postfinish_explicit_owns_the_chain():
    out = postfinish_config({"action": {"s3_upload": ["*"]}}, "SYNC")
    assert out == {
        "action": {"s3_upload": {"*": None}},
        "experiment": {},
        "sequence": {},
    }


def test_postfinish_stray_level_refused():
    with pytest.raises(HookConfigError) as ei:
        postfinish_config({"action": {}, "process": {"x": ["*"]}}, "SYNC")
    assert "process" in str(ei.value)


def test_hookset_select_exact_then_star_in_config_order():
    a, b, c = _Noop(), _Noop(), _Noop()
    hs = HookSet(
        cfg={"a": {"seq1": {"x": 1}}, "b": {"*": None}, "c": {"other": None}},
        hooks={"a": a, "b": b, "c": c},
    )
    assert hs.select("seq1") == [("a", a, {"x": 1}), ("b", b, None)]
    assert hs.select("zzz") == [("b", b, None)]
    assert HookSet.empty().select("seq1") == []


def test_hookset_star_args_apply_when_name_missing():
    a = _Noop()
    hs = HookSet(cfg={"a": {"*": {"d": 1}, "seq1": {"d": 2}}}, hooks={"a": a})
    assert hs.select("seq1") == [("a", a, {"d": 2})]
    assert hs.select("seq2") == [("a", a, {"d": 1})]


def test_find_orchestrator_entry():
    world = {
        "servers": {
            "SIM": {"group": "action"},
            "ORCH": {"group": "orchestrator", "x": 1},
        }
    }
    assert find_orchestrator_entry(world) == {"group": "orchestrator", "x": 1}
    assert find_orchestrator_entry({}) == {}
    assert find_orchestrator_entry(None) == {}


@pytest.mark.parametrize(
    "key,retired",
    [
        ("prefinish_hooks", "hlo_postprocess_libs"),
        ("prefinish_experiment_hooks", "exp_postprocess_libs"),
        ("prefinish_sequence_hooks", "seq_postprocess_libs"),
    ],
)
def test_a_removed_prefinish_list_key_is_refused_not_ignored(key, retired):
    with pytest.raises(HookConfigError, match=retired):
        prefinish_config({retired: ["append_params"]}, key, "SRV")


def test_removed_auto_analyze_sequences_is_refused_not_ignored():
    with pytest.raises(HookConfigError, match="auto_analyze_sequences"):
        postfinish_config(None, "SYNC", params={"auto_analyze_sequences": {}})
    assert postfinish_config(None, "SYNC", params={"other": 1})  # default chain


def test_a_dispatch_analysis_block_with_analysis_params_is_refused():
    hooks = {"sequence": {"dispatch_analysis": {"SEQ": {"analysis_params": {}}}}}
    with pytest.raises(HookConfigError, match="analysis_params"):
        postfinish_config(hooks, "SYNC")
    ok = {"sequence": {"dispatch_analysis": {"SEQ": {"params": {}}}}}
    assert postfinish_config(ok, "SYNC")["sequence"]["dispatch_analysis"]
