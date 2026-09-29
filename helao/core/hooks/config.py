"""Config normalization, aliases and validation for finish hooks (spec §3).

Every violation raises :class:`HookConfigError` naming the offending key: a
bad hook config never degrades to "no hooks" (spec §3.3).
"""

__all__ = [
    "find_orchestrator_entry",
    "normalize_hook_map",
    "postfinish_config",
    "prefinish_config",
]

from typing import Any, Optional

from helao.core.hooks import LEVELS, HookConfigError, HookMap
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def normalize_hook_map(raw: Any, key: str) -> HookMap:
    """``{hook: [names] | {name: args}}`` -> :data:`HookMap`, or raise naming ``key``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HookConfigError(
            f"{key} must be a mapping of hook name -> list of record names, "
            f"got {type(raw).__name__}"
        )
    out: HookMap = {}
    for hook_name, value in raw.items():
        if not isinstance(hook_name, str) or not hook_name:
            raise HookConfigError(
                f"{key}: hook names must be non-empty strings, got {hook_name!r}"
            )
        shape = (
            f"{key}.{hook_name} must be a non-empty list of record names "
            "(or '*'), or a mapping of record name -> mapping of args"
        )
        if isinstance(value, list):
            if not value or not all(isinstance(v, str) and v for v in value):
                raise HookConfigError(shape)
            out[hook_name] = {v: None for v in value}
        elif isinstance(value, dict):
            if not value or not all(
                isinstance(k, str) and k and isinstance(v, dict)
                for k, v in value.items()
            ):
                raise HookConfigError(shape)
            out[hook_name] = dict(value)
        else:
            raise HookConfigError(shape)
    return out


def prefinish_config(server_cfg: dict, key: str, alias: str, label: str) -> HookMap:
    """The pre-finish hook map of one server entry.

    ``key`` is the new dict key (``prefinish_hooks`` /
    ``prefinish_experiment_hooks`` / ``prefinish_sequence_hooks``); ``alias``
    the retired list key it replaces (``hlo_postprocess_libs`` /
    ``exp_postprocess_libs`` / ``seq_postprocess_libs``). An alias translates
    to ``{name: ["*"]}`` with one deprecation warning; both keys together are
    refused (spec §3.1). ``label`` names the server in messages.
    """
    server_cfg = server_cfg or {}
    if key in server_cfg and alias in server_cfg:
        raise HookConfigError(
            f"{label}: {alias!r} and {key!r} are both set; {alias!r} is a "
            f"deprecated alias of {key!r}, keep one"
        )
    if alias in server_cfg:
        names = server_cfg.get(alias) or []
        if not isinstance(names, list) or not all(
            isinstance(n, str) and n for n in names
        ):
            raise HookConfigError(f"{label}.{alias} must be a list of hook names")
        LOGGER.warning(
            f"{label}: {alias!r} is deprecated; use {key}: {{<hook>: ['*']}}"
        )
        return {n: {"*": None} for n in names}
    return normalize_hook_map(server_cfg.get(key), f"{label}.{key}")


def postfinish_config(
    postfinish_hooks: Any, auto_analyze: Any, label: str
) -> dict[str, HookMap]:
    """The post-finish chain per level for the SYNC entry (spec §3, §3.2).

    ``postfinish_hooks`` absent -> the default chain equivalent to today:
    ``s3_upload: ["*"]`` at every level, plus ``dispatch_analysis`` at
    sequence level translated from the ``auto_analyze_sequences`` params
    alias when that is present (one deprecation warning). A present
    ``postfinish_hooks`` owns the whole chain (spec D4); it may only have the
    keys in :data:`LEVELS`, and setting it together with the alias is refused.
    """
    if postfinish_hooks is not None and auto_analyze:
        raise HookConfigError(
            f"{label}: params.auto_analyze_sequences and postfinish_hooks are both "
            "set; auto_analyze_sequences is a deprecated alias of "
            "postfinish_hooks.sequence.dispatch_analysis, keep one"
        )
    if postfinish_hooks is None:
        chain: dict[str, HookMap] = {
            level: {"s3_upload": {"*": None}} for level in LEVELS
        }
        if auto_analyze:
            if not isinstance(auto_analyze, dict) or not all(
                isinstance(k, str) and isinstance(v, dict)
                for k, v in auto_analyze.items()
            ):
                raise HookConfigError(
                    f"{label}.params.auto_analyze_sequences must map sequence "
                    "name -> analysis config mapping"
                )
            LOGGER.warning(
                f"{label}: params.auto_analyze_sequences is deprecated; use "
                "postfinish_hooks.sequence.dispatch_analysis"
            )
            chain["sequence"]["dispatch_analysis"] = dict(auto_analyze)
        return chain
    if not isinstance(postfinish_hooks, dict):
        raise HookConfigError(
            f"{label}.postfinish_hooks must be a mapping with keys {list(LEVELS)}"
        )
    unknown = [k for k in postfinish_hooks if k not in LEVELS]
    if unknown:
        raise HookConfigError(
            f"{label}.postfinish_hooks has unknown keys {unknown}; "
            f"allowed: {list(LEVELS)}"
        )
    return {
        level: normalize_hook_map(
            postfinish_hooks.get(level), f"{label}.postfinish_hooks.{level}"
        )
        for level in LEVELS
    }


def find_orchestrator_entry(world_cfg: Optional[dict]) -> dict:
    """The first ``group: orchestrator`` server entry of a world config, or ``{}``.

    ``MicroOrch`` reads its experiment/sequence pre-finish hooks from here
    (spec §7.3).
    """
    servers = (world_cfg or {}).get("servers") or {}
    for entry in servers.values():
        if isinstance(entry, dict) and entry.get("group") == "orchestrator":
            return entry
    return {}
