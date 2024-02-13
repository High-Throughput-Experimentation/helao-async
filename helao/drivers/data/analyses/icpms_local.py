import sys
from copy import copy
from typing import List
from uuid import UUID
from datetime import datetime

import pandas as pd
import numpy as np
from pydantic import BaseModel
from scipy.signal import savgol_filter
from scipy.stats import binned_statistic

from helaocore.version import get_filehash
from helao.helpers.gen_uuid import gen_uuid

from helao.drivers.data.loaders.localfs import HelaoProcess, HelaoAction, LocalLoader

ANALYSIS_DEFAULTS = {
    "fom_key": "ExtCal.Concentration_ppb",
}

class IcpmsInputs:
    icpms_process: HelaoProcess
    icpms_action: HelaoAction

    def __init__(
        self,
        process_uuid: UUID,
        local_loader: LocalLoader
    ):
        self.process = [
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
            ddf.query("experiment_name=='UVIS_sub_measure'")
            .query("plate_id==@plate_id")
            .query("sample_no==@sample_no")
        )
        self.insitu = HelaoProcess(
            bdf.sort_values("action_timestamp").iloc[0].process_uuid,
            query_df,
        )
        self.insitu_spec_act = HelaoAction(
            bdf.query("action_name=='acquire_spec_adv'")
            .sort_values("action_timestamp")
            .iloc[0]
            .action_uuid,
            query_df,
        )

    @property
    def ref_dark_spec(self):
        return [x.hlo for x in self.ref_dark_spec_acts]

    @property
    def ref_light_spec(self):
        return [x.hlo for x in self.ref_light_spec_acts]

    @property
    def insitu_spec(self):
        return self.insitu_spec_act.hlo


class IcpmsOutputs(BaseModel):
    wavelength: list
    lower_wl_idx: int
    upper_wl_idx: int
    mean_ref_dark: list  # mean over start and end reference dark insitutra
    mean_ref_light: list  # mean over start and end reference light insitutra
    agg_method: str
    agg_insitu: list  # mean over final t seconds of OCV
    bin_wavelength: list
    bin_insitu: list
    smth_insitu: list
    rscl_insitu: list
    insitu_min_rescaled: bool
    insitu_max_rescaled: bool


class IcpmsAnalysis:
    """Dry UVIS Analysis for GCLD demonstration."""

    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    plate_id: int
    sample_no: int
    process_uuid: UUID
    inputs: IcpmsInputs
    outputs: IcpmsOutputs
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
        pdf = query_df.query("process_uuid==@process_uuid")
        self.plate_id = pdf.iloc[0].plate_id
        self.sample_no = pdf.iloc[0].sample_no
        self.inputs = IcpmsInputs(
            process_uuid, self.plate_id, self.sample_no, query_df
        )
        self.process_uuid = process_uuid
        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)

    def calc_output(self):
        """Calculate stability FOMs and intermediate vectors."""
        rdtups = [parse_spechlo(x) for x in self.inputs.ref_dark_spec]
        rltups = [parse_spechlo(x) for x in self.inputs.ref_light_spec]
        btup = parse_spechlo(self.inputs.insitu_spec)

        if any([x is False for x in rdtups + rltups + [btup]]):
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
        agg_insitu = aggfunc(
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

        inds = range(len(wl[wlindlo:wlindhi]))
        nbins = np.round(len(wl[wlindlo:wlindhi]) / ap["bin_width"]).astype(int)
        refadj_insitu = (
            (agg_insitu - mean_ref_dark) / (mean_ref_light - mean_ref_dark)
        )[wlindlo:wlindhi]
        bin_wl = binned_statistic(inds, wl[wlindlo:wlindhi], "mean", nbins).statistic
        bin_insitu = binned_statistic(inds, refadj_insitu, "mean", nbins).statistic
        smth_insitu = savgol_filter(
            bin_insitu, ap["window_length"], ap["poly_order"], delta=ap["delta"]
        )
        insitu_min_rscl, insitu_max_rscl, rscl_insitu = refadjust(
            smth_insitu,
            ap["min_mthd_allowed"],
            ap["max_mthd_allowed"],
            ap["min_limit"],
            ap["max_limit"],
        )

        # create output model
        self.outputs = IcpmsOutputs(
            wavelength=list(wl),
            lower_wl_idx=wlindlo,
            upper_wl_idx=wlindhi,
            mean_ref_dark=list(mean_ref_dark),
            mean_ref_light=list(mean_ref_light),
            agg_method=ap["agg_method"],
            agg_insitu=list(agg_insitu),
            bin_wavelength=list(bin_wl),
            bin_insitu=list(bin_insitu),
            smth_insitu=list(smth_insitu),
            rscl_insitu=list(rscl_insitu),
            insitu_min_rescaled=insitu_min_rscl,
            insitu_max_rescaled=insitu_max_rscl,
        )
        return True
