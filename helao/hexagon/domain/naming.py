"""Pure naming grammar (spec §4.2.3, §5.1-§5.2).

Sources of truth mirrored here:
- meta yml filename: base_meta_writer.py:98/124/146
  ``<obj_timestamp:%y%m%d.%H%M%S%f>-{act,exp,seq}.json``
- streamed/one-shot data filename: active_data_file.py:139
  ``{abbr}-{orch_submit_order}.{action_order}.{action_retry}.{action_split}__{filenum}.jsonl``
- file-conn keys: base_meta_writer.py:154-172 (md5 -> UUID; default key =
  md5(str(None)) — 34 call sites)
- manual-run redirection: re-exported from helao.core.models.run_dir so the
  legacy write sites (base_meta_writer.py, active_data_file.py, ...) and the
  native ones share one implementation rather than importing hexagon from core
- nosync flag: active_data_file.py:154

Dir naming (sequence/experiment/action output dirs) is intentionally NOT
duplicated: it lives on the reused premodels (get_sequence_dir /
get_experiment_dir / get_action_dir, D8) and is pinned by tests/test_naming.py.
"""

import hashlib
from datetime import datetime
from typing import Optional
from uuid import UUID

from helao.core.models.run_dir import redirect_manual_dir

__all__ = [
    "DATA_SUFFIX",
    "HEADER_SUFFIX",
    "META_KINDS",
    "META_SUFFIXES",
    "META_YML_TS_FMT",
    "RECORD_KINDS",
    "data_sibling",
    "data_stem",
    "dflt_file_conn_key",
    "hlo_filename",
    "is_nosync_file",
    "meta_kind",
    "meta_yml_filename",
    "new_file_conn_key",
    "redirect_manual_dir",
]

META_YML_TS_FMT = "%y%m%d.%H%M%S%f"

#: The three record kinds the sync hierarchy is built from.
RECORD_KINDS = ("seq", "exp", "act")
#: Every ``*-<kind>.<suffix>`` metadata file: records, processes, analysis models.
META_KINDS = ("seq", "exp", "act", "prc", "ana")
#: Metadata suffixes, current format first.
META_SUFFIXES = (".json", ".yml")
#: A data pair is ``X.meta.json`` (header, optional) + ``X.jsonl`` (rows).
DATA_SUFFIX = ".jsonl"
HEADER_SUFFIX = ".meta.json"
#: Longest first, so ``X.hlo.json`` is never read as ``X.hlo`` + ``.json``.
_DATA_SUFFIXES = (".hlo.json", HEADER_SUFFIX, DATA_SUFFIX, ".hlo")


def _basename(path) -> str:
    """Last path element of a ``/`` or ``\\`` separated path (pure, no os.path)."""
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def meta_kind(path) -> Optional[str]:
    """``seq``/``exp``/``act``/``prc``/``ana`` from ``*-<kind>.json|.yml``, else None.

    A data header ``X.meta.json`` and an analysis output ``<uuid>_output_<g>.json``
    carry no ``-<kind>`` ending and return None.
    """
    name = _basename(path)
    for suffix in META_SUFFIXES:
        if name.endswith(suffix):
            _, sep, kind = name[: -len(suffix)].rpartition("-")
            return kind if sep and kind in META_KINDS else None
    return None


def data_stem(path) -> str:
    """Basename with ``.hlo.json``/``.meta.json``/``.jsonl``/``.hlo`` stripped."""
    name = _basename(path)
    for suffix in _DATA_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def data_sibling(path, suffix: str) -> str:
    """``path`` in the same directory with its data suffix replaced by ``suffix``."""
    p = str(path)
    return p[: len(p) - len(_basename(p))] + data_stem(p) + suffix


def meta_yml_filename(obj_timestamp: datetime, kind: str) -> str:
    """Return ``<ts>-{kind}.json`` for kind in {'act','exp','seq'}.

    The name is historical; records are JSON since the storage-format switch.
    """
    if kind not in RECORD_KINDS:
        raise ValueError(f"unknown meta kind {kind!r}; expected one of {RECORD_KINDS}")
    return f"{obj_timestamp.strftime(META_YML_TS_FMT)}-{kind}.json"


def hlo_filename(
    action_abbr: str,
    orch_submit_order: int,
    action_order: int,
    action_retry: int,
    action_split: int,
    filenum: int,
    file_ext: str = "jsonl",
) -> str:
    """The streamed/one-shot data filename (active_data_file.py:139).

    ``filenum`` is the index of the file_conn_key in ``action.file_conn_keys``.
    """
    return (
        f"{action_abbr}-{orch_submit_order}.{action_order}."
        f"{action_retry}.{action_split}__{filenum}.{file_ext}"
    )


def new_file_conn_key(key: str) -> UUID:
    """UUID derived from the MD5 hash of ``key`` (base_meta_writer.py:154)."""
    return UUID(hashlib.md5(key.encode("utf-8")).hexdigest())


def dflt_file_conn_key() -> UUID:
    """The default file-connection key: ``md5(str(None))``."""
    return new_file_conn_key(str(None))


def is_nosync_file(filename: str, sync_data: bool) -> bool:
    """FileInfo.nosync rule: True for a data file (``.hlo``/``.jsonl``) when sync_data is off."""
    return (not sync_data) and filename.endswith((".hlo", DATA_SUFFIX))
