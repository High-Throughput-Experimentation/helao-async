"""HLO file reading and parquet conversion.

Consolidates the former read_hlo and parquet modules.
``HelaoData`` is re-exported from ``helao.helpers.helao_data`` for callers that
imported it from ``read_hlo``.
"""

__all__ = [
    "read_hlo",
    "read_hlo_header",
    "read_hlo_data_chunks",
    "hlo_to_parquet",
    "read_helao_metadata",
    "HelaoData",
]

import json
from collections import defaultdict
from pathlib import Path
from typing import Tuple

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML

from .yml_tools import yml_load


_yaml = YAML()


def read_hlo(
    path: str, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Read a .hlo file and return its (meta, data) dictionaries."""
    if keep_keys and omit_keys:
        print(
            "Both keep_keys and omit_keys are provided. keep_keys will take precedence."
        )

    path_to_hlo = Path(path)
    header_lines = []
    header_end = False
    data = defaultdict(list)

    with open(str(path_to_hlo), "rb") as f:
        for line in f:
            if header_end:
                line_dict = orjson.loads(line)
                for k in line_dict:
                    if k in keep_keys or k not in omit_keys:
                        v = line_dict[k]
                        if isinstance(v, list):
                            data[k] += v
                        else:
                            data[k].append(v)
            elif line.decode("utf8").startswith("%%"):
                header_end = True
            elif not header_end:
                header_lines.append(line)
    if header_lines:
        meta = dict(yml_load("".join([x.decode("utf8") for x in header_lines])))
    else:
        meta = {}

    return meta, data


def read_hlo_header(file_path):
    """Read the YAML header of an HLO file. Returns (header_dict, data_start_index)."""
    yml_lines = []
    data_start_index = -1
    with open(file_path) as f:
        for i, line in enumerate(f):
            if line.strip().startswith("%%"):
                data_start_index = i + 1
                break
            else:
                yml_lines.append(line)
        yd = dict(_yaml.load("\n".join(yml_lines)))
    return yd, data_start_index


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
    """Yield (chunk_dict, max_chunk_len) tuples from an HLO file in chunks."""
    with open(file_path) as f:
        chunkd = defaultdict(list)
        for i, line in enumerate(f):
            if i < data_start_index:
                continue
            else:
                jd = json.loads(line.strip())
                for k, val in jd.items():
                    if isinstance(val, list):
                        chunkd[k] += val
                    else:
                        chunkd[k].append(val)
                if (i - data_start_index + 1) % chunk_size == 0:
                    yield dict(chunkd), max([len(v) for v in chunkd.values()])
                    chunkd = defaultdict(list)
        if chunkd:
            yield dict(chunkd), max([len(v) for v in chunkd.values()])


def hlo_to_parquet(
    input_hlo_path, output_parquet_path, chunk_size=100, HISPEC: bool = False
):
    """Convert an HLO file to Parquet format."""
    writer: pq.ParquetWriter = None
    schema = None
    metadata = None
    current_idx = 0
    header, data_start = read_hlo_header(input_hlo_path)

    if HISPEC:
        df_headers_no_time = header["optional"]["wl"]
        df_headers_all = [000] + df_headers_no_time
        df_headers_all = list(map(float, df_headers_all))

    for chunk, chunklen in read_hlo_data_chunks(
        input_hlo_path, data_start, chunk_size=chunk_size
    ):
        df0 = pd.DataFrame(chunk, index=range(current_idx, current_idx + chunklen))

        if current_idx == 0:
            start_ticktime = df0.iloc[0, 0]

        if HISPEC:
            df0.iloc[:, 0] = df0.iloc[:, 0].apply(lambda x: x - start_ticktime)
            df0.columns = df_headers_all
            df = df0.iloc[:, 1:-1]
            df = df.T.groupby(df.columns // 1).mean().T
            df.insert(0, "t_s", df0.iloc[:, 0])
            df.columns = df.columns.astype(str)

            table = pa.Table.from_pandas(df)
            current_idx += chunklen
            df = pd.DataFrame()

        else:
            table = pa.Table.from_pandas(df0)
            current_idx += chunklen

        if schema is None:
            schema = table.schema
            existing_metadata = schema.metadata
            custom_metadata = json.dumps(header.get("optional", {})).encode("utf8")
            metadata = {**{"helao_metadata": custom_metadata}, **existing_metadata}

        table = table.replace_schema_metadata(metadata)
        schema = table.schema

        if writer is None:
            writer = pq.ParquetWriter(output_parquet_path, schema)

        writer.write_table(table)

    if writer:
        writer.close()


def read_helao_metadata(parquet_file_path):
    """Read Helao-specific metadata from a Parquet file's schema."""
    meta = pq.read_metadata(parquet_file_path)
    metadict = json.loads(meta.metadata.get(b"helao_metadata", b"{}").decode())
    return metadict


def __getattr__(name):
    # Lazy re-export of HelaoData from helao_data to keep import side effects light.
    if name == "HelaoData":
        from .helao_data import HelaoData
        return HelaoData
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
