"""Resolve hook names to :class:`FinishHook` instances (spec §4.3, §4.4).

Resolution order, shared by the action host, both orchestrators, ``MicroOrch``
and both SYNC drivers:

1. a built-in, ``helao/core/hooks/builtin/<name>.py``;
2. an existing ``.py`` path;
3. ``helao/deploy/<CONFIG deployment>/processors/<name>.py``;
4. ``helao/deploy/hte/processors/<name>.py``;
5. any ``helao/deploy/*/processors/<name>.py`` (sorted, first wins).

Deployment paths are relative to the repo root, exactly as the retired
``import_postprocessors`` resolved them. The module's class named ``Hook``
(new) or ``PostProcess`` (existing) is used: a ``FinishHook`` subclass
directly, an ``HloPostProcessor``/``MetaProcessor`` subclass through the
adapters below, anything else is a startup error.
"""

__all__ = ["HloPostProcessorHook", "MetaProcessorHook", "import_hook", "load_hook_set"]

import asyncio
import importlib
import os
from glob import glob
from importlib.util import module_from_spec, spec_from_file_location
from typing import Optional

from helao.core.hooks import (
    FinishHook,
    HookConfigError,
    HookMap,
    HookSet,
    PrefinishContext,
)
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.processors import HloPostProcessor, MetaProcessor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

BUILTIN_PKG = "helao.core.hooks.builtin"


class HloPostProcessorHook(FinishHook):
    """Run an ``HloPostProcessor`` class; its result replaces ``record.files``."""

    phase = "prefinish"
    levels = ("action",)

    def __init__(self, cls):
        self.cls = cls

    async def run(self, ctx: PrefinishContext) -> None:
        # The processor joins save_root with action_output_dir itself and
        # redirects a manual action to DIAG, exactly as the finalizer's
        # ``hpp(action, save_root)`` call did.
        save_root = str(ctx.server.helaodirs.save_root)
        processor = self.cls(ctx.record, save_root)
        ctx.record.files = await asyncio.to_thread(processor.process)


class MetaProcessorHook(FinishHook):
    """Run a ``MetaProcessor`` class; it mutates the record in place."""

    phase = "prefinish"

    def __init__(self, cls):
        self.cls = cls

    async def run(self, ctx: PrefinishContext) -> None:
        await asyncio.to_thread(self.cls(ctx.record, ctx.server).process)


def _resolve_path(name: str) -> Optional[str]:
    if name.endswith(".py") and os.path.exists(name):
        return name
    deployment = (config_loader.CONFIG or {}).get("deployment", "")
    candidates = [
        (
            os.path.join("helao", "deploy", deployment, "processors", f"{name}.py")
            if deployment
            else ""
        ),
        os.path.join("helao", "deploy", "hte", "processors", f"{name}.py"),
    ]
    found = next((p for p in candidates if p and os.path.exists(p)), None)
    if found is None:
        any_paths = sorted(
            glob(os.path.join("helao", "deploy", "*", "processors", f"{name}.py"))
        )
        found = any_paths[0] if any_paths else None
    return found


def _load_module_from_path(path: str):
    mod_name = os.path.basename(path)[: -len(".py")]
    spec = spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise HookConfigError(f"cannot load hook module from {path!r}")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def import_hook(name: str) -> FinishHook:
    """Resolve ``name`` (§4.3 order) and return one hook instance."""
    mod = None
    if name.isidentifier():
        try:
            mod = importlib.import_module(f"{BUILTIN_PKG}.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{BUILTIN_PKG}.{name}":
                raise
    if mod is None:
        path = _resolve_path(name)
        if path is None:
            raise HookConfigError(
                f"hook {name!r} not found: not a built-in, not an existing .py "
                f"path, and no helao/deploy/*/processors/{name}.py"
            )
        LOGGER.info(f"Loading hook {name!r} from {path}")
        mod = _load_module_from_path(path)
    cls = getattr(mod, "Hook", None) or getattr(mod, "PostProcess", None)
    if cls is None:
        raise HookConfigError(
            f"hook module {name!r} defines neither a `Hook` nor a `PostProcess` class"
        )
    if isinstance(cls, type) and issubclass(cls, FinishHook):
        return cls()
    if isinstance(cls, type) and issubclass(cls, HloPostProcessor):
        return HloPostProcessorHook(cls)
    if isinstance(cls, type) and issubclass(cls, MetaProcessor):
        return MetaProcessorHook(cls)
    raise HookConfigError(
        f"hook {name!r}: {cls!r} is not a FinishHook, HloPostProcessor or MetaProcessor"
    )


def load_hook_set(cfg: HookMap, phase: str, level: str) -> HookSet:
    """Instantiate every hook named in ``cfg`` once and refuse a misplaced one."""
    hooks: dict[str, FinishHook] = {}
    for hook_name in cfg:
        hook = import_hook(hook_name)
        if hook.phase not in (None, phase):
            raise HookConfigError(
                f"hook {hook_name!r} is a {hook.phase} hook but is configured "
                f"for {phase}"
            )
        if hook.levels is not None and level not in hook.levels:
            raise HookConfigError(
                f"hook {hook_name!r} runs at {list(hook.levels)} level(s) but is "
                f"configured at {level!r}"
            )
        hooks[hook_name] = hook
    return HookSet(cfg=cfg, hooks=hooks)
