"""Plate/platemap lookups against the live HTE service with legacy fallback.

``HTEPlateAPI`` queries the live HTE Plate API for plate ids at or above
``legacy_plateid_threshold`` (10000 by default), and transparently delegates
to ``HTELegacyAPI`` for older ids. Authentication and S3 access are
provided by a ``HelaoLoader`` constructed from an environment file.

A 404 from the live service means "no such plate". An outage (no credentials,
a transport error, or any status other than 200/404) is a different thing:
``lookup_plate`` raises ``PlateAPIUnavailable`` for it, while ``get_info``
folds both into ``None``.
"""

__all__ = ["HTEPlateAPI", "PlateAPIUnavailable"]

import os

import httpx
import mendeleev
import pandas as pd

from helao.core.drivers.data.loaders.helao_loader import HelaoLoader
from helao.helpers import helao_logging as logging
from helao.helpers.legacy_api import HTELegacyAPI

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PlateAPIUnavailable(RuntimeError):
    """The live plate API could not answer (as opposed to "plate not found")."""


class HTEPlateAPI:
    """Combined live + legacy accessor for HTE plate data.

    A 404 from the live service means the plate does not exist: ``get_info``
    returns ``None`` for it, so the ``check_*`` helpers answer ``False`` (or
    consult the legacy API for ids below ``legacy_plateid_threshold``).

    Attributes:
        loader: Optional ``HelaoLoader`` providing AWS/S3 credentials.
        map_cache: Cache of parsed platemap DataFrames keyed by map id.
        legacy_plateid_threshold: Plate ids below this value are served from
            ``HTELegacyAPI`` rather than the live service.
        legacy_api: ``HTELegacyAPI`` instance used for fallbacks.
    """

    def __init__(self, env_file: str | None = None):
        """Construct the API client and prime the legacy fallback.

        Args:
            env_file: Path to an environment file passed to ``HelaoLoader``.
                When omitted, the ``HELAO_CREDENTIALS`` environment variable
                is consulted instead.
        """
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
    def has_access(self) -> bool:
        """Return ``True`` when AWS (or the legacy paths) can be reached."""
        if self.loader is None:
            return self.legacy_api.has_access
        try:
            sts_client = self.loader.sess.client("sts")
            sts_client.get_caller_identity()
            return True
        except Exception:
            LOGGER.error("No access to AWS services", exc_info=True)
            return False

    def lookup_plate(self, plateid: int) -> dict | None:
        """Look a plate up in the live Plate API, telling absent from unreachable.

        Args:
            plateid: Numeric plate identifier.

        Returns:
            The plate record, or ``None`` when the API says the plate does not
            exist (404, or a 200 whose ``plate_id`` is not ``plateid``).

        Raises:
            PlateAPIUnavailable: No credentials, a transport error, or any
                status other than 200 and 404.
        """
        if self.loader is None:
            raise PlateAPIUnavailable("no plate API credentials loaded")
        try:
            resp = httpx.get(
                f"{self.loader.hcred.PLATE_API}/live/plate/id/{plateid}",
                headers={"X-Api-Key": self.loader.hcred.PLATE_API_KEY},
                timeout=30,
            )
        except (httpx.HTTPError, AttributeError) as exc:
            # AttributeError: a loader whose credentials lack PLATE_API[_KEY]
            raise PlateAPIUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise PlateAPIUnavailable(f"HTTP {resp.status_code}")
        try:
            rec = resp.json()
        except ValueError as exc:
            raise PlateAPIUnavailable("HTTP 200 with a non-JSON body") from exc
        try:
            found = isinstance(rec, dict) and int(rec["plate_id"]) == int(plateid)
        except (KeyError, TypeError, ValueError):
            found = False
        if not found:
            LOGGER.warning(f"plate API answered 200 without plate_id {plateid}")
            return None
        return rec

    def get_info(self, plateid: int) -> dict | None:
        """Fetch the plate info record from the live Plate API.

        Args:
            plateid: Numeric plate identifier.

        Returns:
            The decoded JSON info dict, or ``None`` when the plate does not
            exist (404) or the API cannot be reached. Use ``lookup_plate`` to
            tell those apart.
        """
        try:
            return self.lookup_plate(plateid)
        except PlateAPIUnavailable:
            LOGGER.error("Cannot find plateid info.", exc_info=True)
            return None

    def get_print_plateid(self, plateid: int) -> dict | None:
        """Return the most recent PVD print record for ``plateid``.

        Args:
            plateid: Numeric plate identifier.

        Returns:
            The latest print dict (by ``print_date``), or ``None`` on error.
        """
        try:
            headers = {"X-Api-Key": self.loader.hcred.PLATE_API_KEY}
            resp = httpx.get(
                f"{self.loader.hcred.PLATE_API}/live/pvd_printplate/{plateid}/list",
                headers=headers,
                timeout=30,
            )
            prints = resp.json()
            latest_print = sorted(prints, key=lambda x: x["print_date"], reverse=True)[
                0
            ]
            return latest_print
        except Exception:
            LOGGER.error("Cannot find plateid info.", exc_info=True)
            return None

    def get_platemap(self, map_id: int) -> pd.DataFrame:
        """Fetch and cache the platemap CSV for a given map id from S3.

        Args:
            map_id: Numeric platemap identifier.

        Returns:
            The platemap as a ``pandas.DataFrame`` with cleaned column
            names.
        """
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
        """Return the platemap as a list of per-sample dicts.

        Args:
            map_id: Numeric platemap identifier.

        Returns:
            One dict per sample with a synthesised ``sample_no`` field.
        """
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
        """Return the platemap dict-list associated with ``plateid``.

        Falls back to ``HTELegacyAPI`` for legacy plate ids and to ``None``
        when no ``screening_map_id`` is published for the plate.
        """
        infod = self.get_info(plateid)
        if infod is None:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.get_info_plateid(plateid)
            return None
        if "screening_map_id" not in infod:
            return None
        screening_map_id = infod["screening_map_id"]
        return self.get_platemapdlist(screening_map_id)

    def get_platemap_plateid(self, plateid: int):
        """Return the platemap for ``plateid``, using legacy paths when needed."""
        infolist = self.get_info_plateid(plateid)
        if infolist is None:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.get_platemap_plateid(plateid)
        else:
            return infolist

    def get_rcp_plateid(self, plateid: int):
        """Forward an RCP lookup to ``HTELegacyAPI`` (currently a no-op)."""
        LOGGER.info(f" ... get rcp for plateid: {plateid}")
        return self.legacy_api.get_rcp_plateid(plateid)

    def check_plateid(self, plateid: int) -> bool:
        """Return ``True`` when an info record exists for ``plateid``."""
        infod = self.get_info(plateid)
        # 1. checks that the plateid (info file) exists
        if infod is not None:
            return True
        else:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.check_plateid(plateid)
            return False

    def check_printrecord_plateid(self, plateid: int):
        """Return ``True`` when the info record has a ``screening_print_id``."""
        infod = self.get_info(plateid)
        if infod is not None:
            if "screening_print_id" not in infod:
                return False
            else:
                return True
        else:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.check_printrecord_plateid(plateid)
            return False

    def check_annealrecord_plateid(self, plateid: int):
        """Return ``True`` when the info record contains an ``anneals`` block."""
        infod = self.get_info(plateid)
        if infod is not None:
            if "anneals" not in infod:
                return False
            else:
                return True
        else:
            if plateid < self.legacy_plateid_threshold:
                return self.legacy_api.check_annealrecord_plateid(plateid)
            return False

    def get_print(self, print_id: str) -> dict | None:
        """Fetch a print record by id from the live Plate API.

        Args:
            print_id: The print identifier.

        Returns:
            The decoded print dict, or ``None`` on error.
        """
        try:
            headers = {"X-Api-Key": self.loader.hcred.PLATE_API_KEY}
            resp = httpx.get(
                f"{self.loader.hcred.PLATE_API}/live/pvd_print/id/{print_id}",
                headers=headers,
                timeout=30,
            )
            return resp.json()
        except Exception:
            LOGGER.error("Could not locate print_id.", exc_info=True)

    def get_elements_plateid(
        self,
        plateid: int | dict,
        exclude_elements_list: list = [],
        **kwargs,
    ) -> list[str] | None:
        """Return the symbols of the print elements for a plate.

        For legacy plate ids the call is forwarded to ``HTELegacyAPI``.
        Otherwise the screening print is fetched, its source ``chemical_id``
        strings are mapped to element symbols via ``mendeleev``, and common
        gas/noble-gas symbols are filtered out.

        Args:
            plateid: Numeric plate identifier or a pre-loaded info dict.
            exclude_elements_list: Additional element symbols to drop.
            **kwargs: Forwarded to the legacy fallback when applicable.

        Returns:
            The filtered list of element symbols, or ``None`` on failure.
        """
        if isinstance(plateid, dict):
            infofiled = plateid
        else:
            infofiled: dict | None = self.get_info(plateid)
            if infofiled is None:
                if plateid < self.legacy_plateid_threshold:
                    return self.legacy_api.get_elements_plateid(
                        plateid=plateid,
                        exclude_elements_list=exclude_elements_list,
                        **kwargs,
                    )
                return None
        print_id: str | None = infofiled.get("screening_print_id", None)
        if print_id is None:
            return None

        printd = self.get_print(print_id)
        if "sources" not in printd.keys() and isinstance(plateid, int):
            LOGGER.warning(
                "No sources found in print record. Using alternate retrieval."
            )
            printd = self.get_print_plateid(plateid)

        if printd is not None and self.loader is not None:

            els = [
                d["chemical_id"].split("_")[0].capitalize() for d in printd["sources"]
            ]
            els = [
                el
                for el in els
                if el not in ("O", "Ar", "N", "C", "He", "Ne", "Kr", "Xe", "Rn", "")
            ]
            el_syms = [mendeleev.element(el).symbol for el in els]

            return [el for el in el_syms if el not in exclude_elements_list]

        else:
            LOGGER.warning("Could not retrieve elements.")
            LOGGER.warning(f"printd: {printd}")
            LOGGER.warning(f"loader: {self.loader}")
            return None
