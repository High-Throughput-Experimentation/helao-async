"""Hook loading (spec §4.3/§4.4): resolution order, class names, adapters."""

import asyncio
import textwrap
from glob import glob
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.hooks import (
    FinishHook,
    HookConfigError,
    HookMap,
    HookSet,
    PrefinishContext,
)
from helao.core.hooks.loader import (
    HloPostProcessorHook,
    MetaProcessorHook,
    import_hook,
    load_hook_set,
)
from helao.helpers.processors import HloPostProcessor, MetaProcessor

REPO = Path(__file__).resolve().parents[3]


def _write(path: Path, body: str) -> str:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


def test_path_form_with_hook_class(tmp_path):
    p = _write(
        tmp_path / "my_hook.py",
        """
        from helao.core.hooks import FinishHook
        class Hook(FinishHook):
            blocking = False
            async def run(self, ctx):
                ctx.record.touched = True
        """,
    )
    hook = import_hook(p)
    assert isinstance(hook, FinishHook) and hook.blocking is False


def test_path_form_with_postprocess_meta_processor_is_wrapped(tmp_path):
    p = _write(
        tmp_path / "meta_pp.py",
        """
        from helao.helpers.processors import MetaProcessor
        class PostProcess(MetaProcessor):
            def process(self):
                self.meta.experiment_params["marked"] = True
        """,
    )
    hook = import_hook(p)
    assert isinstance(hook, MetaProcessorHook)


def test_hte_processors_resolve_by_bare_name():
    assert isinstance(import_hook("hlo_to_csv"), HloPostProcessorHook)
    assert isinstance(import_hook("append_params"), MetaProcessorHook)


def test_every_deployment_processor_imports_and_wraps():
    """Spec §8: all existing processors import and wrap (private ones too,
    when their deployment is checked out; none is named here, discovered
    only by globbing helao/deploy/*/processors/*.py). A processor whose
    vendor package is not installed on this OS is reported as skipped, the
    way run_tests.py reports ENV; a missing helao module is a failure.

    Controller ruling #1: assert the SPECIFIC adapter type per the module's
    PostProcess base class rather than a tautological isinstance-tuple
    check (HloPostProcessorHook | MetaProcessorHook | FinishHook always
    matches, since FinishHook is the common superclass).
    """
    all_found = sorted(
        glob(str(REPO / "helao" / "deploy" / "*" / "processors" / "*.py"))
    )
    found = [p for p in all_found if Path(p).stem != "__init__"]
    names = [Path(p).stem for p in found]
    assert names, "no processors found; run from the repo root"
    skipped = []
    for path, name in zip(found, names):
        try:
            hook = import_hook(name)
        except ModuleNotFoundError as exc:
            if (exc.name or "").startswith("helao"):
                raise
            skipped.append((name, exc.name))
            continue
        mod = _load_module_for_inspection(path, name)
        post_process = getattr(mod, "PostProcess", None)
        if post_process is not None and issubclass(post_process, HloPostProcessor):
            assert isinstance(hook, HloPostProcessorHook), name
        elif post_process is not None and issubclass(post_process, MetaProcessor):
            assert isinstance(hook, MetaProcessorHook), name
        else:
            assert isinstance(hook, FinishHook), name
    assert len(skipped) < len(names), skipped
    if skipped:
        pytest.skip(f"vendor packages missing for: {skipped} (others passed)")


def _load_module_for_inspection(path: str, name: str):
    """Load the same module a second time, purely to read its base class."""
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(f"_inspect_{name}", path)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_unknown_name_raises():
    with pytest.raises(HookConfigError) as ei:
        import_hook("definitely_not_a_hook_xyz")
    assert "definitely_not_a_hook_xyz" in str(ei.value)


def test_module_without_hook_or_postprocess_raises(tmp_path):
    p = _write(tmp_path / "empty_mod.py", "X = 1\n")
    with pytest.raises(HookConfigError) as ei:
        import_hook(p)
    assert "Hook" in str(ei.value) and "PostProcess" in str(ei.value)


def test_non_hook_class_raises(tmp_path):
    p = _write(tmp_path / "bad_cls.py", "class Hook:\n    pass\n")
    with pytest.raises(HookConfigError):
        import_hook(p)


def test_load_hook_set_refuses_hlo_processor_outside_action_level():
    with pytest.raises(HookConfigError) as ei:
        load_hook_set(
            {"hlo_to_csv": {"*": None}}, phase="prefinish", level="experiment"
        )
    assert "hlo_to_csv" in str(ei.value) and "experiment" in str(ei.value)


def test_load_hook_set_refuses_prefinish_hook_in_postfinish_phase():
    with pytest.raises(HookConfigError) as ei:
        load_hook_set(
            {"append_params": {"*": None}}, phase="postfinish", level="sequence"
        )
    assert "append_params" in str(ei.value)


def test_load_hook_set_builds_one_instance_per_hook():
    hs = load_hook_set(
        {"append_params": {"*": None}, "hlo_to_csv": {"acq": None}},
        phase="prefinish",
        level="action",
    )
    assert isinstance(hs, HookSet)
    assert list(hs.hooks) == ["append_params", "hlo_to_csv"]
    assert hs.select("acq")[1][1] is hs.hooks["hlo_to_csv"]


def test_load_hook_set_hooks_keys_match_cfg_keys():
    """Controller ruling #2: HookSet.select indexes self.hooks[hook_name]
    without a guard, so load_hook_set must build hooks with exactly the
    keys of the normalized cfg -- no more, no fewer."""
    cfg: HookMap = {"append_params": {"*": None}, "hlo_to_csv": {"acq": None}}
    hs = load_hook_set(cfg, phase="prefinish", level="action")
    assert set(hs.hooks) == set(hs.cfg)


@pytest.mark.asyncio
async def test_hlo_adapter_replaces_files_and_reads_save_root_from_server(tmp_path):
    seen = {}

    class PP(HloPostProcessor):
        def process(self):  # type: ignore[override]
            seen["output_dir"] = self.output_dir
            return ["replaced"]

    record = SimpleNamespace(
        manual_action=False,
        action_output_dir="2026/0928/seq/exp/0__0__S__a",
        files=["orig"],
    )
    server = SimpleNamespace(
        helaodirs=SimpleNamespace(save_root=str(tmp_path / "RUNS"))
    )
    await HloPostProcessorHook(PP).run(
        PrefinishContext(record=record, record_dir=tmp_path, server=server, args=None)
    )
    assert record.files == ["replaced"]
    assert seen["output_dir"] == str(tmp_path / "RUNS" / "2026/0928/seq/exp/0__0__S__a")


@pytest.mark.asyncio
async def test_meta_adapter_mutates_in_place():
    class PP(MetaProcessor):
        def process(self):
            self.meta.experiment_params["k"] = self.meta_type

    class Experiment:  # meta_type is the lowercased class name
        experiment_params = {}

    rec = Experiment()
    await MetaProcessorHook(PP).run(
        PrefinishContext(record=rec, record_dir=Path("."), server=object(), args=None)
    )
    assert rec.experiment_params == {"k": "experiment"}
