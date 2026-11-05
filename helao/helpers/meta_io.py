"""Record metadata I/O for both formats: ``.json`` (current) and ``.yml`` (legacy).

A record (``-seq/-exp/-act``), process (``-prc``) or analysis model (``-ana``)
is written as pretty JSON. A record that already exists as ``<stem>.yml`` keeps
that format when rewritten -- the in-flight rule of the JSON storage spec -- so
a run that straddles the upgrade never gains a second, ``.json`` twin.
"""

__all__ = ["dumps_meta", "meta_glob", "read_meta", "resolve_meta_path", "write_meta"]

import glob
import os
import time
from pathlib import Path
from typing import Any, Optional, Union

import orjson

from helao.helpers.file_utils import staging_path
from helao.helpers.to_json import _hlo_json_default
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import META_SUFFIXES, meta_kind

_JSON_OPTS = orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS


def _default(obj):
    """orjson fallback: sets (``HelaoDict`` keeps them) as sorted lists, then floats."""
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return _hlo_json_default(obj)


def read_meta(
    path_or_bytes: Union[str, os.PathLike, bytes], name: Optional[str] = None
) -> Any:
    """Parse a metadata file: ``.json`` with orjson, anything else as YAML.

    Args:
        path_or_bytes: A path, or the raw bytes of a zip member.
        name: The file or member name; required with bytes, where it picks the
            format.
    """
    if isinstance(path_or_bytes, (bytes, bytearray)):
        if name is None:
            raise ValueError("read_meta(bytes) needs name= to pick a format")
        if str(name).endswith(".json"):
            return orjson.loads(path_or_bytes)
        return yml_load(bytes(path_or_bytes).decode("utf-8"), fast=True)
    path = Path(path_or_bytes)
    if path.name.endswith(".json"):
        return orjson.loads(path.read_bytes())
    return yml_load(path, fast=True)


def dumps_meta(d: Any, path: Union[str, os.PathLike, None] = None) -> str:
    """Pretty JSON (2-space, UTF-8, trailing newline); YAML for a ``.yml`` ``path``."""
    if path is not None and str(path).endswith(".yml"):
        return yml_dumps(d)
    return orjson.dumps(d, default=_default, option=_JSON_OPTS).decode("utf-8") + "\n"


def resolve_meta_path(path: Union[str, os.PathLike]) -> Path:
    """The file a write to ``path`` lands in: an existing ``<stem>.yml``, else ``<stem>.json``."""
    p = Path(path)
    if p.suffix not in (".json", ".yml"):
        raise ValueError(f"not a record path (want .json or .yml): {path}")
    legacy = p.with_suffix(".yml")
    return legacy if legacy.exists() else p.with_suffix(".json")


def _replace_when_free(src, dst, timeout: float = 5.0) -> None:
    """``os.replace`` retried while Windows holds ``dst`` open (sync twin of
    ``file_utils.replace_when_free``; same backoff, shorter cap)."""
    delay, waited = 0.05, 0.0
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if waited >= timeout:
                raise
            time.sleep(delay)
            waited += delay
            delay = min(delay * 2, 1.0)


def write_meta(path: Union[str, os.PathLike], d: Any) -> Path:
    """Atomically write ``d`` to :func:`resolve_meta_path` ``(path)``; return that path."""
    target = resolve_meta_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging_path(target)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(dumps_meta(d, target))
        _replace_when_free(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return target


def meta_glob(
    root: Union[str, os.PathLike],
    kind: Union[str, tuple],
    prefix_pattern: str = "*",
    *,
    wildcard_root: bool = False,
) -> list[Path]:
    """``<root>/<prefix_pattern>-<kind>.json|.yml`` for the given kind(s), sorted.

    ``prefix_pattern`` is a glob (``**`` recurses). ``root`` is escaped by
    default -- sequence labels are free text, and a ``[`` in a directory name
    would otherwise hide its records. ``wildcard_root=True`` keeps ``root`` a
    pattern, for callers widening a legacy ``RUNS_*`` segment.

    One glob per suffix, then filtered by :func:`meta_kind`, so a data header
    (``X.meta.json``) or analysis output never matches.
    """
    kinds = {kind} if isinstance(kind, str) else set(kind)
    base = str(root) if wildcard_root else glob.escape(str(root))
    found = {
        Path(p)
        for suffix in META_SUFFIXES
        for p in glob.glob(
            os.path.join(base, f"{prefix_pattern}-*{suffix}"), recursive=True
        )
        if meta_kind(p) in kinds
    }
    return sorted(found)
