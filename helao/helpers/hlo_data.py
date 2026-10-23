"""Readers for HELAO data files: the legacy ``.hlo`` (YAML header, ``%%``, JSON lines), the current pair ``X.meta.json`` (header) + ``X.jsonl`` (rows), and the S3 ``X.hlo.json`` shape ``{"meta", "data"}``.
This module exposes utilities to read both header and body, to stream the body
in chunks, and to convert a data file to Parquet (carrying the optional header
as schema metadata). ``HelaoData`` is lazily re-exported from
``helao.helpers.helao_data``.
"""

__all__ = [
    "read_hlo",
    "read_hlo_stream",
    "read_hlo_bytes",
    "read_hlo_pair_bytes",
    "resolve_data_file",
    "read_hlo_via",
    "read_hlo_header",
    "read_hlo_data_chunks",
    "hlo_to_parquet",
    "read_helao_metadata",
    "HelaoData",
]

import json
import os
from collections import defaultdict
from collections.abc import Callable, Collection
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from .helao_data import HelaoData

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML

from helao.hexagon.domain.naming import DATA_SUFFIX, HEADER_SUFFIX, data_sibling

from .yml_tools import yml_load

_yaml = YAML()
#: Names that denote a data file and may be resolved to their ``.jsonl``/``.hlo``.
_DATA_NAMES = (".hlo", ".hlo.json", DATA_SUFFIX, HEADER_SUFFIX)


def _keep(key, keep_keys, omit_keys) -> bool:
    """``keep_keys`` wins when given; otherwise ``omit_keys`` drops."""
    return key in keep_keys if keep_keys else key not in omit_keys


def _loads(content: bytes):
    """orjson, falling back to stdlib for the NaN/Infinity tokens it rejects."""
    try:
        return orjson.loads(content)
    except orjson.JSONDecodeError:
        return json.loads(content)


def _read_s3_shape(content: bytes, keep_keys, omit_keys) -> tuple[dict, dict]:
    """The S3 ``X.hlo.json`` document ``{"meta": ..., "data": {col: [...]}}``."""
    doc = _loads(content)
    data = defaultdict(list)
    for k, v in (doc.get("data") or {}).items():
        if _keep(k, keep_keys, omit_keys):
            data[k] = v
    return dict(doc.get("meta") or {}), data


def read_hlo(path, keep_keys: list = [], omit_keys: list = []) -> tuple[dict, dict]:
    """Read any data-file shape and return ``(meta, data)``.

    Dispatch is by name: ``.hlo`` (legacy, YAML header + ``%%`` + rows),
    ``.jsonl`` (rows; header from a sibling ``.meta.json`` when present),
    ``.meta.json`` (header; rows from the sibling ``.jsonl``, which must
    exist -- a missing header is legal, missing rows are a lost artifact),
    ``.hlo.json`` (the S3 ``{"meta", "data"}`` document). Raw ``bytes`` are
    parsed as a legacy ``.hlo``.

    Args:
        path: Filesystem path, or raw legacy ``.hlo`` bytes.
        keep_keys: When non-empty, only these keys are kept from the body.
        omit_keys: Keys to drop from the body when ``keep_keys`` is empty.

    Returns:
        ``(meta, data)``: the header dict and a dict of column lists.
    """
    if isinstance(path, (bytes, bytearray)):
        return read_hlo_bytes(path, keep_keys=keep_keys, omit_keys=omit_keys)
    p = str(path)
    if p.endswith(".hlo.json"):
        return _read_s3_shape(Path(p).read_bytes(), keep_keys, omit_keys)
    if p.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header = data_sibling(p, HEADER_SUFFIX)
        meta = orjson.loads(Path(header).read_bytes()) if os.path.isfile(header) else {}
        with open(data_sibling(p, DATA_SUFFIX), "rb") as f:
            _, data = read_hlo_stream(
                f, keep_keys=keep_keys, omit_keys=omit_keys, has_header=False
            )
        return meta, data
    with open(p, "rb") as f:
        return read_hlo_stream(f, keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_stream(
    stream, keep_keys: list = [], omit_keys: list = [], has_header: bool = True
) -> tuple[dict, dict]:
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
        has_header: ``False`` for a ``.jsonl``: every line is a row, even one
            that does not start with ``{``.

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
        if has_header and not header_end:
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
            # orjson rejects the non-finite tokens (``NaN``/``Infinity``) that
            # stdlib ``json.dumps`` emits by default, which are common in
            # instrument data. Fall back to stdlib ``json.loads`` (allow_nan)
            # so such rows are recovered as real ``nan``/``inf`` floats instead
            # of being silently dropped.
            try:
                line_dict = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                print(f"skipping unparseable hlo data line: {line[:80]!r}")
                continue
        for k in line_dict:
            if _keep(k, keep_keys, omit_keys):
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
) -> tuple[dict, dict]:
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


def read_hlo_pair_bytes(
    meta_bytes: Optional[bytes],
    data_bytes: bytes,
    keep_keys: list = [],
    omit_keys: list = [],
) -> tuple[dict, dict]:
    """``(meta, data)`` from the bytes of a ``.meta.json`` (or None) and its ``.jsonl``."""
    meta = orjson.loads(meta_bytes) if meta_bytes else {}
    _, data = read_hlo_stream(
        BytesIO(data_bytes), keep_keys=keep_keys, omit_keys=omit_keys, has_header=False
    )
    return meta, data


Where = Union[str, os.PathLike, Collection[str], Callable[[str], bool], None]


def _exists_fn(where: Where) -> Callable[[str], bool]:
    if callable(where):
        return where
    if isinstance(where, (str, os.PathLike)):
        return lambda n: os.path.isfile(os.path.join(where, n))
    names = set(where or ())
    return names.__contains__


def resolve_data_file(where: Where, name: str) -> Optional[str]:
    """The physical file a recorded data name refers to, or ``None``.

    A data name (``X.hlo``/``X.jsonl``/``X.meta.json``/``X.hlo.json``) is
    reduced to its stem ``X`` (directory kept) and resolved to the first of
    ``X.jsonl``, ``X.hlo``, ``X.hlo.json`` that exists: metadata records the
    S3 name ``X.hlo.json``, the local artifact is the ``.jsonl`` (current) or
    ``.hlo`` (legacy), and a tree rebuilt from S3 holds only ``.hlo.json``.
    ``X.meta.json`` never resolves to itself. Any other name is tried as-is.

    Args:
        where: A directory, a collection of names (e.g. a zip ``namelist()``),
            or an ``exists(name) -> bool`` callable.
        name: The recorded name, relative to ``where``.
    """
    exists = _exists_fn(where)
    if not name.endswith(_DATA_NAMES):
        return name if exists(name) else None
    candidates = (data_sibling(name, s) for s in (DATA_SUFFIX, ".hlo", ".hlo.json"))
    return next((c for c in candidates if exists(c)), None)


def read_hlo_via(
    where: Where,
    get_bytes: Callable[[str], bytes],
    name: str,
    keep_keys: list = [],
    omit_keys: list = [],
) -> tuple[dict, dict]:
    """:func:`read_hlo` for a byte source: a zip, a run-tree mapper, a loader.

    With ``where=None`` existence is probed by calling ``get_bytes``;
    ``FileNotFoundError`` and ``KeyError`` (a zip's missing member) mean absent.

    Raises:
        FileNotFoundError: ``name`` resolves to nothing, or to a header whose
            ``.jsonl`` is missing.
    """
    cache: dict[str, bytes] = {}

    def probe(n: str) -> bool:
        try:
            cache[n] = get_bytes(n)
        except (FileNotFoundError, KeyError):
            return False
        return True

    exists = probe if where is None else _exists_fn(where)
    fetch = (
        (lambda n: cache[n] if n in cache else get_bytes(n))
        if where is None
        else get_bytes
    )
    phys = resolve_data_file(exists, name)
    if phys is None:
        raise FileNotFoundError(name)
    if phys.endswith(".hlo.json"):
        return _read_s3_shape(fetch(phys), keep_keys, omit_keys)
    if phys.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header, rows = data_sibling(phys, HEADER_SUFFIX), data_sibling(
            phys, DATA_SUFFIX
        )
        if not exists(rows):
            raise FileNotFoundError(rows)
        meta_bytes = fetch(header) if exists(header) else None
        return read_hlo_pair_bytes(meta_bytes, fetch(rows), keep_keys, omit_keys)
    return read_hlo_bytes(fetch(phys), keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_header(file_path) -> tuple:
    """Read the YAML header of an HLO file.

    For a ``.jsonl``/``.meta.json`` pair the header comes from the
    ``.meta.json`` and the data start index is 0.

    Args:
        file_path: Path to the ``.hlo``, ``.jsonl`` or ``.meta.json`` file.

    Returns:
        A ``(header_dict, data_start_index)`` tuple where
        ``data_start_index`` is the zero-based index of the first body line
        (or ``-1`` if no ``%%`` marker was found).
    """
    p = str(file_path)
    if p.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header = data_sibling(p, HEADER_SUFFIX)
        meta = orjson.loads(Path(header).read_bytes()) if os.path.isfile(header) else {}
        return meta, 0
    yml_lines = []
    data_start_index = -1
    with open(file_path, encoding="utf-8") as f:
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
    if str(file_path).endswith(HEADER_SUFFIX):
        file_path = data_sibling(file_path, DATA_SUFFIX)
    with open(file_path, encoding="utf-8") as f:
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
