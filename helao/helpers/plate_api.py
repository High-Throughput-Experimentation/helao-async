__all__ = ["HTEPlateAPI"]

import pandas as pd
import httpx
import mendeleev

from helao.helpers import helao_logging as logging
from helao.helpers.openapi_client import OpenAPIClient
from helao.core.drivers.data.loaders.helao_loader import HelaoLoader

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class HTEPlateAPI:
    def __init__(self, env_file: str = ".env"):
        self.loader = HelaoLoader(env_file=env_file)
        self.ocli = OpenAPIClient(openapi_json_url=self.loader.hcred.OPENAPI_JSON)
        self.map_cache = {}

    @property
    def has_access(self):
        try:
            sts_client = self.loader.sess.client("sts")
            sts_client.get_caller_identity()
            return True
        except Exception:
            LOGGER.error("No access to AWS services", exc_info=True)
            return False

    def get_info(self, plate_id: int) -> dict | None:
        try:
            ep: str = self.loader.hcred.OPENAPI_JSON.replace("/openapi.json", "")
            ep += f"/plate/{plate_id}"
            resp: httpx.Response = httpx.get(ep)
            return resp.json()
        except Exception:
            LOGGER.error("Cannot find plate_id info.", exc_info=True)
            return None

    def get_platemap(self, map_id: int) -> pd.DataFrame:
        if map_id in self.map_cache:
            return self.map_cache[map_id]
        maps = [
            f
            for f in self.loader.cli.list_objects_v2(
                Bucket="sync.j", Prefix=f"hte_jcap_app_proto__unzipped/map/{map_id:04}"
            ).get("Contents", [])
            if f["Key"].endswith("mp.txt")
        ]
        map_uri = maps[0]["Key"]
        map_bytes = self.loader.get_bytes("sync.j", map_uri)
        map_df = pd.read_csv(map_bytes, skiprows=1)
        map_df.columns = [
            x.split("(")[0].replace("%", "").strip() for x in map_df.columns
        ]
        self.map_cache[map_id] = map_df
        return map_df

    def get_platemapdlist(self, map_id: int) -> list[dict]:
        map_df = self.get_platemap(map_id)
        for col in "ABCDEFGH":
            map_df[col] = map_df[col].apply(lambda x: float(x.strip()))
        map_df["sample_no"] = map_df.Sample
        return map_df.to_dict(orient="records")

    def get_info_plate_id(self, plate_id: int):
        infod = self.get_info(plate_id)
        if infod is None:
            return None
        if "screening_map_id" not in infod:
            return None
        screening_map_id = infod["screening_map_id"]
        return self.get_platemapdlist(screening_map_id)

    def check_plate_id(self, plate_id: int):
        infod = self.get_info(plate_id)
        # 1. checks that the plate_id (info file) exists
        if infod is not None:
            return True
        else:
            return False

    def check_printrecord_plate_id(self, plate_id: int):
        infod = self.get_info(plate_id)
        if infod is not None:
            if "screening_print_id" not in infod:
                return False
            else:
                return True

    def check_annealrecord_plate_id(self, plate_id: int):
        infod = self.get_info(plate_id)
        if infod is not None:
            if "anneals" not in infod:
                return False
            else:
                return True

    def get_print(self, print_id: str) -> dict | None:
        try:
            headers = {"X-Api-Key": self.loader.hcred.PLATE_API_KEY}
            resp = httpx.get(
                f"{self.loader.hcred.PLATE_API}/live/pvd_print/id/{print_id}",
                headers=headers,
            )
            return resp.json()
        except Exception:
            LOGGER.error("Could not locate print_id.", exc_info=True)

    def get_elements_plate_id(
        self,
        plate_id: int | dict,
        exclude_elements_list: list = [""],
    ) -> list[str] | None:
        if isinstance(plate_id, dict):
            infofiled: dict = plate_id
        else:
            infofiled: dict | None = self.get_info(plate_id)
            if infofiled is None:
                return None
        print_id: str | None = infofiled.get("screening_print_id", None)
        if print_id is None:
            return None
        printd = self.get_print(print_id)

        els = [
            d["chemical_id"].split("_target")[0].capitalize()
            for d in printd["sources"]
            if "_target_" in d["chemical_id"]
        ]
        el_syms = [mendeleev.element(el).symbol for el in els]

        return [el for el in el_syms if el not in exclude_elements_list]
