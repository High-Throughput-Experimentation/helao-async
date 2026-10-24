"""Config normalization and validation for finish hooks (spec §3).

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


# Removed list keys; a config still using one is refused rather than run
# without hooks (spec §3.3).
_RETIRED_PREFINISH = {
    "prefinish_hooks": "hlo_postprocess_libs",
    "prefinish_experiment_hooks": "exp_postprocess_libs",
    "prefinish_sequence_hooks": "seq_postprocess_libs",
}


def prefinish_config(server_cfg: dict, key: str, label: str) -> HookMap:
    """The pre-finish hook map of one server entry.

    ``key`` is the dict key (``prefinish_hooks`` / ``prefinish_experiment_hooks``
    / ``prefinish_sequence_hooks``). ``label`` names the server in messages.
    """
    server_cfg = server_cfg or {}
    retired = _RETIRED_PREFINISH.get(key)
    if retired and retired in server_cfg:
        raise HookConfigError(
            f"{label}: {retired!r} was removed; use {key}: {{<hook>: ['*']}}"
        )
    return normalize_hook_map(server_cfg.get(key), f"{label}.{key}")


def postfinish_config(
    postfinish_hooks: Any, label: str, params: Optional[dict] = None
) -> dict[str, HookMap]:
    """The post-finish chain per level for the SYNC entry (spec §3, §3.2).

    ``postfinish_hooks`` absent -> the default chain, ``s3_upload: ["*"]`` at
    every level. A present ``postfinish_hooks`` owns the whole chain (spec D4);
    it may only have the keys in :data:`LEVELS`. ``params`` (the SYNC server
    params) is checked for the removed ``auto_analyze_sequences`` key.
    """
    if params and "auto_analyze_sequences" in params:
        raise HookConfigError(
            f"{label}: params.auto_analyze_sequences was removed; use "
            "postfinish_hooks.sequence.dispatch_analysis (rename each block's "
            "analysis_params to params)"
        )
    if postfinish_hooks is None:
        return {level: {"s3_upload": {"*": None}} for level in LEVELS}
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
    chain = {
        level: normalize_hook_map(
            postfinish_hooks.get(level), f"{label}.postfinish_hooks.{level}"
        )
        for level in LEVELS
    }
    # an old auto_analyze_sequences block moved across verbatim would run with
    # default analysis params; refuse the removed key instead
    for level, hook_map in chain.items():
        for name, args in (hook_map.get("dispatch_analysis") or {}).items():
            if isinstance(args, dict) and "analysis_params" in args:
                raise HookConfigError(
                    f"{label}.postfinish_hooks.{level}.dispatch_analysis: block "
                    f"{name!r} uses removed 'analysis_params'; rename to 'params'"
                )
    return chain


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
