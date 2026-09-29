"""Config surface of the finish hooks (spec §3): shapes, aliases, refusals."""

import logging

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


def test_prefinish_alias_translates_and_warns(caplog):
    caplog.set_level(logging.WARNING)
    out = prefinish_config(
        {"hlo_postprocess_libs": ["hlo_to_csv", "spec_melt_wls"]},
        "prefinish_hooks",
        "hlo_postprocess_libs",
        "SPEC_R",
    )
    assert out == {"hlo_to_csv": {"*": None}, "spec_melt_wls": {"*": None}}
    assert "hlo_postprocess_libs" in caplog.text and "deprecated" in caplog.text


def test_prefinish_new_key_is_normalized_without_warning(caplog):
    caplog.set_level(logging.WARNING)
    out = prefinish_config(
        {"prefinish_hooks": {"hlo_to_csv": ["acquire"]}},
        "prefinish_hooks",
        "hlo_postprocess_libs",
        "SPEC_R",
    )
    assert out == {"hlo_to_csv": {"acquire": None}}
    assert "deprecated" not in caplog.text


def test_prefinish_old_and_new_together_refused_naming_both():
    with pytest.raises(HookConfigError) as ei:
        prefinish_config(
            {"prefinish_hooks": {"a": ["*"]}, "hlo_postprocess_libs": ["a"]},
            "prefinish_hooks",
            "hlo_postprocess_libs",
            "SPEC_R",
        )
    msg = str(ei.value)
    assert (
        "prefinish_hooks" in msg and "hlo_postprocess_libs" in msg and "SPEC_R" in msg
    )


def test_prefinish_absent_is_empty():
    assert prefinish_config({}, "prefinish_hooks", "hlo_postprocess_libs", "X") == {}


def test_postfinish_default_chain_without_analysis():
    out = postfinish_config(None, None, "SYNC")
    assert tuple(out) == LEVELS
    assert out == {level: {"s3_upload": {"*": None}} for level in LEVELS}


def test_postfinish_default_chain_adds_dispatch_analysis_alias(caplog):
    caplog.set_level(logging.WARNING)
    ana = {"server_key": "ANA", "endpoint": "e", "host": "h", "port": 1}
    out = postfinish_config(None, {"my_seq": ana}, "SYNC")
    assert out["sequence"] == {
        "s3_upload": {"*": None},
        "dispatch_analysis": {"my_seq": ana},
    }
    assert out["action"] == {"s3_upload": {"*": None}}
    assert "auto_analyze_sequences" in caplog.text and "deprecated" in caplog.text


def test_postfinish_empty_alias_is_ignored(caplog):
    caplog.set_level(logging.WARNING)
    assert postfinish_config(None, {}, "SYNC")["sequence"] == {"s3_upload": {"*": None}}
    assert "deprecated" not in caplog.text


def test_postfinish_explicit_owns_the_chain():
    out = postfinish_config({"action": {"s3_upload": ["*"]}}, None, "SYNC")
    assert out == {
        "action": {"s3_upload": {"*": None}},
        "experiment": {},
        "sequence": {},
    }


def test_postfinish_stray_level_refused():
    with pytest.raises(HookConfigError) as ei:
        postfinish_config({"action": {}, "process": {"x": ["*"]}}, None, "SYNC")
    assert "process" in str(ei.value)


def test_postfinish_old_and_new_together_refused():
    with pytest.raises(HookConfigError) as ei:
        postfinish_config(
            {"sequence": {"s3_upload": ["*"]}}, {"s": {"server_key": "A"}}, "SYNC"
        )
    msg = str(ei.value)
    assert "auto_analyze_sequences" in msg and "postfinish_hooks" in msg


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
