import io
import json
from uuid import UUID

import boto3
from sqlmodel import Session, text, create_engine



class HelaoLoader:
    """Provides cached access to S3 and SQL"""

    def __init__(
        self,
        awscli_profile_name: str = "default",
        cache_s3: bool = False,
        cache_json: bool = True,
    ):
        self.sess = boto3.Session(profile_name=awscli_profile_name)
        self.cli = self.sess.client("s3")
        self.res = self.sess.resource("s3")
        self.cache_s3 = cache_s3
        self.cache_json = cache_json
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self.s3_cache = {}  # {s3_path: hlo_dict}
        self.sql_cache = {}  # {(uuid, type): json_dict}
        self.last_seq_uuid = ""
        self.engine = create_engine(f"//postgresql://{user}:{pw}@{self.dbhost}:{self.dbport}/{self.dbname}")

    def __del__(self):
        self.cli.close()
    
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

    def get_act(self, action_uuid: UUID):
        jd = self.act_cache.get(action_uuid, self.get_json("action", action_uuid))
        if self.cache_json:
            self.act_cache[action_uuid] = jd
        return jd

    def get_exp(self, experiment_uuid: UUID):
        jd = self.exp_cache.get(
            experiment_uuid, self.get_json("experiment", experiment_uuid)
        )
        if self.cache_json:
            self.exp_cache[experiment_uuid] = jd
        return jd

    def get_seq(self, sequence_uuid: UUID):
        if sequence_uuid != self.last_seq_uuid:
            self.clear_cache()
            self.last_seq_uuid = sequence_uuid
        jd = self.seq_cache.get(sequence_uuid, self.get_json("sequence", sequence_uuid))
        if self.cache_json:
            self.seq_cache[sequence_uuid] = jd
        return jd

    def get_pro(self, process_uuid: UUID):
        jd = self.pro_cache.get(process_uuid, self.get_json("process", process_uuid))
        if self.cache_json:
            self.pro_cache[process_uuid] = jd
        return jd

    def get_hlo(self, action_uuid: UUID, hlo_fn: str):
        keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}.json"
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
        ) not in self.sql_cache.keys():
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
                dict(resp[0]) if resp else {}
            )
        return self.sql_cache[
            (
                helao_type,
                obj_uuid,
            )
        ]
