"""Extension-dispatched dataset readers for the data browser.

A *locator* identifies one column-bearing data file:

- loose file: an absolute filesystem path, e.g. ``/data/.../cv_data.hlo``
- zip member: ``"zip::<zip_path>::<member_name>"``

``read_dataset(locator, fmt)`` returns ``(meta, data)`` where ``meta`` is a dict
of header/metadata and ``data`` is ``{column_name: list}``.
"""
import io
import json
import os
import zipfile
from typing import Optional, Tuple

import pyarrow.parquet as pq

from helao.framework.adapters.loaders.hlo_loader import read_hlo_bytes

ZIP_PREFIX = "zip::"
ZIP_SEP = "::"


def make_zip_locator(zip_path: str, member: str) -> str:
    return f"{ZIP_PREFIX}{zip_path}{ZIP_SEP}{member}"


def parse_locator(locator: str) -> tuple:
    """Return ('file', path) or ('zip', zip_path, member)."""
    if locator.startswith(ZIP_PREFIX):
        zip_path, member = locator[len(ZIP_PREFIX):].split(ZIP_SEP, 1)
        return ("zip", zip_path, member)
    return ("file", locator)


def _read_bytes(locator: str) -> Tuple[str, bytes]:
    """Return (file_name, content_bytes) for any locator."""
    parsed = parse_locator(locator)
    if parsed[0] == "zip":
        _, zip_path, member = parsed
        with zipfile.ZipFile(zip_path) as zf:
            return os.path.basename(member), zf.read(member)
    with open(parsed[1], "rb") as f:
        return os.path.basename(parsed[1]), f.read()


def read_dataset(locator: str, fmt: Optional[str] = None) -> Tuple[dict, dict]:
    """Read any supported column-bearing file into (meta, {column: list})."""
    file_name, content = _read_bytes(locator)
    if fmt is None:
        fmt = os.path.splitext(file_name)[1].lower().lstrip(".")
    if fmt == "hlo":
        return read_hlo_bytes(content)
    if fmt == "json":
        return _read_json(content)
    if fmt == "parquet":
        return _read_parquet(content)
    raise ValueError(f"unsupported data format: {fmt!r} ({file_name})")


def _read_json(content: bytes) -> Tuple[dict, dict]:
    """Parse a JSON data file into (meta, {column: list})."""
    obj = json.loads(content.decode("utf-8"))
    if isinstance(obj, dict):
        data = {k: list(v) for k, v in obj.items() if isinstance(v, (list, tuple))}
        meta = {k: v for k, v in obj.items() if k not in data}
        return meta, data
    if isinstance(obj, list):
        cols = {}
        for rec in obj:
            if isinstance(rec, dict):
                for k, v in rec.items():
                    cols.setdefault(k, []).append(v)
        return {}, cols
    return {}, {}


def _read_parquet(content: bytes) -> Tuple[dict, dict]:
    table = pq.read_table(io.BytesIO(content))
    data = {name: table.column(name).to_pylist() for name in table.column_names}
    meta = {}
    raw = (table.schema.metadata or {}).get(b"helao_metadata")
    if raw:
        try:
            meta = json.loads(raw.decode("utf-8"))
        except Exception:
            meta = {}
    return meta, data
