import os
from copy import copy
from typing import List, Optional
from uuid import UUID
from datetime import datetime

import pandas as pd
import numpy as np
from pydantic import BaseModel
from scipy.signal import savgol_filter
from scipy.stats import binned_statistic
from mps_client import run_raw_query

from helao.helpers.gen_uuid import gen_uuid
from helao.drivers.data.loaders.pgs3 import HelaoLoader

ANALYSIS_DEFAULTS = {
    "ev_parts": [1.8, 2.2, 2.6, 3.0],
    "bin_width": 3,
    "window_length": 45,
    "poly_order": 4,
    "lower_wl": 370,
    "upper_wl": 700,
    "max_mthd_allowed": 1.2,
    "max_limit": 0.99,
    "min_mthd_allowed": -0.2,
    "min_limit": 0.01,
    "delta": 1.0,
    "skip_first_n": 4,
    "agg_last_secs": 2,
    "agg_method": "mean",
}

SDCUVIS_QUERY = """
SELECT
    hp.dummy,
    hp.run_type,
    hp.sequence_uuid,
    hp.experiment_uuid,
    hp.process_uuid,
    hp.process_group_index,
    hp.process_params,
    hp.technique_name,
    hp.run_use,
    hp.process_timestamp,
    hs.sequence_params,
    hs.sequence_name,
    hs.sequence_label,
    hs.sequence_timestamp,
    hs.sequence_status,
    he.experiment_params,
    he.experiment_name,
    he.experiment_status,
    ha.action_uuid,
    ha.action_params,
    ha.action_name,
    ha.action_timestamp,
    hsmp.global_label
FROM
    helao_process hp
    JOIN helao_sequence hs on hs.sequence_uuid = hp.sequence_uuid
    JOIN helao_experiment he on he.experiment_uuid = hp.experiment_uuid
    JOIN helao_action ha on ha.experiment_uuid = he.experiment_uuid
    JOIN helao_sample_process hsmpp on hsmpp.process_id = hp.id
    JOIN helao_sample hsmp on hsmp.id = hsmpp.sample_id
WHERE
    true
    AND hs.sequence_name in ('ECHEUVIS_multiCA_led', 'UVIS_T')
    AND hp.run_type='eche'
    AND ha.action_name in ('run_OCV', 'run_CA', 'acquire_spec_adv', 'acquire_spec_extrig')
    AND hs.sequence_label LIKE '%insitu%'
"""


class EcheUvisLoader(HelaoLoader):
    """ECHEUVIS process dataloader"""

    def __init__(
        self,
        awscli_profile_name: str = "default",
        cache_s3: bool = False,
        cache_json: bool = True,
    ):
        super().__init__(awscli_profile_name, cache_s3, cache_json)
        self.recent_cache = {}  # {'%Y-%m-%d': dataframe}

    def get_recent(
        self,
        min_date: Optional[str] = "2023-04-26",
        plate_id: Optional[int] = None,
        sample_no: Optional[int] = None,
    ):
        conditions = []
        if min_date is not None:
            conditions.append(f"AND hp.process_timestamp >= '{min_date}'")
        if plate_id is not None:
            conditions.append(
                f"AND hsmp.global_label LIKE 'legacy__solid__{plate_id}__%'"
            )
        if sample_no is not None:
            conditions.append(
                f"AND hsmp.global_label LIKE 'legacy__solid__%__{sample_no}'"
            )
        recent_md = sorted(
            [md for md, pi, sn in self.recent_cache if pi is None and sn is None]
        )
        recent_mdpi = sorted(
            [md for md, pi, sn in self.recent_cache if pi == plate_id and sn is None]
        )
        recent_mdsn = sorted(
            [md for md, pi, sn in self.recent_cache if pi is None and sn == sample_no]
        )
        query_parts = ""
        if plate_id is not None:
            query_parts += f" & plate_id=={plate_id}"
        if sample_no is not None:
            query_parts += f" & sample_no=={sample_no}"
        if recent_md and min_date >= recent_md[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_md[0],
                    None,
                    None,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        elif recent_mdpi and min_date >= recent_mdpi[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_mdpi[0],
                    plate_id,
                    None,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        elif recent_mdsn and min_date >= recent_mdsn[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_mdsn[0],
                    None,
                    sample_no,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        elif (
            min_date,
            plate_id,
            sample_no,
        ) not in self.recent_cache:
            data = run_raw_query(SDCUVIS_QUERY + "\n".join(conditions))
            pdf = pd.DataFrame(data)
            pdf["plate_id"] = pdf.global_label.apply(
                lambda x: x.split("_")[-2] if "solid" in x else None
            )
            pdf["sample_no"] = pdf.global_label.apply(
                lambda x: x.split("_")[-1] if "solid" in x else None
            )
            # assign solid samples from sequence params
            for suuid in set(pdf.query("sample_no.isna()").sequence_uuid):
                subdf = pdf.query("sequence_uuid==@suuid")
                spars = subdf.iloc[0]["sequence_params"]
                pid = spars["plate_id"]
                solid_samples = spars["plate_sample_no_list"]
                assemblies = sorted(
                    set(
                        subdf.query(
                            "global_label.str.contains('assembly')"
                        ).global_label
                    )
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
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = pdf.sort_values("process_timestamp")
        return self.recent_cache[
            (
                min_date,
                plate_id,
                sample_no,
            )
        ].reset_index(drop=True)


EUL = EcheUvisLoader(awscli_profile_name="htejcap", cache_s3=True)


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
            row_dict = query_df.query(f"{helao_type}_uuid==@uuid").iloc[0].to_dict()
        else:
            row_dict = self.row_dict
        self.timestamp = row_dict.get(
            f"{helao_type}_timestamp",
            self.row_dict.get(f"{helao_type}_timestamp", None),
        )
        self.params = row_dict.get(
            f"{helao_type}_params", self.row_dict.get(f"{helao_type}_params", {})
        )
        if helao_type == "process":
            self.name = row_dict.get(
                "technique_name", self.row_dict.get("technique_name", None)
            )
        else:
            self.name = row_dict.get(
                f"{helao_type}_name", self.row_dict.get(f"{helao_type}_name", None)
            )

    @property
    def json(self):
        # retrieve json metadata from S3 via HelaoAccess
        return EUL.get_json(self.helao_type, self.uuid)

    @property
    def row_dict(self):
        # retrieve row from API database via HelaoAccess
        return EUL.get_sql(self.helao_type, self.uuid)


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
    def hlo_file(self):
        """Return primary .hlo filename for this action."""
        meta = self.json
        file_list = meta.get("files", [])
        hlo_files = [x for x in file_list if x["file_name"].endswith(".hlo")]
        if not hlo_files:
            return ""
        filename = hlo_files[0]["file_name"]
        return filename

    @property
    def hlo(self):
        """Retrieve json data from S3 via HelaoLoader."""
        hlo_file = self.hlo_file
        if not hlo_file:
            return {}
        return EUL.get_hlo(self.action_uuid, hlo_file)


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


def parse_spechlo(hlod: dict):
    """Read spectrometer hlo into wavelength, epoch, spectra tuple."""
    wl = np.array(hlod["meta"]["optional"]["wl"])
    epochs = np.array(hlod["data"]["epoch_s"])
    specarr = (
        pd.DataFrame(hlod["data"])
        .sort_index(axis=1)
        .drop([x for x in hlod["data"].keys() if not x.startswith("ch_")], axis=1)
        .to_numpy()
    )
    return wl, epochs, specarr


def refadjust(v, min_mthd_allowed, max_mthd_allowed, min_limit, max_limit):
    """Normalization func from JCAPDataProcess uvis_basics.py, updated for array ops."""
    w = copy(v)
    min_rescaled = np.bitwise_and(
        (w.min(axis=-1) >= min_mthd_allowed),
        (w.min(axis=-1) < min_limit),
    )
    w[min_rescaled] = (
        w[min_rescaled] - w[min_rescaled].min(axis=-1).reshape(-1, 1) + min_limit
    )
    max_rescaled = np.bitwise_and(
        (w.max(axis=-1) <= max_mthd_allowed),
        (w.max(axis=-1) >= max_limit),
    )
    w[max_rescaled] = w[max_rescaled] / (
        w[max_rescaled].max(axis=-1).reshape(-1, 1) + 0.02
    )

    return min_rescaled, max_rescaled, w


class EcheUvisInputs:
    ref_drks: List[HelaoProcess]
    ref_drk_spec_acts: List[HelaoAction]
    ref_lights: List[HelaoProcess]
    ref_light_spec_acts: List[HelaoAction]
    baseline: HelaoProcess
    baseline_spec_act: HelaoAction
    baseline_ocv_act: HelaoAction
    insitu: HelaoProcess
    insitu_spec_act: HelaoAction
    insitu_ca_act: HelaoAction

    def __init__(
        self,
        insitu_process_uuid: UUID,
        plate_id: int,
        sample_no: int,
        query_df: pd.DataFrame,
    ):
        self.insitu = HelaoProcess(insitu_process_uuid, query_df)
        self.insitu_spec_act = HelaoAction(
            query_df.query(
                "process_uuid==@insitu_process_uuid & action_name=='acquire_spec_extrig'"
            )
            .iloc[0]
            .action_uuid,
            query_df,
        )
        self.insitu_ca_act = HelaoAction(
            query_df.query("process_uuid==@insitu_process_uuid & action_name=='run_CA'")
            .iloc[0]
            .action_uuid,
            query_df,
        )

        suuid = (
            query_df.query("process_uuid==@insitu_process_uuid").iloc[0].sequence_uuid
        )
        sdf = query_df.query("sequence_uuid==@suuid")
        self.ref_drks = [
            HelaoProcess(x, query_df)
            for x in sdf.query("run_use=='ref_dark'").process_uuid
        ]
        self.ref_drk_spec_acts = [
            HelaoAction(x, query_df)
            for x in sdf.query("run_use=='ref_dark'").action_uuid
        ]
        self.ref_lights = [
            HelaoProcess(x, query_df)
            for x in sdf.query("run_use=='ref_light'").process_uuid
        ]
        self.ref_light_spec_acts = [
            HelaoAction(x, query_df)
            for x in sdf.query("run_use=='ref_light'").action_uuid
        ]

        ddf = sdf.query("run_use=='data'")
        bdf = (
            ddf.query("experiment_name=='ECHEUVIS_sub_OCV_led'")
            .query("plate_id==@plate_id")
            .query("sample_no==@sample_no")
        )
        self.baseline = HelaoProcess(
            bdf.sort_values("action_timestamp").iloc[0].process_uuid,
            query_df,
        )
        self.baseline_spec_act = HelaoAction(
            bdf.query("action_name=='acquire_spec_extrig'")
            .sort_values("action_timestamp")
            .iloc[0]
            .action_uuid,
            query_df,
        )
        self.baseline_ocv_act = HelaoAction(
            ddf.query("action_name=='run_OCV'")
            .sort_values("action_timestamp")
            .iloc[0]
            .action_uuid,
            query_df,
        )

    @property
    def ref_dark_spec(self):
        return [x.hlo for x in self.ref_drk_spec_acts]

    @property
    def ref_light_spec(self):
        return [x.hlo for x in self.ref_light_spec_acts]

    @property
    def baseline_spec(self):
        return self.baseline_spec_act.hlo

    @property
    def baseline_ocv(self):
        return self.baseline_ocv_act.hlo

    @property
    def insitu_spec(self):
        return self.insitu_spec_act.hlo

    @property
    def insitu_ca(self):
        return self.insitu_ca_act.hlo


class EcheUvisOutputs(BaseModel):
    wavelength: list
    lower_wl_idx: int
    upper_wl_idx: int
    mean_ref_dark: list  # mean over start and end reference dark spectra
    mean_ref_light: list  # mean over start and end reference light spectra
    agg_method: str
    agg_baseline: list  # mean over final t seconds of OCV
    agg_insitu: list  # mean over final t seconds of CA
    bin_wavelength: list
    bin_baseline: list
    bin_insitu: list
    smth_baseline: list
    smth_insitu: list
    rscl_baseline: list
    rscl_insitu: list
    baseline_min_rescaled: bool
    baseline_max_rescaled: bool
    insitu_bin_rescaled: bool
    insitu_max_rescaled: bool
    mean_abs_omT_ratio: float  # mean over wavelengths
    mean_abs_omT_diff: float  # mean over wavelengths


class EcheUvisAnalysis:
    """ECHEUVIS Optical Stability Analysis for GCLD demonstration."""

    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    plate_id: int
    sample_no: int
    ca_potential_vrhe: float
    process_uuid: UUID
    inputs: EcheUvisInputs
    outputs: EcheUvisOutputs

    def __init__(
        self,
        process_uuid: UUID,
        query_df: pd.DataFrame,
        analysis_params: dict,
    ):
        self.analysis_timestamp = datetime.now()
        self.analysis_uuid = gen_uuid()
        self.analysis_params = analysis_params
        pdf = query_df.query("process_uuid==@process_uuid")
        self.plate_id = pdf.iloc[0].plate_id
        self.sample_no = pdf.iloc[0].sample_no
        self.inputs = EcheUvisInputs(
            process_uuid, self.plate_id, self.sample_no, query_df
        )
        self.process_uuid = process_uuid
        self.ca_potential_vrhe = self.inputs.insitu.process_params["CA_potential_vsRHE"]

    def calc_output(self):
        """Calculate stability FOMs and intermediate vectors."""
        rdtups = [parse_spechlo(x) for x in self.inputs.ref_dark_spec]
        rltups = [parse_spechlo(x) for x in self.inputs.ref_light_spec]
        btup = parse_spechlo(self.inputs.baseline_spec)
        itup = parse_spechlo(self.inputs.insitu_spec)

        ap = self.analysis_params
        aggfunc = np.mean if ap["agg_method"] == "mean" else np.median
        wl = btup[0]
        wlindlo = np.where(wl > ap["lower_wl"])[0].min()
        wlindhi = np.where(wl < ap["upper_wl"])[0].max()

        # mean aggregate initial and final reference dark spectra
        mean_ref_dark = np.vstack(
            [
                arr[
                    np.where(
                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
                    )[0].min() :
                ]
                for wl, ep, arr in rdtups
            ]
        ).mean(axis=0)

        # mean aggregate initial and final reference light spectra
        mean_ref_light = np.vstack(
            [
                arr[
                    np.where(
                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
                    )[0].min() :
                ]
                for wl, ep, arr in rltups
            ]
        ).mean(axis=0)

        # aggregate baseline insitu OCV spectra over final t seconds, omitting first n
        agg_baseline = aggfunc(
            [
                arr[
                    np.where(
                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
                    )[0].min() :
                ]
                for wl, ep, arr in (btup,)
            ][0],
            axis=0,
        )

        # aggregate insitu CA spectra over final t seconds, omitting first n
        agg_insitu = aggfunc(
            [
                arr[
                    np.where(
                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
                    )[0].min() :
                ]
                for wl, ep, arr in (itup,)
            ][0],
            axis=0,
        )

        inds = range(len(wl[wlindlo:wlindhi]))
        nbins = np.round(len(wl[wlindlo:wlindhi]) / ap["bin_width"]).astype(int)
        refadj_baseline = (
            (agg_baseline - mean_ref_dark) / (mean_ref_light - mean_ref_dark)
        )[wlindlo:wlindhi]
        refadj_insitu = (
            (agg_insitu - mean_ref_dark) / (mean_ref_light - mean_ref_dark)
        )[wlindlo:wlindhi]
        bin_wl = binned_statistic(inds, wl[wlindlo:wlindhi], "mean", nbins).statistic
        bin_baseline = binned_statistic(inds, refadj_baseline, "mean", nbins).statistic
        bin_insitu = binned_statistic(inds, refadj_insitu, "mean", nbins).statistic
        smth_baseline = savgol_filter(
            bin_baseline, ap["window_length"], ap["poly_order"], delta=ap["delta"]
        )
        smth_insitu = savgol_filter(
            bin_insitu, ap["window_length"], ap["poly_order"], delta=ap["delta"]
        )
        baseline_min_rscl, baseline_max_rscl, rscl_baseline = refadjust(
            smth_baseline,
            ap["min_mthd_allowed"],
            ap["max_mthd_allowed"],
            ap["min_limit"],
            ap["max_limit"],
        )
        insitu_min_rscl, insitu_max_rscl, rscl_insitu = refadjust(
            smth_insitu,
            ap["min_mthd_allowed"],
            ap["max_mthd_allowed"],
            ap["min_limit"],
            ap["max_limit"],
        )

        # create output model
        self.outputs = EcheUvisOutputs(
            wavelength=list(wl),
            lower_wl_idx=wlindlo,
            upper_wl_idx=wlindhi,
            mean_ref_dark=list(mean_ref_dark),
            mean_ref_light=list(mean_ref_light),
            agg_method=ap["agg_method"],
            agg_baseline=list(agg_baseline),
            agg_insitu=list(agg_insitu),
            bin_wavelength=list(bin_wl),
            bin_baseline=list(bin_baseline),
            bin_insitu=list(bin_insitu),
            smth_baseline=list(smth_baseline),
            smth_insitu=list(smth_insitu),
            rscl_baseline=list(rscl_baseline),
            rscl_insitu=list(rscl_insitu),
            baseline_min_rescaled=baseline_min_rscl,
            baseline_max_rescaled=baseline_max_rscl,
            insitu_bin_rescaled=insitu_min_rscl,
            insitu_max_rescaled=insitu_max_rscl,
            mean_abs_omT_ratio=np.mean(
                np.abs(np.log10((1 - rscl_insitu) / (1 - rscl_baseline)))
            ),
            mean_abs_omT_diff=np.mean(np.abs((1 - rscl_insitu) - (1 - rscl_baseline))),
        )


def batch_calc_echeuvis(
    plate_id: Optional[int] = None,
    sequence_uuid: Optional[UUID] = None,
    params: dict = {},
):
    """Generate list of EcheUvisAnalysis from sequence or plate_id (latest seq)."""
    eul = EcheUvisLoader(awscli_profile_name="htejcap", cache_s3=True)
    df = eul.get_recent(min_date=datetime.now().strftime("%Y-%m-%d"), plate_id=plate_id)

    # all processes in sequence
    pdf = df.sort_values(["sequence_timestamp", "process_timestamp"], ascending=False)
    if sequence_uuid is not None:
        pdf = pdf.query("sequence_uuid==@sequence_uuid")
    pdf = pdf.query("sequence_timestamp==sequence_timestamp.max()")

    # only SPEC actions during CA
    eudf = (
        pdf.query("experiment_name=='ECHEUVIS_sub_CA_led'")
        .query("run_use=='data'")
        .query("action_name=='acquire_spec_extrig'")
    )
    ana_params = copy(ANALYSIS_DEFAULTS)
    analist = []
    for puuid in eudf.process_uuid:
        ana = EcheUvisAnalysis(puuid, pdf, ana_params.update(params))
        ana.calc_output()
        analist.append(ana)
    return analist
