"""Pure naming grammar (spec §4.2.3, §5.1-§5.2).

Sources of truth mirrored here:
- meta yml filename: base_meta_writer.py:98/124/146
  ``<obj_timestamp:%y%m%d.%H%M%S%f>-{act,exp,seq}.yml``
- streamed/one-shot data filename: active_data_file.py:139
  ``{abbr}-{orch_submit_order}.{action_order}.{action_retry}.{action_split}__{filenum}.{ext}``
- file-conn keys: base_meta_writer.py:154-172 (md5 -> UUID; default key =
  md5(str(None)) — 34 call sites)
- manual-run redirection RUNS_ACTIVE -> RUNS_DIAG: centralized here (legacy
  copy-pastes the string replace at 8+ write sites, e.g. base_meta_writer.py:94
  / active_data_file.py:257/308/415/441)
- nosync flag: active_data_file.py:154

Dir naming (sequence/experiment/action output dirs) is intentionally NOT
duplicated: it lives on the reused premodels (get_sequence_dir /
get_experiment_dir / get_action_dir, D8) and is pinned by tests/test_naming.py.
"""

import hashlib
from datetime import datetime
from uuid import UUID

__all__ = [
    "META_YML_TS_FMT",
    "dflt_file_conn_key",
    "hlo_filename",
    "is_nosync_file",
    "meta_yml_filename",
    "new_file_conn_key",
    "redirect_manual_dir",
]

META_YML_TS_FMT = "%y%m%d.%H%M%S%f"

_META_KINDS = ("act", "exp", "seq")


def meta_yml_filename(obj_timestamp: datetime, kind: str) -> str:
    """Return ``<ts>-{kind}.yml`` for kind in {'act','exp','seq'}."""
    if kind not in _META_KINDS:
        raise ValueError(f"unknown meta kind {kind!r}; expected one of {_META_KINDS}")
    return f"{obj_timestamp.strftime(META_YML_TS_FMT)}-{kind}.yml"


def hlo_filename(
    action_abbr: str,
    orch_submit_order: int,
    action_order: int,
    action_retry: int,
    action_split: int,
    filenum: int,
    file_ext: str = "hlo",
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
    md5_hash = hashlib.md5()
    md5_hash.update(key.encode("utf-8"))
    return UUID(md5_hash.hexdigest())


def dflt_file_conn_key() -> UUID:
    """The default file-connection key: ``md5(str(None))``."""
    return new_file_conn_key(str(None))


def redirect_manual_dir(path: str) -> str:
    """Manual-run redirection: substitute RUNS_ACTIVE -> RUNS_DIAG.

    Mirrors ``save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)``
    literal string substitution (spec §5.1); this is the single domain home
    for the manual variant, centralizing what legacy copy-pastes at 8+ write
    sites.
    """
    return path.replace("RUNS_ACTIVE", "RUNS_DIAG")


def is_nosync_file(filename: str, sync_data: bool) -> bool:
    """FileInfo.nosync rule: True for ``.hlo`` files when sync_data is off."""
    return (not sync_data) and filename.endswith(".hlo")
