import sys
from copy import copy
from typing import List
from uuid import UUID
from datetime import datetime
import traceback

import pandas as pd
import numpy as np
from pydantic import BaseModel
from scipy.signal import savgol_filter
from scipy.stats import binned_statistic

from helaocore.version import get_filehash
from helao.helpers.gen_uuid import gen_uuid

from .base_analysis import BaseAnalysis
from helao.drivers.data.loaders.pgs3 import HelaoProcess, HelaoAction

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
    JOIN helao_action ha on ha.process_id = hp.id
    JOIN helao_sequence hs on hs.sequence_uuid = hp.sequence_uuid
    JOIN helao_experiment he on he.experiment_uuid = hp.experiment_uuid
    JOIN helao_sample_process hsmpp on hsmpp.process_id = hp.id
    JOIN helao_sample hsmp on hsmp.id = hsmpp.sample_id
WHERE
    true
    AND hs.sequence_name in ('ECHEUVIS_multiCA_led')
    AND hp.run_type='echeuvis'
    AND ha.action_name in ('run_OCV', 'run_CA', 'acquire_spec_adv', 'acquire_spec_extrig')
"""


def parse_spechlo(hlod: dict):
    """Read spectrometer hlo into wavelength, epoch, spectra tuple."""
    try:
        wl = np.array(hlod["meta"]["optional"]["wl"])
        epochs = np.array(hlod["data"]["epoch_s"])
        specarr = (
            pd.DataFrame(hlod["data"])
            .sort_index(axis=1)
            .drop([x for x in hlod["data"].keys() if not x.startswith("ch_")], axis=1)
            .to_numpy()
        )
    except Exception as err:
        str_err = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        )
        print(str_err)
        return False
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
    ref_darks: List[HelaoProcess]
    ref_dark_spec_acts: List[HelaoAction]
    ref_lights: List[HelaoProcess]
    ref_light_spec_acts: List[HelaoAction]
    baseline: HelaoProcess
    baseline_spec_act: HelaoAction
    baseline_ocv_act: HelaoAction
    insitu: HelaoProcess
    insitu_spec_act: HelaoAction
    insitu_ca_act: HelaoAction
    process_params: dict
    # solid_samples: list

    def __init__(
        self,
        insitu_process_uuid: UUID,
        plate_id: int,
        sample_no: int,
        query_df: pd.DataFrame,
    ):
        self.insitu = HelaoProcess(insitu_process_uuid, query_df)
        self.process_params = self.insitu.process_params
        self.insitu_spec_act = HelaoAction(
            query_df.query(
                "process_uuid==@insitu_process_uuid & action_name=='acquire_spec_extrig'"
                # "process_uuid==@insitu_process_uuid & action_name=='acquire_spec_adv'"
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
        self.ref_darks = [
            HelaoProcess(x, query_df)
            for x in sdf.query("run_use=='ref_dark'").process_uuid
        ]
        self.ref_dark_spec_acts = [
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
            # bdf.query("action_name=='acquire_spec_adv'")
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

        # self.solid_samples = [f"legacy__solid__{plate_id}+{sample_no}"]

    @property
    def ref_dark_spec(self):
        return [x.hlo for x in self.ref_dark_spec_acts]

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


class EcheUvisAnalysis(BaseAnalysis):
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
    analysis_codehash: str

    def __init__(
        self,
        process_uuid: UUID,
        query_df: pd.DataFrame,
        analysis_params: dict,
    ):
        self.analysis_timestamp = datetime.now()
        self.analysis_uuid = gen_uuid()
        self.analysis_params = copy(ANALYSIS_DEFAULTS)
        self.analysis_params.update(analysis_params)
        pdf = query_df.query("process_uuid==@process_uuid").reset_index(drop=True)
        # print("filtered data has shape:", pdf.shape)
        self.plate_id = int(pdf.iloc[0].plate_id)
        self.sample_no = int(pdf.iloc[0].sample_no)
        # print("assembling inputs")
        self.inputs = EcheUvisInputs(
            process_uuid, self.plate_id, self.sample_no, query_df
        )
        self.process_uuid = process_uuid
        self.ca_potential_vrhe = self.inputs.insitu.process_params["CA_potential_vsRHE"]
        # print("getting code hash")
        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)

    def calc_output(self):
        """Calculate stability FOMs and intermediate vectors."""
        rdtups = [parse_spechlo(x) for x in self.inputs.ref_dark_spec]
        rltups = [parse_spechlo(x) for x in self.inputs.ref_light_spec]
        btup = parse_spechlo(self.inputs.baseline_spec)
        itup = parse_spechlo(self.inputs.insitu_spec)

        if any([x is False for x in rdtups + rltups + [btup, itup]]):
            return False

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
        return True

