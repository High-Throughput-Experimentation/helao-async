"""Readers and conversion helpers for the HELAO ``.hlo`` data file format.

A ``.hlo`` file is a YAML header followed by a ``%%`` separator line and one
JSON object per line of data. This module exposes utilities to read both
header and body, to stream the body in chunks, and to convert a ``.hlo``
file to Parquet (carrying the optional header as schema metadata).
``HelaoData`` is lazily re-exported from ``helao.helpers.helao_data``.
"""

__all__ = [
    "read_hlo",
    "read_hlo_stream",
    "read_hlo_bytes",
    "read_hlo_header",
    "read_hlo_data_chunks",
    "hlo_to_parquet",
    "read_helao_metadata",
    "HelaoData",
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

from .yml_tools import yml_load


_yaml = YAML()


def read_hlo(
    path: str, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Read a ``.hlo`` file and return its header and body as dicts.

    Accepts either a filesystem path or the raw file content as ``bytes``
    (e.g. as returned by :meth:`FileMapper.read_bytes`), so a caller that has
    already pulled the bytes out of a zip member need not write them to disk.

    Args:
        path: Filesystem path to the ``.hlo`` file, or its raw ``bytes``.
        keep_keys: When non-empty, only these keys are kept from the body.
        omit_keys: Keys to omit from the body (ignored when ``keep_keys`` is
            populated, which takes precedence).

    Returns:
        A ``(meta, data)`` tuple where ``meta`` is the parsed YAML header
        and ``data`` is a dict of column lists assembled from the body.
    """
    if isinstance(path, (bytes, bytearray)):
        return read_hlo_bytes(path, keep_keys=keep_keys, omit_keys=omit_keys)
    path_to_hlo = Path(path)
    with open(str(path_to_hlo), "rb") as f:
        return read_hlo_stream(f, keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_stream(
    stream, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Parse an HLO ``(meta, data)`` pair from an open binary stream.

    Shares the parsing core of :func:`read_hlo` so callers holding an
    already-open binary file-like (e.g. a ``ZipFile`` member) can parse
    without a filesystem path.

    Args:
        stream: An iterable of raw (``bytes``) lines, such as an open binary
            file or ``ZipFile.open(member)`` handle.
        keep_keys: When non-empty, only these keys are kept from the body.
        omit_keys: Keys to omit from the body (ignored when ``keep_keys`` is
            populated, which takes precedence).

    Returns:
        A ``(meta, data)`` tuple where ``meta`` is the parsed YAML header
        and ``data`` is a dict of column lists assembled from the body.
    """
    if keep_keys and omit_keys:
        print(
            "Both keep_keys and omit_keys are provided. keep_keys will take precedence."
        )

    header_lines = []
    header_end = False
    data = defaultdict(list)

    for line in stream:
        if not header_end:
            stripped = line.decode("utf8", "ignore").lstrip()
            if stripped.startswith("%%"):
                # The header/data separator. A ``%%`` seen before any header
                # line has been collected is a stray/duplicate marker (some
                # files carry a spurious leading ``%%`` before the real
                # header); ignore it and keep reading so the real header is
                # not swallowed into the body.
                if header_lines:
                    header_end = True
                continue
            if not stripped.startswith("{"):
                # Ordinary header line (YAML ``key: value`` / list item).
                header_lines.append(line)
                continue
            # A JSON object appeared before any separator: the body has begun
            # (e.g. a header-less file). Switch to data mode and parse it.
            header_end = True
        if not line.strip():
            continue
        try:
            line_dict = orjson.loads(line)
        except orjson.JSONDecodeError:
            print(f"skipping unparseable hlo data line: {line[:80]!r}")
            continue
        for k in line_dict:
            if k in keep_keys or k not in omit_keys:
                v = line_dict[k]
                if isinstance(v, list):
                    data[k] += v
                else:
                    data[k].append(v)
    if header_lines:
        meta = dict(yml_load("".join([x.decode("utf8") for x in header_lines])))
    else:
        meta = {}

    return meta, data


def read_hlo_bytes(
    content, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Parse an HLO ``(meta, data)`` pair from the raw file content.

    Thin wrapper over :func:`read_hlo_stream` for callers that hold the whole
    file as ``bytes`` (e.g. :meth:`FileMapper.read_bytes` of a zip member).

    Args:
        content: Raw bytes of an entire ``.hlo`` file.
        keep_keys: When non-empty, only these keys are kept from the body.
        omit_keys: Keys to omit from the body (ignored when ``keep_keys`` is
            populated, which takes precedence).

    Returns:
        A ``(meta, data)`` tuple where ``meta`` is the parsed YAML header
        and ``data`` is a dict of column lists assembled from the body.
    """
    return read_hlo_stream(BytesIO(content), keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_header(file_path) -> tuple:
    """Read the YAML header of an HLO file.

    Args:
        file_path: Path to the ``.hlo`` file.

    Returns:
        A ``(header_dict, data_start_index)`` tuple where
        ``data_start_index`` is the zero-based index of the first body line
        (or ``-1`` if no ``%%`` marker was found).
    """
    yml_lines = []
    data_start_index = -1
    with open(file_path) as f:
        for i, line in enumerate(f):
            if line.strip().startswith("%%"):
                # Ignore a stray leading ``%%`` written before the real header
                # (see :func:`read_hlo_stream`); only a separator that follows
                # collected header lines marks the true start of the body.
                if yml_lines:
                    data_start_index = i + 1
                    break
            else:
                yml_lines.append(line)
        yd = dict(_yaml.load("\n".join(yml_lines)))
    return yd, data_start_index


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
    """Yield successive chunks of the body of an HLO file.

    Args:
        file_path: Path to the ``.hlo`` file.
        data_start_index: Line index of the first body line (as returned by
            ``read_hlo_header``).
        chunk_size: Maximum number of body lines per chunk.

    Yields:
        ``(chunk_dict, max_chunk_len)`` tuples where ``chunk_dict`` is a
        dict of column lists for at most ``chunk_size`` lines and
        ``max_chunk_len`` is the longest column length in that chunk.
    """
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
    """Convert an HLO file to Parquet, embedding the header in schema metadata.

    The ``optional`` section of the header is serialized as JSON and stored
    under the ``helao_metadata`` schema metadata key. When ``HISPEC`` is set,
    wavelength columns from ``header["optional"]["wl"]`` are used to label
    the data columns and adjacent wavelengths are mean-aggregated.

    Args:
        input_hlo_path: Path to the source ``.hlo`` file.
        output_parquet_path: Destination Parquet file path.
        chunk_size: Number of body lines to read per write batch.
        HISPEC: When ``True``, apply HiSpec-specific column relabelling and
            wavelength aggregation before writing.
    """
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


def read_helao_metadata(parquet_file_path) -> dict:
    """Return the ``helao_metadata`` dict embedded in a Parquet schema.

    Args:
        parquet_file_path: Path to the Parquet file to inspect.

    Returns:
        The deserialized ``helao_metadata`` dict, or ``{}`` when no such
        schema-level metadata is present.
    """
    meta = pq.read_metadata(parquet_file_path)
    metadict = json.loads(meta.metadata.get(b"helao_metadata", b"{}").decode())
    return metadict


def __getattr__(name):
    """Lazily re-export ``HelaoData`` from :mod:`helao.helpers.helao_data`."""
    if name == "HelaoData":
        from .helao_data import HelaoData
        return HelaoData
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
