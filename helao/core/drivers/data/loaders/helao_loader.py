"""Remote HELAO data loader backed by S3 (HLO/JSON) and PostgreSQL (metadata).

Provides ``HelaoLoader`` with optional in-memory caches for S3 objects and JSON
metadata, plus thin wrapper classes (``HelaoAction`` /
``HelaoExperiment`` / ``HelaoSequence`` / ``HelaoProcess``) that lazily fetch
their metadata and primary HLO file via a module-level ``LOADER`` instance.
"""

import io
import json
import warnings
from datetime import datetime
from typing import Optional
from uuid import UUID

import boto3
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from helao.core.drivers.data.loaders.model_base import (
    HelaoDataModelMixin,
    HloPayload,
)
from helao.core.models.credentials import HelaoCredentials
from helao.helpers import helao_logging as logging
from helao.hexagon.domain.naming import data_stem

#: The SQL metadata backend is being retired and no deployment queries it.
_SQL_DEPRECATED = (
    "the HELAO SQL metadata backend is deprecated and will be shut off; "
    "use the S3 JSON (get_json / .json) instead"
)


def _warn_sql(stacklevel: int = 3):
    """Warn at the caller of the deprecated API (``stacklevel`` frames up)."""
    warnings.warn(_SQL_DEPRECATED, DeprecationWarning, stacklevel=stacklevel)


def _as_datetime(value):
    """Parse an ISO timestamp string from S3 JSON; anything else passes through.

    The local loader's yml parser yields ``datetime``; this gives the remote
    wrappers the same type.
    """
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


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
                Deprecated with the SQL backend.
        """
        self.uuid = uuid
        self.helao_type = helao_type
        if query_df is not None:
            # Reached through a subclass __init__'s super() call: one frame more.
            _warn_sql(stacklevel=4)
        if (
            query_df is not None
            and query_df.query(f"{helao_type}_uuid==@uuid").shape[0] > 1
        ):
            self.meta_dict = (
                query_df.query(f"{helao_type}_uuid==@uuid").iloc[0].to_dict()
            )
        else:
            self.meta_dict = self.json
        self.timestamp = _as_datetime(self.meta_dict.get(f"{helao_type}_timestamp"))
        self.params = self.meta_dict.get(f"{helao_type}_params", {})
        key = "technique_name" if helao_type == "process" else f"{helao_type}_name"
        self.name = self.meta_dict.get(key)

    @property
    def json(self) -> dict:
        """Remote JSON metadata for this record, fetched via the module ``LOADER``."""
        return LOADER.get_json(self.helao_type, self.uuid)


class HelaoDataModel(HelaoDataModelMixin, HelaoModel):
    """``HelaoModel`` mixed with HLO-data accessors for action and process records.

    Adds :attr:`files` (legacy ``(s3_key, file_type, run_use)`` tuples). The
    dict-based accessors from the mixin (``data_files``/``hlo_file``/``hlo``)
    are left unchanged.
    """

    @staticmethod
    def _s3_key(file_dict: dict) -> str:
        """S3 key for a ``files`` entry under its action's ``raw_data`` prefix."""
        return f"raw_data/{file_dict['action_uuid']}/{file_dict['file_name']}"

    @property
    def files(self) -> list:
        """``(s3_key, file_type, run_use)`` tuples for every file in the record."""
        return [
            (self._s3_key(x), x.get("file_type"), x.get("run_use"))
            for x in self.json.get("files", [])
        ]

    @property
    def hlo(self) -> HloPayload:
        """:class:`HloPayload` of the primary data file (empty if none)."""
        if not self.data_files:
            return HloPayload()
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


LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

DEFAULT_READ_BUCKET = "helao.data"


class HelaoLoader:
    """Cached access layer over the HELAO S3 bucket and metadata SQL database.

    Manages a boto3 session, an S3 client/resource, and a SQLAlchemy engine
    pointing at the credentials defined in ``env_file``. Supports optional
    caches for raw S3 bytes and decoded JSON metadata.
    """

    def __init__(
        self,
        env_file: str = ".env",
        cache_s3: bool = False,
        cache_json: bool = False,
    ):
        """Open the S3 and SQL connections using credentials from ``env_file``.

        Args:
            env_file: Path to the ``.env`` file with HELAO credentials.
            cache_s3: Cache raw S3 HLO payloads in memory.
            cache_json: Cache fetched JSON metadata in memory.
        """
        self.env_file = env_file
        self.cache_s3 = cache_s3
        self.cache_json = cache_json
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}
        self.last_seq_uuid = ""
        self.connect()

    def __del__(self):
        """Close the S3 client on garbage collection."""
        self.cli.close()
        # self.tunnel.stop()

    def connect(self):
        """Load credentials and open the S3 session and SQL engine."""
        self.hcred = HelaoCredentials(_env_file=self.env_file)
        # self.tunnel = sshtunnel.SSHTunnelForwarder(
        #     self.hcred.JUMPBOX_HOST,
        #     ssh_username=self.hcred.JUMPBOX_USER,
        #     ssh_pkey=self.hcred.JUMPBOX_KEYFILE,
        #     remote_bind_address=(self.hcred.API_HOST, int(self.hcred.API_PORT)),
        # )
        # self.tunnel.start()
        # self.hcred.set_api_port(self.tunnel.local_bind_port)
        self.sess = boto3.Session(
            aws_access_key_id=self.hcred.AWS_ACCESS_KEY_ID.get_secret_value(),
            aws_secret_access_key=self.hcred.AWS_SECRET_ACCESS_KEY.get_secret_value(),
        )
        self.s3_bucket = self.hcred.AWS_BUCKET.get_secret_value()
        self.s3_region = self.hcred.AWS_REGION.get_secret_value()
        self.cli = self.sess.client("s3")
        self.res = self.sess.resource("s3")
        # Deprecated with the SQL backend; create_engine does not connect.
        self.engine = create_engine(self.hcred.api_dsn)

    def reconnect(self):
        """Close the existing S3 client (if any) and re-open the connections."""
        try:
            self.cli.close()
            # self.tunnel.stop()
        except Exception as e:
            print(f"!!! Error closing tunnel: {e}")
        finally:
            self.connect()

    def run_raw_query(self, query: str) -> list:
        """Execute a raw SQL ``query`` against the metadata DB. Deprecated."""
        _warn_sql()
        return self._query(query)

    def _query(self, query: str) -> list:
        with Session(self.engine) as session:
            return list(session.execute(text(query)).all())

    def clear_cache(self):
        """Drop every in-memory cache (action/experiment/sequence/process/S3)."""
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}

    _warned_empty_bucket = False

    @property
    def read_bucket(self) -> str:
        """Credential bucket for reads; ``helao.data`` (warned once) when it is empty."""
        if self.s3_bucket:
            return self.s3_bucket
        if not HelaoLoader._warned_empty_bucket:
            HelaoLoader._warned_empty_bucket = True
            LOGGER.warning(
                f"AWS_BUCKET is empty in the credentials; reading from "
                f"'{DEFAULT_READ_BUCKET}'. Set AWS_BUCKET to silence this."
            )
        return DEFAULT_READ_BUCKET

    def get_bytes(self, s3_bucket: str, s3_key: str) -> io.BytesIO:
        """Fetch ``s3://s3_bucket/s3_key`` and return its body as a ``BytesIO``."""
        obj = self.res.Object(bucket_name=s3_bucket, key=s3_key)
        obytes = io.BytesIO(obj.get()["Body"].read())
        return obytes

    def get_json(self, helao_type: str, uuid: UUID) -> dict:
        """Fetch and decode ``s3://<s3_bucket>/<helao_type>/<uuid>.json``."""
        obytes = self.get_bytes(
            s3_bucket=self.read_bucket, s3_key=f"{helao_type}/{str(uuid)}.json"
        )
        md = json.load(obytes)
        return md

    def get_act(self, action_uuid: UUID, hmod: bool = True) -> dict | HelaoAction:
        """Return the action's JSON dict, or a ``HelaoAction`` wrapper when ``hmod``."""
        if self.cache_json and action_uuid in self.act_cache:
            jd = self.act_cache[action_uuid]
        else:
            jd = self.get_json("action", action_uuid)
            if self.cache_json:
                self.act_cache[action_uuid] = jd
        if hmod:
            return HelaoAction(action_uuid)
        return jd

    def get_exp(
        self, experiment_uuid: UUID, hmod: bool = True
    ) -> dict | HelaoExperiment:
        """Return the experiment's JSON dict, or a ``HelaoExperiment`` wrapper when ``hmod``."""
        if self.cache_json and experiment_uuid in self.exp_cache:
            jd = self.exp_cache[experiment_uuid]
        else:
            jd = self.get_json("experiment", experiment_uuid)
            if self.cache_json:
                self.exp_cache[experiment_uuid] = jd
        if hmod:
            return HelaoExperiment(experiment_uuid)
        return jd

    def get_seq(self, sequence_uuid: UUID, hmod: bool = True) -> dict | HelaoSequence:
        """Return the sequence's JSON dict, or a ``HelaoSequence`` wrapper when ``hmod``.

        Clears all caches when ``sequence_uuid`` differs from the previously
        loaded sequence to keep cache memory bounded.
        """
        if sequence_uuid != self.last_seq_uuid:
            self.clear_cache()
            self.last_seq_uuid = sequence_uuid
        if self.cache_json and sequence_uuid in self.seq_cache:
            jd = self.seq_cache[sequence_uuid]
        else:
            jd = self.get_json("sequence", sequence_uuid)
            if self.cache_json:
                self.seq_cache[sequence_uuid] = jd
        if hmod:
            return HelaoSequence(sequence_uuid)
        return jd

    def get_prc(self, process_uuid: UUID, hmod: bool = True) -> dict | HelaoProcess:
        """Return the process's JSON dict, or a ``HelaoProcess`` wrapper when ``hmod``."""
        if self.cache_json and process_uuid in self.pro_cache:
            jd = self.pro_cache[process_uuid]
        else:
            jd = self.get_json("process", process_uuid)
            if self.cache_json:
                self.pro_cache[process_uuid] = jd
        if hmod:
            return HelaoProcess(process_uuid)
        return jd

    def get_hlo(self, action_uuid: UUID, hlo_fn: str) -> HloPayload:
        """Fetch and decode the HLO JSON for ``hlo_fn`` under the action's raw_data prefix.

        Args:
            action_uuid: UUID of the parent action.
            hlo_fn: HLO/JSON file name as recorded in the action's ``files``.

        Returns:
            :class:`HloPayload` of the ``.hlo.json``; empty if the file name is
            not a valid HLO.
        """
        if hlo_fn.endswith((".hlo", ".jsonl")):
            keystr = f"raw_data/{str(action_uuid)}/{data_stem(hlo_fn)}.hlo.json"
        elif hlo_fn.endswith(".json"):
            if not hlo_fn.endswith(".hlo.json"):
                keystr = f"raw_data/{str(action_uuid)}/{hlo_fn.replace('.json', '.hlo.json')}"
            else:
                keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}"

        else:
            print(f"{hlo_fn} is not a valid named hlo file.")
            return HloPayload()
        if keystr in self.s3_cache:
            return self.s3_cache[keystr]
        obj = self.res.Object(bucket_name=self.read_bucket, key=keystr)
        obytes = io.BytesIO(obj.get()["Body"].read())
        raw = json.load(obytes)
        jd = HloPayload(raw.get("meta"), raw.get("data"))
        if self.cache_s3:
            self.s3_cache[keystr] = jd
        return jd


LOADER: HelaoLoader = None
