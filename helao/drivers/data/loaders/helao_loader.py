import io
import json

import boto3
import sshtunnel
from sqlmodel import Session, text, create_engine
from helao.core.models.credentials import HelaoCredentials

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