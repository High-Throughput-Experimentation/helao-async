import io
import json
import time
from uuid import UUID
from typing import Optional
from datetime import datetime

import boto3
import sshtunnel
import pandas as pd
from sqlmodel import Session, text, create_engine
from helaocore.models.credentials import HelaoCredentials

# initialize in driver
LOADER = None


class HelaoLoader:
    """Provides cached access to S3 and SQL"""

    def __init__(
        self,
        env_file: str = ".env",
        cache_s3: bool = False,
        cache_json: bool = False,
        cache_sql: bool = False,
    ):
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
        self.cli.close()
        self.tunnel.stop()

    def connect(self):
        self.hcred = HelaoCredentials(_env_file=self.env_file)
        self.tunnel = sshtunnel.SSHTunnelForwarder(
            self.hcred.JUMPBOX_HOST,
            ssh_username=self.hcred.JUMPBOX_USER,
            ssh_pkey=self.hcred.JUMPBOX_KEYFILE,
            remote_bind_address=(self.hcred.API_HOST, int(self.hcred.API_PORT)),
        )
        self.tunnel.start()
        self.hcred.set_api_port(self.tunnel.local_bind_port)
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
        try:
            self.cli.close()
            self.tunnel.stop()
        except Exception as e:
            print(f"!!! Error closing tunnel: {e}")
        finally:
            self.connect()

    def run_raw_query(self, query: str):
        with Session(self.engine) as session:
            result = session.exec(text(query)).all()
        return result

    def clear_cache(self):
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}
        self.sql_cache = {}  # {(uuid, type): json_dict}

    def get_json(self, helao_type: str, uuid: UUID):
        obj = self.res.Object(
            bucket_name="helao.data", key=f"{helao_type}/{str(uuid)}.json"
        )
        obytes = io.BytesIO(obj.get()["Body"].read())
        md = json.load(obytes)
        return md

    def get_act(self, action_uuid: UUID, hmod: bool = True):
        jd = self.act_cache.get(action_uuid, self.get_json("action", action_uuid))
        if self.cache_json:
            self.act_cache[action_uuid] = jd
        if hmod:
            return HelaoAction(action_uuid)
        return jd

    def get_exp(self, experiment_uuid: UUID, hmod: bool = True):
        jd = self.exp_cache.get(
            experiment_uuid, self.get_json("experiment", experiment_uuid)
        )
        if self.cache_json:
            self.exp_cache[experiment_uuid] = jd
        if hmod:
            return HelaoExperiment(experiment_uuid)
        return jd

    def get_seq(self, sequence_uuid: UUID, hmod: bool = True):
        if sequence_uuid != self.last_seq_uuid:
            self.clear_cache()
            self.last_seq_uuid = sequence_uuid
        jd = self.seq_cache.get(sequence_uuid, self.get_json("sequence", sequence_uuid))
        if self.cache_json:
            self.seq_cache[sequence_uuid] = jd
        if hmod:
            return HelaoSequence(sequence_uuid)
        return jd

    def get_prc(self, process_uuid: UUID, hmod: bool = True):
        jd = self.pro_cache.get(process_uuid, self.get_json("process", process_uuid))
        if self.cache_json:
            self.pro_cache[process_uuid] = jd
        if hmod:
            return HelaoProcess(process_uuid)
        return jd

    def get_hlo(self, action_uuid: UUID, hlo_fn: str):
        if hlo_fn.endswith(".hlo"):
            keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}.json"
        elif hlo_fn.endswith(".hlo.json"):
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

    def get_sql(self, helao_type: str, obj_uuid: UUID):
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

    def __init__(self, helao_type: str, uuid: UUID, query_df: pd.DataFrame = None):
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
            self.meta_dict = self._meta_dict
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

    def __init__(self, uuid: UUID, query_df: pd.DataFrame = None):
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
            if x["file_name"].endswith(".hlo") or x["file_name"].endswith(".hlo.json")
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

    def __init__(self, uuid: UUID, query_df: pd.DataFrame = None):
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

    def __init__(self, uuid: UUID, query_df: pd.DataFrame = None):
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

    def __init__(self, uuid: UUID, query_df: pd.DataFrame = None):
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
                time.sleep(30*tries)
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
                time.sleep(30*tries)
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
