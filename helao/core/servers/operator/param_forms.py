"""Pure parameter-form logic shared by the operator UIs.

Both the Bokeh operator and the Reflex operator have to turn a sequence or
experiment library into selectable items with typed, documented parameters.
That means introspecting the callables and parsing their Google-style ``Args:``
sections -- a few hundred lines of fiddly logic that would drift immediately if
each UI carried its own copy.

Nothing here imports a UI toolkit, so it is testable directly rather than
through UI callbacks, which is how ``bokeh_operator`` reached it before.
"""

__all__ = ["build_lib", "parse_arg_docs", "version_hint_parts", "clear_lib_cache"]

import inspect
import json
import re
from enum import Enum
from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Introspected sequence/experiment dropdown data, keyed by the inputs that can
#: change it. The table is a pure function of the library callables, their file
#: hashes, and the config-level default overlay -- all fixed for a running
#: process -- so it is cached across UI sessions. Only plain data is cached
#: (dicts + name list), never UI models.
_LIB_TABLE_CACHE: dict = {}


def clear_lib_cache() -> None:
    """Drop the introspection cache. For tests that rebuild a library."""
    _LIB_TABLE_CACHE.clear()


def build_lib(
    lib: dict,
    filter_type,
    config_key: str,
    world_cfg: dict,
    loaded_config_path,
    model_class,
    name_field: str,
    codehash_map: Optional[dict] = None,
) -> tuple:
    """Inspect ``lib`` and return ``(items, select_list)`` for the dropdowns.

    Drops parameters whose annotation matches ``filter_type`` (e.g. the
    ``Experiment`` arg of experiment functions) and overlays defaults from the
    world config under ``config_key``.

    Args:
        lib: Mapping of name to library callable.
        filter_type: Annotation whose parameters are framework-injected and
            must not be prompted for. ``None`` filters nothing.
        config_key: World-config section holding default overrides.
        world_cfg: The loaded world config.
        loaded_config_path: Path of the loaded config. Part of the cache key so
            two configs in one process cannot serve each other's defaults.
        model_class: Pydantic model describing one item.
        name_field: ``"sequence_name"`` or ``"experiment_name"``.
        codehash_map: Optional name-to-hash map for the version hint.

    Returns:
        tuple: ``(items, select_list)``. Both are fresh copies, so a caller
        mutating them cannot poison the cache.
    """
    items = []
    select_list = []
    codehash_map = codehash_map or {}
    version_attr = name_field.replace("_name", "_version")

    cache_key = (
        loaded_config_path,
        config_key,
        name_field,
        tuple(lib),
        tuple(sorted(codehash_map.items())),
    )
    cached = _LIB_TABLE_CACHE.get(cache_key)
    if cached is not None:
        cached_items, cached_select = cached
        return [dict(it) for it in cached_items], list(cached_select)

    LOGGER.info(f"found {name_field.replace('_name', '')}s: {list(lib)}")
    for i, name in enumerate(lib):
        func = lib[name]
        tmpdoc = func.__doc__ or ""
        argspec = inspect.getfullargspec(func)
        tmpargs = list(argspec.args)
        tmpdefs = list(argspec.defaults or [])
        tmpdefs = [x.value if isinstance(x, Enum) else x for x in tmpdefs]
        tmptypes = [argspec.annotations.get(k, "unspecified") for k in tmpargs]

        if filter_type is not None:
            idxlist = [
                idx
                for idx, arg in enumerate(tmpargs)
                if argspec.annotations.get(arg) == filter_type
            ]
            for j, idx in enumerate(idxlist):
                if len(tmpargs) == len(tmpdefs):
                    tmpargs.pop(idx - j)
                    tmpdefs.pop(idx - j)
                    tmptypes.pop(idx - j)
                else:
                    tmpargs.pop(idx - j)
                    tmptypes.pop(idx - j)

        cfg_defs = world_cfg.get(config_key, {})
        tmpdefs = [cfg_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
        for t in tmpdefs:
            try:
                if isinstance(t, Enum):
                    t = json.dumps(t.value)
                else:
                    t = json.dumps(t)
            except Exception:
                t = ""
        codehash = codehash_map.get(name)
        items.append(
            model_class(
                index=i,
                **{name_field: name},
                doc=tmpdoc,
                args=tuple(tmpargs),
                defaults=tuple(tmpdefs),
                argtypes=tuple(tmptypes),
                version=getattr(func, version_attr, None),
                codehash=str(codehash)[:8] if codehash else None,
            ).model_dump()
        )
        select_list.append(name)
    _LIB_TABLE_CACHE[cache_key] = (
        [dict(it) for it in items],
        list(select_list),
    )
    return items, select_list


def parse_arg_docs(doc: str) -> dict:
    """Parse a Google-style ``Args:`` section into ``{arg_name: description}``.

    Recognises ``name: text`` and ``name (type): text`` entries, folds
    indented continuation lines into the preceding entry, and stops at the
    next section header or a blank line. ``*args``/``**kwargs`` are skipped.
    """
    if not doc:
        return {}
    header_re = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.I)
    section_re = re.compile(
        r"^\s*(Returns?|Raises|Yields?|Examples?|Notes?|Attributes|"
        r"Args|Arguments|Parameters)\s*:\s*$",
        re.I,
    )
    arg_re = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
    descs = {}
    in_args = False
    cur = None
    for line in doc.splitlines():
        if not in_args:
            if header_re.match(line):
                in_args = True
            continue
        if line.strip() == "":
            break
        if section_re.match(line):
            break
        if re.match(r"^\s*\*", line):  # *args / **kwargs: skip, end current
            cur = None
            continue
        m = arg_re.match(line)
        if m:
            cur = m.group(1)
            descs[cur] = m.group(2).strip()
        elif cur is not None:
            descs[cur] = f"{descs[cur]} {line.strip()}".strip()
    return descs


def version_hint_parts(item: dict) -> list:
    """Return the ``["v2", "abc123"]`` parts of a selector's version hint.

    Plain strings, no markup and no escaping: the Bokeh operator wraps and
    escapes these for a ``Div``, while the Reflex operator renders them as
    text, where markup would simply be visible.
    """
    parts = []
    version = item.get("version")
    if version is not None:
        parts.append(f"v{version}")
    codehash = item.get("codehash")
    if codehash:
        parts.append(str(codehash))
    return parts
