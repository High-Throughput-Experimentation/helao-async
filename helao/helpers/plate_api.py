__all__ = ["HTEPlateAPI"]

import os

import pandas as pd
import httpx
import mendeleev

from helao.helpers import helao_logging as logging
from helao.core.drivers.data.loaders.helao_loader import HelaoLoader
from helao.helpers.legacy_api import HTELegacyAPI

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class HTEPlateAPI:
    def __init__(self, env_file: str | None = None):
        self.loader = None
        if "HELAO_CREDENTIALS" in os.environ:
            env_file = os.environ["HELAO_CREDENTIALS"]
        if env_file is not None and os.path.exists(env_file):
            try:
                self.loader = HelaoLoader(env_file=env_file)
            except Exception:
                LOGGER.warning(
                    "Could not load HTEPlateAPI credentials from .env file.",
                    exc_info=True,
                )
        self.map_cache = {}
        self.legacy_plateid_threshold: int = 10000
        self.legacy_api = HTELegacyAPI()

    @property
    def has_access(self):
        if self.loader is None:
            return self.legacy_api.has_access
        try:
            sts_client = self.loader.sess.client("sts")
            sts_client.get_caller_identity()
            return True
        except Exception:
            LOGGER.error("No access to AWS services", exc_info=True)
            return False

    def get_info(self, plateid: int) -> dict | None:
        try:
            headers = {"X-Api-Key": self.loader.hcred.PLATE_API_KEY}
            resp = httpx.get(
                f"{self.loader.hcred.PLATE_API}/live/plate/id/{plateid}",
                headers=headers,
            )
            return resp.json()
        except Exception:
            LOGGER.error("Cannot find plateid info.", exc_info=True)
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
            try:
                map_df[col] = map_df[col].apply(lambda x: float(x.strip()))
            except Exception:
                # already float
                pass
        map_df["sample_no"] = map_df.Sample
        return map_df.to_dict(orient="records")

    def get_info_plateid(self, plateid: int):
        if plateid < self.legacy_plateid_threshold:
            return self.legacy_api.get_info_plateid(plateid)
        infod = self.get_info(plateid)
        if infod is None:
            return None
        if "screening_map_id" not in infod:
            return None
        screening_map_id = infod["screening_map_id"]
        return self.get_platemapdlist(screening_map_id)

    def get_platemap_plateid(self, plateid: int):
        if plateid < self.legacy_plateid_threshold:
            return self.legacy_api.get_platemap_plateid(plateid)
        else:
            return self.get_info_plateid(plateid)

    def get_rcp_plateid(self, plateid: int):
        LOGGER.info(f" ... get rcp for plateid: {plateid}")
        return self.legacy_api.get_rcp_plateid(plateid)

    def check_plateid(self, plateid: int):
        if plateid < self.legacy_plateid_threshold:
            return self.legacy_api.check_plateid(plateid)
        infod = self.get_info(plateid)
        # 1. checks that the plateid (info file) exists
        if infod is not None:
            return True
        else:
            return False

    def check_printrecord_plateid(self, plateid: int):
        if plateid < self.legacy_plateid_threshold:
            return self.legacy_api.check_printrecord_plateid(plateid)
        infod = self.get_info(plateid)
        if infod is not None:
            if "screening_print_id" not in infod:
                return False
            else:
                return True

    def check_annealrecord_plateid(self, plateid: int):
        if plateid < self.legacy_plateid_threshold:
            return self.legacy_api.check_annealrecord_plateid(plateid)
        infod = self.get_info(plateid)
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

    def get_elements_plateid(
        self,
        plateid: int | dict,
        exclude_elements_list: list = [""],
        **kwargs,
    ) -> list[str] | None:
        if isinstance(plateid, dict):
            infofiled = plateid
        else:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.get_elements_plateid(
                    plateid=plateid,
                    exclude_elements_list=exclude_elements_list,
                    **kwargs,
                )
            infofiled: dict | None = self.get_info(plateid)
            if infofiled is None:
                return None
        print_id: str | None = infofiled.get("screening_print_id", None)
        if print_id is None:
            return None
        printd = self.get_print(print_id)

        if printd is not None and self.loader is not None:

            els = [
                d["chemical_id"].split("_")[0].capitalize() for d in printd["sources"]
            ]
            els = [
                el
                for el in els
                if el not in ("O", "Ar", "N", "C", "He", "Ne", "Kr", "Xe", "Rn")
            ]
            el_syms = [mendeleev.element(el).symbol for el in els]

            return [el for el in el_syms if el not in exclude_elements_list]

        else:
            LOGGER.warning("Could not retrieve elements.")
            LOGGER.warning(f"printd: {printd}")
            LOGGER.warning(f"loader: {self.loader}")
            return None
