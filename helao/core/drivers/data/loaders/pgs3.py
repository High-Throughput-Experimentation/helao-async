import time
from uuid import UUID
from typing import Optional

import pandas as pd
from helao.core.drivers.data.loaders.helao_loader import HelaoLoader

LOADER: HelaoLoader = None


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
