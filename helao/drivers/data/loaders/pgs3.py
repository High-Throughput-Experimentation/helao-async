import time
from uuid import UUID
from typing import Optional
from datetime import datetime

import pandas as pd
from helao.drivers.data.loaders.helao_loader import HelaoLoader

# initialize in driver
LOADER: HelaoLoader = None


class HelaoSolid:
    sample_label: str
    # composition: dict

    def __init__(self, sample_label):
        self.sample_label = sample_label


class HelaoModel:
    name: str
    uuid: UUID
    helao_type: str
    timestamp: datetime
    params: dict

    def __init__(self, helao_type: str, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
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
    def json(self):
        # retrieve json metadata from S3 via HelaoAccess
        return LOADER.get_json(self.helao_type, self.uuid)

    @property
    def _meta_dict(self):
        # retrieve row from API database via HelaoAccess
        return LOADER.get_sql(self.helao_type, self.uuid)


class HelaoAction(HelaoModel):
    action_name: str
    action_uuid: UUID
    action_timestamp: datetime
    action_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        super().__init__(helao_type="action", uuid=uuid, query_df=query_df)
        self.action_name = self.name
        self.action_uuid = self.uuid
        self.action_timestamp = self.timestamp
        self.action_params = self.params

    @property
    def hlo_file_tup(self):
        """Return primary .hlo filename, filetype, and data keys for this action."""
        meta = self.json
        file_list = meta.get("files", [])
        hlo_files = [
            x
            for x in file_list
            if x["file_name"].endswith(".hlo")
            or x["file_name"].endswith(".json")
            or x["file_type"] in ["helao__json_file", "json__file"]
        ]
        if not hlo_files:
            return "", "", []
        first_hlo = hlo_files[0]
        retkeys = ["file_name", "file_type", "data_keys"]
        return [first_hlo.get(k, "") for k in retkeys]

    @property
    def hlo_file(self):
        """Return primary .hlo filename for this action."""
        return self.hlo_file_tup[0]

    @property
    def hlo(self):
        """Retrieve json data from S3 via HelaoLoader."""
        hlo_file = self.hlo_file
        if not hlo_file:
            return {}
        return LOADER.get_hlo(self.action_uuid, hlo_file)


class HelaoExperiment(HelaoModel):
    experiment_name: str
    experiment_uuid: UUID
    experiment_timestamp: datetime
    experiment_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        super().__init__(helao_type="experiment", uuid=uuid, query_df=query_df)
        self.experiment_name = self.name
        self.experiment_uuid = self.uuid
        self.experiment_timestamp = self.timestamp
        self.experiment_params = self.params


class HelaoSequence(HelaoModel):
    sequence_name: str
    sequence_uuid: UUID
    sequence_timestamp: datetime
    sequence_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        super().__init__(helao_type="sequence", uuid=uuid, query_df=query_df)
        self.sequence_name = self.name
        self.sequence_uuid = self.uuid
        self.sequence_timestamp = self.timestamp
        self.sequence_params = self.params


class HelaoProcess(HelaoModel):
    process_name: str
    process_uuid: UUID
    process_timestamp: datetime
    process_params: dict

    def __init__(self, uuid: UUID, query_df: Optional[pd.DataFrame] = None):
        super().__init__(helao_type="process", uuid=uuid, query_df=query_df)
        self.technique_name = self.name
        self.process_uuid = self.uuid
        self.process_timestamp = self.timestamp
        self.process_params = self.params


class EcheUvisLoader(HelaoLoader):
    """ECHEUVIS process dataloader"""

    def __init__(
        self,
        env_file: str = ".env",
        cache_s3: bool = False,
        cache_json: bool = False,
        cache_sql: bool = False,
    ):
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
    ):
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
        pdf["plate_id"] = pdf.global_label.apply(
            lambda x: (
                int(x.split("_")[-2]) if "solid" in x and "None" not in x else None
            )
        )
        pdf["sample_no"] = pdf.global_label.apply(
            lambda x: (
                int(x.split("_")[-1]) if "solid" in x and "None" not in x else None
            )
        )
        # assign solid samples from sequence params
        for suuid in set(pdf.query("sample_no.isna()").sequence_uuid):
            subdf = pdf.query("sequence_uuid==@suuid")
            spars = subdf.iloc[0]["sequence_params"]
            pid = spars["plate_id"]
            solid_samples = spars["plate_sample_no_list"]
            assemblies = sorted(
                set(subdf.query("global_label.str.contains('assembly')").global_label)
            )
            for slab, alab in zip(solid_samples, assemblies):
                pdf.loc[
                    pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                    "plate_id",
                ] = pid
                pdf.loc[
                    pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                    "sample_no",
                ] = slab

            return pdf.sort_values("process_timestamp").reset_index(drop=True)

    def get_recent(
        self,
        query: str,
        min_date: str = "2024-01-01",
        plate_id: Optional[int] = None,
        sample_no: Optional[int] = None,
        sql_query_retries: int = 3,
    ):
        conditions = []
        conditions.append(f"    AND hp.process_timestamp >= '{min_date}'")
        # recent_md = sorted(
        #     [md for md, pi, sn in self.recent_cache if pi is None and sn is None]
        # )
        # recent_mdpi = sorted(
        #     [md for md, pi, sn in self.recent_cache if pi == plate_id and sn is None]
        # )
        # recent_mdsn = sorted(
        #     [md for md, pi, sn in self.recent_cache if pi is None and sn == sample_no]
        # )
        query_parts = ""
        if plate_id is not None:
            query_parts += f" & plate_id=={plate_id}"
        if sample_no is not None:
            query_parts += f" & sample_no=={sample_no}"

        # if (
        #     min_date,
        #     plate_id,
        #     sample_no,
        # ) not in self.recent_cache or not self.cache_sql:
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
        pdf["plate_id"] = pdf.global_label.apply(
            lambda x: (
                int(x.split("_")[-2]) if "solid" in x and "None" not in x else None
            )
        )
        pdf["sample_no"] = pdf.global_label.apply(
            lambda x: (
                int(x.split("_")[-1]) if "solid" in x and "None" not in x else None
            )
        )
        # assign solid samples from sequence params
        for suuid in set(pdf.query("sample_no.isna()").sequence_uuid):
            subdf = pdf.query("sequence_uuid==@suuid")
            spars = subdf.iloc[0]["sequence_params"]
            pid = spars["plate_id"]
            solid_samples = spars["plate_sample_no_list"]
            assemblies = sorted(
                set(subdf.query("global_label.str.contains('assembly')").global_label)
            )
            for slab, alab in zip(solid_samples, assemblies):
                pdf.loc[
                    pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                    "plate_id",
                ] = pid
                pdf.loc[
                    pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                    "sample_no",
                ] = slab

            # self.recent_cache[
            #     (
            #         min_date,
            #         plate_id,
            #         sample_no,
            #     )
            # ] = pdf.sort_values("process_timestamp")

            return (
                pdf.query(f"process_timestamp >= '{min_date}'" + query_parts)
                .sort_values("process_timestamp")
                .reset_index(drop=True)
            )

        # elif recent_md and min_date >= recent_md[0]:
        #     self.recent_cache[
        #         (
        #             min_date,
        #             plate_id,
        #             sample_no,
        #         )
        #     ] = self.recent_cache[
        #         (
        #             recent_md[0],
        #             None,
        #             None,
        #         )
        #     ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        # elif recent_mdpi and min_date >= recent_mdpi[0]:
        #     self.recent_cache[
        #         (
        #             min_date,
        #             plate_id,
        #             sample_no,
        #         )
        #     ] = self.recent_cache[
        #         (
        #             recent_mdpi[0],
        #             plate_id,
        #             None,
        #         )
        #     ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        # elif recent_mdsn and min_date >= recent_mdsn[0]:
        #     self.recent_cache[
        #         (
        #             min_date,
        #             plate_id,
        #             sample_no,
        #         )
        #     ] = self.recent_cache[
        #         (
        #             recent_mdsn[0],
        #             None,
        #             sample_no,
        #         )
        #     ].query(f"process_timestamp >= '{min_date}'" + query_parts)

        # return self.recent_cache[
        #     (
        #         min_date,
        #         plate_id,
        #         sample_no,
        #     )
        # ].reset_index(drop=True)
