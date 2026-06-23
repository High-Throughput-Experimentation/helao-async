"""Readers and conversion helpers for the HELAO .hlo data file format.

Direct port from helao/helpers/hlo_data.py with import paths updated to
use helao.framework.support.yml_tools instead of helao.helpers.yml_tools.
HelaoData lazy re-export is omitted (out of SP6 scope).
"""
__all__ = [
    "read_hlo",
    "read_hlo_stream",
    "read_hlo_bytes",
    "read_hlo_header",
    "read_hlo_data_chunks",
    "hlo_to_parquet",
    "read_helao_metadata",
]

import json
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Tuple

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML

from helao.framework.support.yml_tools import yml_load

_yaml = YAML()


def read_hlo(path, keep_keys: list | None = None, omit_keys: list | None = None) -> Tuple[dict, dict]:
    """Read a .hlo file; return (header_dict, data_dict).

    `path` may be a filesystem path string or raw bytes.
    """
    if isinstance(path, (bytes, bytearray)):
        return read_hlo_bytes(path, keep_keys=keep_keys, omit_keys=omit_keys)
    with open(str(Path(path)), "rb") as f:
        return read_hlo_stream(f, keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_stream(stream, keep_keys: list | None = None, omit_keys: list | None = None) -> Tuple[dict, dict]:
    """Parse a (meta, data) pair from an open binary stream."""
    header_lines = []
    header_end = False
    data: dict = defaultdict(list)
    _keep = keep_keys or []
    _omit = omit_keys or []

    for line in stream:
        if header_end:
            line_dict = orjson.loads(line)
            for k in line_dict:
                if _keep:
                    if k in _keep:
                        v = line_dict[k]
                        data[k] += v if isinstance(v, list) else [v]
                else:
                    if k not in _omit:
                        v = line_dict[k]
                        data[k] += v if isinstance(v, list) else [v]
        elif line.decode("utf-8").startswith("%%"):
            header_end = True
        else:
            header_lines.append(line)

    if header_lines:
        meta = dict(yml_load("".join(x.decode("utf-8") for x in header_lines)))
    else:
        meta = {}
    return meta, dict(data)


def read_hlo_bytes(content, keep_keys: list | None = None, omit_keys: list | None = None) -> Tuple[dict, dict]:
    """Parse a (meta, data) pair from raw .hlo bytes."""
    return read_hlo_stream(BytesIO(content), keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_header(file_path) -> tuple:
    """Return (header_dict, data_start_index) for a .hlo file."""
    yml_lines = []
    data_start_index = -1
    with open(file_path) as f:
        for i, line in enumerate(f):
            if line.strip().startswith("%%"):
                data_start_index = i + 1
                break
            yml_lines.append(line)
    yd = dict(_yaml.load("\n".join(yml_lines)))
    return yd, data_start_index


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
    """Yield (chunk_dict, max_len) tuples from the body of a .hlo file."""
    with open(file_path) as f:
        chunkd: dict = defaultdict(list)
        for i, line in enumerate(f):
            if i < data_start_index:
                continue
            jd = orjson.loads(line)
            for k, val in jd.items():
                if isinstance(val, list):
                    chunkd[k] += val
                else:
                    chunkd[k].append(val)
            if (i - data_start_index + 1) % chunk_size == 0:
                yield dict(chunkd), max(len(v) for v in chunkd.values())
                chunkd = defaultdict(list)
        if chunkd:
            yield dict(chunkd), max(len(v) for v in chunkd.values())


def hlo_to_parquet(
    input_hlo_path, output_parquet_path, chunk_size: int = 100
) -> None:
    """Convert a .hlo file to Parquet, embedding the header in schema metadata."""
    writer: pq.ParquetWriter | None = None
    schema = None
    metadata = None
    current_idx = 0
    header, data_start = read_hlo_header(input_hlo_path)

    for chunk, chunklen in read_hlo_data_chunks(input_hlo_path, data_start, chunk_size=chunk_size):
        df0 = pd.DataFrame(chunk, index=range(current_idx, current_idx + chunklen))
        table = pa.Table.from_pandas(df0)
        current_idx += chunklen

        if schema is None:
            custom_metadata = json.dumps(header.get("optional", {})).encode("utf8")
            existing = table.schema.metadata or {}
            metadata = {**{"helao_metadata": custom_metadata}, **existing}
        table = table.replace_schema_metadata(metadata)
        schema = table.schema

        if writer is None:
            writer = pq.ParquetWriter(output_parquet_path, schema)
        writer.write_table(table)

    if writer:
        writer.close()


def read_helao_metadata(parquet_file_path) -> dict:
    """Return the helao_metadata dict embedded in a Parquet schema."""
    meta = pq.read_metadata(parquet_file_path)
    return json.loads(meta.metadata.get(b"helao_metadata", b"{}").decode())
