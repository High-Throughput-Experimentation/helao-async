"""Pure read/convert functions for the HELAO ``.hlo`` data file format.

A ``.hlo`` file is a YAML header followed by a ``%%`` separator line and one
JSON object per line of data. This module is a faithful, self-contained port
of :func:`read_hlo` and :func:`hlo_to_parquet` from
``helao/helpers/hlo_data.py`` (and the small private helpers they depend on),
living under the framework so the framework does not import legacy helpers.

The HLO parsing and the Parquet schema/metadata layout are byte/schema
identical to the legacy implementation: historical data, the live
``HelaoSyncer``, and downstream analysis all depend on them, so they are NOT
changed here.

Design note (D7 of the SP6 spec): these are loaders consumed by the sync
pipeline / downstream analysis, not injected into the domain, so they live in
``adapters/loaders/`` with no port. ``yml_load`` is taken from the framework's
own ``support`` package (not from ``helao.helpers``) to keep the framework
self-contained.
"""

import io
import json
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime

import boto3
import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML
from sqlmodel import Session, text, create_engine

from helao.framework.models.credentials import HelaoCredentials
from helao.framework.adapters.loaders.model_base import HelaoDataModelMixin
from helao.framework.support.yml_tools import yml_load

_yaml = YAML()


def read_hlo(
    path: str, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Read a ``.hlo`` file and return its header and body as dicts.

    Accepts either a filesystem path or the raw file content as ``bytes``, so a
    caller that has already pulled the bytes out of a zip member need not write
    them to disk.

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
        if header_end:
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
        elif line.decode("utf8").startswith("%%"):
            header_end = True
        elif not header_end:
            header_lines.append(line)
    if header_lines:
        meta = dict(yml_load("".join([x.decode("utf8") for x in header_lines])))
    else:
        meta = {}

    return meta, data


def read_hlo_bytes(
    content, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """Parse an HLO ``(meta, data)`` pair from the raw file content.

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


# ---------------------------------------------------------------------------
# Remote S3 + PostgreSQL loader — ported from
# helao/core/drivers/data/loaders/helao_loader.py
# Legacy imports repointed:
#   helao.core.models.credentials      → helao.framework.models.credentials
#   helao.core.drivers.data.loaders.model_base → helao.framework.adapters.loaders.model_base
# ---------------------------------------------------------------------------


class HelaoSolid:
    """Lightweight handle to a solid sample identified by its global label."""

    sample_label: str

    def __init__(self, sample_label):
        """Store the sample's global label.

        Args:
            sample_label: Global sample label.
        """
        self.sample_label = sample_label


class HelaoModel:
    """Base wrapper around a HELAO record (action/experiment/sequence/process).

    Hydrates ``name``, ``uuid``, ``timestamp``, and ``params`` from either an
    optional pre-loaded query dataframe row or the remote JSON fetched via
    the module-level ``LOADER``.

    Attributes:
        name: Record name (technique name for processes).
        uuid: Record UUID.
        helao_type: One of ``action``/``experiment``/``sequence``/``process``.
        timestamp: Record timestamp.
        params: Record ``*_params`` dict.
    """

    name: str
    uuid: UUID
    helao_type: str
    timestamp: datetime
    params: dict

    def __init__(
        self, helao_type: str, uuid: UUID, query_df: Optional[pd.DataFrame] = None
    ):
        """Hydrate the record from ``query_df`` (if non-empty) or from remote JSON.

        Args:
            helao_type: Record kind.
            uuid: Record UUID.
            query_df: Optional SQL result frame to source metadata from.
        """
        self.uuid = uuid
        self.helao_type = helao_type
        if (
            query_df is not None
            and query_df.query(f"{helao_type}_uuid==@uuid").shape[0] > 1
        ):
            self.meta_dict = (
                query_df.query(f"{helao_type}_uuid==@uuid").iloc[0].to_dict()
            )
        else:
            self.meta_dict = self.json
        self.timestamp = self.meta_dict.get(
            f"{helao_type}_timestamp",
            self.meta_dict.get(f"{helao_type}_timestamp", None),
        )
        self.params = self.meta_dict.get(
            f"{helao_type}_params", self.meta_dict.get(f"{helao_type}_params", {})
        )
        if helao_type == "process":
            self.name = self.meta_dict.get(
                "technique_name", self.meta_dict.get("technique_name", None)
            )
        else:
            self.name = self.meta_dict.get(
                f"{helao_type}_name", self.meta_dict.get(f"{helao_type}_name", None)
            )

    @property
    def json(self) -> dict:
        """Remote JSON metadata for this record, fetched via the module ``LOADER``."""
        return LOADER.get_json(self.helao_type, self.uuid)

    @property
    def _meta_dict(self) -> dict:
        """SQL row for this record fetched via the module ``LOADER``."""
        return LOADER.get_sql(self.helao_type, self.uuid)


class HelaoDataModel(HelaoDataModelMixin, HelaoModel):
    """``HelaoModel`` mixed with HLO-data accessors for action and process records."""

    @property
    def hlo(self) -> dict:
        """Parsed HLO JSON for the primary data file (empty dict if none)."""
        if not self.hlo_file:
            return {}
        return LOADER.get_hlo(self.hlo_file["action_uuid"], self.hlo_file["file_name"])


class HelaoAction(HelaoDataModel):
    """Action record loaded from the remote backend, with HLO data access."""

    action_name: str
    action_uuid: UUID
    action_timestamp: datetime
    action_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        """Load action ``uuid`` and mirror its identity to ``action_*`` attributes.

        Args:
            uuid: Action UUID.
            query_df: Optional SQL result frame.
        """
        super().__init__(helao_type="action", uuid=uuid, query_df=query_df)
        self.action_name = self.name
        self.action_uuid = self.uuid
        self.action_timestamp = self.timestamp
        self.action_params = self.params


class HelaoExperiment(HelaoModel):
    """Experiment record loaded from the remote backend."""

    experiment_name: str
    experiment_uuid: UUID
    experiment_timestamp: datetime
    experiment_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        """Load experiment ``uuid`` and mirror its identity to ``experiment_*`` attributes.

        Args:
            uuid: Experiment UUID.
            query_df: Optional SQL result frame.
        """
        super().__init__(helao_type="experiment", uuid=uuid, query_df=query_df)
        self.experiment_name = self.name
        self.experiment_uuid = self.uuid
        self.experiment_timestamp = self.timestamp
        self.experiment_params = self.params


class HelaoSequence(HelaoModel):
    """Sequence record loaded from the remote backend."""

    sequence_name: str
    sequence_uuid: UUID
    sequence_timestamp: datetime
    sequence_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        """Load sequence ``uuid`` and mirror its identity to ``sequence_*`` attributes.

        Args:
            uuid: Sequence UUID.
            query_df: Optional SQL result frame.
        """
        super().__init__(helao_type="sequence", uuid=uuid, query_df=query_df)
        self.sequence_name = self.name
        self.sequence_uuid = self.uuid
        self.sequence_timestamp = self.timestamp
        self.sequence_params = self.params


class HelaoProcess(HelaoDataModel):
    """Process record loaded from the remote backend, with HLO data access."""

    process_name: str
    process_uuid: UUID
    process_timestamp: datetime
    process_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        """Load process ``uuid`` and expose ``technique_name`` / ``process_*`` attributes.

        Args:
            uuid: Process UUID.
            query_df: Optional SQL result frame.
        """
        super().__init__(helao_type="process", uuid=uuid, query_df=query_df)
        self.technique_name = self.name
        self.process_uuid = self.uuid
        self.process_timestamp = self.timestamp
        self.process_params = self.params


class HelaoLoader:
    """Cached access layer over the HELAO S3 bucket and metadata SQL database.

    Manages a boto3 session, an S3 client/resource, and a sqlmodel engine
    pointing at the credentials defined in ``env_file``. Supports optional
    caches for raw S3 bytes, decoded JSON metadata, and SQL rows.
    """

    def __init__(
        self,
        env_file: str = ".env",
        cache_s3: bool = False,
        cache_json: bool = False,
        cache_sql: bool = False,
    ):
        """Open the S3 and SQL connections using credentials from ``env_file``.

        Args:
            env_file: Path to the ``.env`` file with HELAO credentials.
            cache_s3: Cache raw S3 HLO payloads in memory.
            cache_json: Cache fetched JSON metadata in memory.
            cache_sql: Cache SQL query rows in memory.
        """
        self.env_file = env_file
        self.cache_s3 = cache_s3
        self.cache_json = cache_json
        self.cache_sql = cache_sql
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}
        self.sql_cache = {}  # {(uuid, type): json_dict}
        self.last_seq_uuid = ""
        self.connect()

    def __del__(self):
        """Close the S3 client on garbage collection."""
        self.cli.close()

    def connect(self):
        """Load credentials and open the S3 session and SQL engine."""
        self.hcred = HelaoCredentials(_env_file=self.env_file)
        self.sess = boto3.Session(
            aws_access_key_id=self.hcred.AWS_ACCESS_KEY_ID.get_secret_value(),
            aws_secret_access_key=self.hcred.AWS_SECRET_ACCESS_KEY.get_secret_value(),
        )
        self.s3_bucket = self.hcred.AWS_BUCKET.get_secret_value()
        self.s3_region = self.hcred.AWS_REGION.get_secret_value()
        self.cli = self.sess.client("s3")
        self.res = self.sess.resource("s3")
        self.engine = create_engine(self.hcred.api_dsn)

    def reconnect(self):
        """Close the existing S3 client (if any) and re-open the connections."""
        try:
            self.cli.close()
        except Exception as e:
            print(f"!!! Error closing tunnel: {e}")
        finally:
            self.connect()

    def run_raw_query(self, query: str) -> list:
        """Execute a raw SQL ``query`` against the metadata DB and return all rows."""
        with Session(self.engine) as session:
            result = session.exec(text(query)).all()
        return result

    def clear_cache(self):
        """Drop every in-memory cache (action/experiment/sequence/process/S3/SQL)."""
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}
        self.sql_cache = {}  # {(uuid, type): json_dict}

    def get_bytes(self, s3_bucket: str, s3_key: str) -> io.BytesIO:
        """Fetch ``s3://s3_bucket/s3_key`` and return its body as a ``BytesIO``."""
        obj = self.res.Object(bucket_name=s3_bucket, key=s3_key)
        obytes = io.BytesIO(obj.get()["Body"].read())
        return obytes

    def get_json(self, helao_type: str, uuid: UUID) -> dict:
        """Fetch and decode ``s3://helao.data/<helao_type>/<uuid>.json``."""
        obytes = self.get_bytes(
            s3_bucket="helao.data", s3_key=f"{helao_type}/{str(uuid)}.json"
        )
        md = json.load(obytes)
        return md

    def get_act(self, action_uuid: UUID, hmod: bool = True) -> "dict | HelaoAction":
        """Return the action's JSON dict, or a ``HelaoAction`` wrapper when ``hmod``."""
        jd = self.act_cache.get(action_uuid, self.get_json("action", action_uuid))
        if self.cache_json:
            self.act_cache[action_uuid] = jd
        if hmod:
            return HelaoAction(action_uuid)
        return jd

    def get_exp(self, experiment_uuid: UUID, hmod: bool = True) -> "dict | HelaoExperiment":
        """Return the experiment's JSON dict, or a ``HelaoExperiment`` wrapper when ``hmod``."""
        jd = self.exp_cache.get(
            experiment_uuid, self.get_json("experiment", experiment_uuid)
        )
        if self.cache_json:
            self.exp_cache[experiment_uuid] = jd
        if hmod:
            return HelaoExperiment(experiment_uuid)
        return jd

    def get_seq(self, sequence_uuid: UUID, hmod: bool = True) -> "dict | HelaoSequence":
        """Return the sequence's JSON dict, or a ``HelaoSequence`` wrapper when ``hmod``.

        Clears all caches when ``sequence_uuid`` differs from the previously
        loaded sequence to keep cache memory bounded.
        """
        if sequence_uuid != self.last_seq_uuid:
            self.clear_cache()
            self.last_seq_uuid = sequence_uuid
        jd = self.seq_cache.get(sequence_uuid, self.get_json("sequence", sequence_uuid))
        if self.cache_json:
            self.seq_cache[sequence_uuid] = jd
        if hmod:
            return HelaoSequence(sequence_uuid)
        return jd

    def get_prc(self, process_uuid: UUID, hmod: bool = True) -> "dict | HelaoProcess":
        """Return the process's JSON dict, or a ``HelaoProcess`` wrapper when ``hmod``."""
        jd = self.pro_cache.get(process_uuid, self.get_json("process", process_uuid))
        if self.cache_json:
            self.pro_cache[process_uuid] = jd
        if hmod:
            return HelaoProcess(process_uuid)
        return jd

    def get_hlo(self, action_uuid: UUID, hlo_fn: str) -> dict:
        """Fetch and decode the HLO JSON for ``hlo_fn`` under the action's raw_data prefix.

        Args:
            action_uuid: UUID of the parent action.
            hlo_fn: HLO/JSON file name as recorded in the action's ``files``.

        Returns:
            Parsed JSON dict, or ``{}`` if the file name is not a valid HLO.
        """
        if hlo_fn.endswith(".hlo"):
            keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}.json"
        elif hlo_fn.endswith(".json"):
            if not hlo_fn.endswith(".hlo.json"):
                keystr = f"raw_data/{str(action_uuid)}/{hlo_fn.replace('.json', '.hlo.json')}"
            else:
                keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}"
        else:
            print(f"{hlo_fn} is not a valid named hlo file.")
            return {}
        if keystr in self.s3_cache:
            return self.s3_cache[keystr]
        obj = self.res.Object(bucket_name="helao.data", key=keystr)
        obytes = io.BytesIO(obj.get()["Body"].read())
        jd = json.load(obytes)
        if self.cache_s3:
            self.s3_cache[keystr] = jd
        return jd

    def get_sql(self, helao_type: str, obj_uuid: UUID) -> dict:
        """Return the metadata DB row for ``(helao_type, obj_uuid)`` as a dict."""
        if (
            helao_type,
            obj_uuid,
        ) not in self.sql_cache.keys() or not self.cache_sql:
            sql_command = f"""
                SELECT *
                FROM helao_{helao_type} ht
                WHERE ht.{helao_type}_uuid = '{obj_uuid}'
                LIMIT 1
            """
            resp = self.run_raw_query(sql_command)
            self.sql_cache[
                (
                    helao_type,
                    obj_uuid,
                )
            ] = (
                resp[0]._asdict() if resp else {}
            )
        return self.sql_cache[
            (
                helao_type,
                obj_uuid,
            )
        ]


LOADER: HelaoLoader = None
