"""ECHEUVIS-specific HELAO loader backed by PostgreSQL + S3."""

import time
from uuid import UUID
from typing import Optional

import pandas as pd
from helao.framework.adapters.loaders.hlo_loader import HelaoLoader

LOADER: HelaoLoader = None


def _annotate_plate_sample(pdf: pd.DataFrame) -> pd.DataFrame:
    """Add ``plate_id``/``sample_no`` columns derived from each row's global label.

    The two values are parsed from the trailing fields of a ``solid`` global
    label; rows whose sample number can't be parsed are backfilled from the
    owning sequence's ``plate_id`` / ``plate_sample_no_list`` params. Mutates
    and returns ``pdf``.

    Args:
        pdf: Query-result frame with ``global_label``, ``sequence_uuid`` and
            ``sequence_params`` columns.

    Returns:
        The same frame with ``plate_id`` and ``sample_no`` columns populated.
    """
    pdf["plate_id"] = pdf.global_label.apply(
        lambda x: int(x.split("_")[-2]) if "solid" in x and "None" not in x else None
    )
    pdf["sample_no"] = pdf.global_label.apply(
        lambda x: int(x.split("_")[-1]) if "solid" in x and "None" not in x else None
    )
    for suuid in set(pdf.query("sample_no.isna()").sequence_uuid):
        subdf = pdf.query("sequence_uuid==@suuid")
        spars = subdf.iloc[0]["sequence_params"]
        pid = spars["plate_id"]
        solid_samples = spars["plate_sample_no_list"]
        assemblies = sorted(
            set(subdf.query("global_label.str.contains('assembly')").global_label)
        )
        for slab, alab in zip(solid_samples, assemblies):
            idx = pdf.query("sequence_uuid==@suuid & global_label==@alab").index
            pdf.loc[idx, "plate_id"] = pid
            pdf.loc[idx, "sample_no"] = slab
    return pdf


class EcheUvisLoader(HelaoLoader):
    """``HelaoLoader`` extended with ECHEUVIS-specific queries.

    Adds retry-aware ``get_sequence`` and ``get_recent`` methods that decorate
    raw SQL results with ``plate_id`` / ``sample_no`` columns derived from the
    global label and any sequence-level plate metadata.
    """

    def __init__(
        self,
        env_file: str = ".env",
        cache_s3: bool = False,
        cache_json: bool = False,
        cache_sql: bool = False,
    ):
        """Initialize the loader and a per-instance ``recent_cache`` dict.

        Args:
            env_file: Path to the ``.env`` file with credentials.
            cache_s3: Cache raw S3 HLO payloads in memory.
            cache_json: Cache fetched JSON metadata in memory.
            cache_sql: Cache SQL query rows in memory.
        """
        super().__init__(env_file, cache_s3, cache_json, cache_sql)
        # print("!!! using env_file:", env_file)
        # print("!!! postgresql dsn:", self.hcred.api_dsn)
        self.recent_cache = {}  # {'%Y-%m-%d': dataframe}
        self.cache_sql = cache_sql

    def get_sequence(
        self,
        query: str,
        sequence_uuid: UUID,
        sql_query_retries: int = 5,
    ) -> pd.DataFrame:
        """Run ``query`` scoped to one ``sequence_uuid`` with retry-on-failure.

        Args:
            query: Base SQL (the sequence-uuid filter is appended).
            sequence_uuid: Sequence to scope the query to.
            sql_query_retries: Max attempts before raising.

        Returns:
            Result frame annotated with ``plate_id`` / ``sample_no`` and
            sorted by ``process_timestamp``.

        Raises:
            Exception: If every retry of the SQL query fails.
        """
        conditions = []
        conditions.append(f"    AND hp.sequence_uuid = '{str(sequence_uuid)}'")
        tries = 0
        data = None
        while tries < sql_query_retries:
            try:
                data = self.run_raw_query(query + "\n".join(conditions))
                break
            except Exception as e:
                print(f"!!! SQL query failed: {e}")
                tries += 1
                time.sleep(30 * tries)
                self.reconnect()
        if data is None:
            raise Exception("!!! SQL query failed after retries.")
        pdf = pd.DataFrame(data)
        print("!!! dataframe shape:", pdf.shape)
        print("!!! dataframe cols:", pdf.columns)
        pdf = _annotate_plate_sample(pdf)
        return pdf.sort_values("process_timestamp").reset_index(drop=True)

    def get_recent(
        self,
        query: str,
        min_date: str = "2024-01-01",
        plate_id: Optional[int] = None,
        sample_no: Optional[int] = None,
        sql_query_retries: int = 3,
    ) -> pd.DataFrame:
        """Run ``query`` filtered by ``min_date`` and optional plate/sample.

        Args:
            query: Base SQL (the date/plate/sample filter is appended).
            min_date: ``YYYY-MM-DD`` lower bound on ``process_timestamp``.
            plate_id: Optional plate-id filter applied client-side.
            sample_no: Optional sample-no filter applied client-side.
            sql_query_retries: Max attempts before raising.

        Returns:
            Filtered frame annotated with ``plate_id`` / ``sample_no`` and
            sorted by ``process_timestamp``.

        Raises:
            Exception: If every retry of the SQL query fails.
        """
        conditions = []
        conditions.append(f"    AND hp.process_timestamp >= '{min_date}'")
        query_parts = ""
        if plate_id is not None:
            query_parts += f" & plate_id=={plate_id}"
        if sample_no is not None:
            query_parts += f" & sample_no=={sample_no}"

        tries = 0
        data = None
        while tries < sql_query_retries:
            try:
                data = self.run_raw_query(query + "\n".join(conditions))
                break
            except Exception as e:
                print(f"!!! SQL query failed: {e}")
                tries += 1
                time.sleep(30 * tries)
                self.reconnect()
        if data is None:
            raise Exception("!!! SQL query failed after retries.")
        pdf = pd.DataFrame(data)
        print("!!! dataframe shape:", pdf.shape)
        print("!!! dataframe cols:", pdf.columns)
        pdf = _annotate_plate_sample(pdf)
        return (
            pdf.query(f"process_timestamp >= '{min_date}'" + query_parts)
            .sort_values("process_timestamp")
            .reset_index(drop=True)
        )
