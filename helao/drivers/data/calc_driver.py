""" Local data calculation server

This server performs calculations on locally saved data for in-situ amendment of running
sequences, i.e. repeated experiment looping, thresholding, etc.

TODO:
Calc.fill_syringe_volume_check() and Calc.check_co2_purge_level() need to be updated to
handle orchestrator requests originating outside of the config launch group.

"""
import time
import os
import numpy as np
from collections import defaultdict
from copy import copy
from scipy.signal import savgol_filter
from ruamel.yaml import YAML

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.servers.base import Base, Active
from helao.helpers.premodels import Experiment
from helao.helpers.file_mapper import FileMapper
from helao.helpers.dispatcher import async_private_dispatcher


def handlenan_savgol_filter(
    d_arr, window_length, polyorder, delta=1.0, deriv=0, replacenan_value=0.1
):
    """Custom savgol_filter from JCAPDataProcess uvis_basics.py, updated for array ops."""
    try:
        return savgol_filter(d_arr, window_length, polyorder, delta=delta, deriv=deriv)
    except Exception:
        nans = np.isnan(d_arr)
        if len(nans) > 1:
            d_arr[nans] = replacenan_value
        return savgol_filter(d_arr, window_length, polyorder, delta=delta, deriv=deriv)


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


def squeeze_foms(d):
    sd = {}
    for k, v in d.items():
        if isinstance(v, np.ndarray):
            if len(v.shape) > 1:
                sv = v.mean(axis=1).tolist()
            else:
                sv = v.tolist()
        else:
            sv = v
        sd[k] = sv
    return sd


class Calc:
    """In-sequence FOM calculation driver."""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.yaml = YAML(typ="safe")
        self.world_config = self.base.app.helao_cfg

    def gather_seq_data(self, seq_reldir: str, action_name: str):
        """Get all files using FileMapper to traverse ACTIVE/FINISHED/SYNCED."""
        active_save_dir = self.base.helaodirs.save_root.__str__()
        seq_absdir = os.path.join(active_save_dir, seq_reldir)
        FM = FileMapper(seq_absdir)
        paths = [x for x in FM.relstrs if action_name in x]
        hlos = sorted([x for x in paths if x.endswith(".hlo")])
        ymls = sorted([x for x in paths if x.endswith(".yml")])

        if len(hlos) != len(ymls):
            LOGGER.error(f"mismatch number of data files ({len(hlos)}), metadata files ({len(ymls)})")
            return {}

        hlo_dict = {}
        for hp, yp in zip(hlos, ymls):
            meta, data = FM.read_hlo(hp)
            actd = FM.read_yml(yp)

            expp = os.path.dirname(os.path.dirname(yp))
            ep = [
                x
                for x in FM.relstrs
                if x.startswith(expp)
                and x.endswith(".yml")
                and os.path.dirname(x) == expp
            ][0]
            expd = FM.read_yml(ep)

            hlo_dict[hp] = {
                "meta": meta,
                "data": data,
                "actd": actd,
                "expd": expd,
            }

        return hlo_dict

    def gather_seq_exps(self, seq_reldir: str, exp_name: str):
        """Get all exp dicts using FileMapper to traverse ACTIVE/FINISHED/SYNCED."""
        active_save_dir = self.base.helaodirs.save_root.__str__()
        seq_absdir = os.path.join(active_save_dir, seq_reldir)
        FM = FileMapper(seq_absdir)
        if exp_name == "*":
            paths = FM.relstrs
        else:
            paths = [x for x in FM.relstrs if exp_name in x]
        ymls = sorted([x for x in paths if x.endswith("exp.yml")])
        yml_dict = {}
        for ep in ymls:
            expd = FM.read_yml(ep)
            yml_dict[ep] = expd
        return yml_dict

    def get_seq_dict(self, seq_reldir: str):
        """Get sequence dict."""
        active_save_dir = self.base.helaodirs.save_root.__str__()
        seq_absdir = os.path.join(active_save_dir, seq_reldir)
        FM = FileMapper(seq_absdir)
        ymls = [x for x in FM.relstrs if x.endswith("seq.yml")]
        yml_dict = {}
        for sp in ymls:
            seqd = FM.read_yml(sp)
            yml_dict = seqd
        return yml_dict

    def calc_uvis_abs(self, activeobj: Active):
        """Figure of merit calculator for UVIS TR, DR, and T techniques."""
        seq_reldir = activeobj.action.get_sequence_dir()
        hlo_dict = self.gather_seq_data(seq_reldir, "acquire_spec")

        params = activeobj.action.action_params
        skip_nspec = params.get("skip_nspec", 0)
        spec_types = ["T", "R"]
        ru_keys = ("ref_dark", "ref_light", "data")
        specd = {}
        # specd holds bkg-sub, normalized spectra for "T" and/or "R"
        # specd["T"] = {
        #     "smplist": list of sample_labels with len (num_samples)
        #     "action_uuids": list of action_uuids, ordered by smplist
        #     "bsnlist": list of background-sub'd, normalized spectra, ordered by smplist
        #     "wlarr": mean wavelength array over samples with shape (num_wavlengths,)
        #     "technique": technique_name from experiment yaml
        # }
        refd = defaultdict(dict)
        # refd holds raw ref_dark and ref_light spectra
        for spec in spec_types:
            # run_use dict 'rud' holds per-sample averaged signals
            rud = {
                ru: {
                    p: d
                    for p, d in hlo_dict.items()
                    if (d["actd"]["run_use"] == ru)
                    and (
                        d["actd"]["action_server"]["server_name"].split("_")[1] == spec
                    )
                }
                for ru in ru_keys
            }

            for rk in list(rud.keys()):
                for dk in list(rud[rk].keys()):
                    rud["technique_name"] = rud[rk][dk]["actd"]["technique_name"]
                    data = rud[rk][dk]["data"]
                    if len(np.array(data).shape) > 1:
                        if len(data) > skip_nspec:
                            data = data[skip_nspec:]
                        else:
                            data = data[-1:]
                    epochs = data["epoch_s"]
                    vals = [
                        data[chk]
                        for chk in sorted(
                            [k for k in data.keys() if k.startswith("ch_")],
                            key=lambda x: int(x.split("_")[-1]),
                        )
                    ]
                    arr = np.array(vals).transpose()
                    rud[rk][dk].update(
                        {
                            "raw": arr,
                            "median": np.median(arr, axis=0),
                            "mean": arr.mean(axis=0),
                            "epoch": epochs,
                        }
                    )

            for ref_type in ["ref_dark", "ref_light"]:
                if rud[ref_type]:
                    actuuids = []
                    smplist = []
                    wllist = []
                    siglist = []

                    for d in rud[ref_type].values():
                        actd = d["actd"]
                        solid_matches = [
                            s["global_label"]
                            for s in actd["samples_in"]
                            if s["sample_type"] == "solid"
                        ]
                        assem_matches = [
                            s["parts"]
                            for s in actd["samples_in"]
                            if s["sample_type"] == "assembly"
                        ]
                        solid_smp = False
                        if solid_matches:
                            solid_smp = solid_matches[0]
                        elif assem_matches:
                            parts = assem_matches[0]
                            solid_parts = [
                                x["global_label"]
                                for x in parts
                                if x["sample_type"] == "solid"
                            ]
                            if solid_parts:
                                solid_smp = solid_parts[0]
                        if solid_smp:
                            smplist.append(solid_smp)
                            wllist.append(d["meta"]["optional"]["wl"])
                            actuuids.append(actd["action_uuid"])
                            siglist.append(d["mean"].tolist())

                    wlarr = np.array(wllist).mean(axis=0)
                    refd[ref_type][spec] = {
                        "smplist": smplist,
                        "action_uuids": actuuids,
                        "siglist": siglist,
                        "wlarr": wlarr,
                        "technique": rud["technique_name"],
                    }

            if rud["ref_dark"] and rud["ref_light"] and rud["data"]:
                refdark = np.vstack([d["mean"] for d in rud["ref_dark"].values()])
                reflight = np.vstack([d["mean"] for d in rud["ref_light"].values()])
                mindark = refdark.min(axis=0)
                maxlight = reflight.max(axis=0)
                actuuids = []
                smplist = []
                wllist = []
                bsnlist = []
                epochlist = []

                for d in rud["data"].values():
                    actd = d["actd"]
                    solid_matches = [
                        s["global_label"]
                        for s in actd["samples_in"]
                        if s["sample_type"] == "solid"
                    ]
                    assem_matches = [
                        s["parts"]
                        for s in actd["samples_in"]
                        if s["sample_type"] == "assembly"
                    ]
                    solid_smp = False
                    if solid_matches:
                        solid_smp = solid_matches[0]
                    elif assem_matches:
                        parts = assem_matches[0]
                        solid_parts = [
                            x["global_label"]
                            for x in parts
                            if x["sample_type"] == "solid"
                        ]
                        if solid_parts:
                            solid_smp = solid_parts[0]
                    if solid_smp:
                        smplist.append(solid_smp)
                        wllist.append(d["meta"]["optional"]["wl"])
                        actuuids.append(actd["action_uuid"])
                        bsnlist.append(d["raw"])

                wlarr = np.array(wllist).mean(axis=0)
                mini = np.where(wlarr > params["lower_wl"])[0].min()
                maxi = np.where(wlarr < params["upper_wl"])[0].max()

                refdark = np.vstack([d["mean"] for d in rud["ref_dark"].values()])[
                    :, mini:maxi
                ]
                reflight = np.vstack([d["mean"] for d in rud["ref_light"].values()])[
                    :, mini:maxi
                ]
                mindark = refdark.min(axis=0)
                maxlight = reflight.max(axis=0)

                specd[spec] = {
                    "smplist": smplist,
                    "action_uuids": actuuids,
                    "bsnlist": [
                        (x[:, mini:maxi] - mindark) / (maxlight - mindark)
                        for x in bsnlist
                    ],
                    "wlarr": wlarr[mini:maxi],
                    "epoch": epochlist,
                    "technique": rud["technique_name"],
                }

        if not specd:
            LOGGER.info("Missing references and/or data. Cannot calculate FOMs.")
            return {}

        pred = {}
        binds = []
        # pred holds intermediate outputs for "T", "R", and/or "TR"
        # pred["TR"] = {
        #     "full": full resolution vectors between lower_wl and upper_wl limits
        #     "bin": binned 'full' vectors
        #     "smooth": smoothed 'bin' vectors
        #     "smooth_refadj": refadjust() applied to 'smooth' vectors
        #     "smooth_refadj_scl": max-normalized 'smooth_refadj'
        # }
        # pred["TR"]["full"]["sig"] vector refers to "TR_unsmth_fullrng"
        # pred["TR"]["bin"]["sig"] vector refers to "TR_unsmth_binned"
        # pred["TR"]["smooth"]["sig"] vector refers to "TR_smth"
        # pred["TR"]["smooth_refadj"]["sig"] vector refers to "TR_smth_refadj"
        for k, sd in specd.items():
            pred[k] = {
                "full": {},
                "bin": {},
                "smooth": {},
                "smooth_refadj": {},
                "smooth_refadj_scl": {},
            }
            wl = np.array(sd["wlarr"])
            wlmask = np.where((wl > params["lower_wl"]) & (wl < params["upper_wl"]))[0]
            pred[k]["full"]["wl"] = wl[wlmask]

            shortest = min([x.shape[0] for x in sd["bsnlist"]])
            trunc_bsnlist = [x[:shortest] for x in sd["bsnlist"]]
            trunc_epoch = [x[:shortest] for x in sd["epoch"]]
            pred[k]["full"]["sig"] = np.array(trunc_bsnlist)[:, :, wlmask]
            pred[k]["full"]["epoch"] = np.array(trunc_epoch)
            binds = [
                [
                    y
                    for y in range(x, x + params["bin_width"])
                    if y < pred[k]["full"]["wl"].shape[0]
                ]
                for x in range(0, pred[k]["full"]["wl"].shape[0], params["bin_width"])
            ]
            pred[k]["binds"] = binds  # list of lists of indices per bin
            rsi = [np.median(inds).astype(int) for inds in pred[k]["binds"]]
            pred[k]["rsi"] = rsi  # raw indices from full vector

            for bin_key in ("bin", "smooth", "smooth_refadj", "smooth_refadj_scl"):
                pred[k][bin_key]["wl"] = pred["T"]["full"]["wl"][rsi]  # center index of bin
                pred[k][bin_key]["epoch"] = pred[k]["full"]["epoch"]
                
            hv = [
                1239.8 / x for x in pred[k]["bin"]["wl"]
            ]  # convert binned wl[nm] to energy[eV]
            pred[k]["hv"] = np.array(hv)
            dx = [hv[1] - hv[0]]
            dx += [(hv[idx + 1] - hv[idx - 1]) / 2.0 for idx in range(1, len(rsi) - 1)]
            dx += [hv[-1] - hv[-2]]
            pred[k]["dx"] = np.array(dx)

        smplist = []
        if specd.get("T", {}) and specd.get("R", {}):  # TR_UVVIS technique
            if pred["T"]["binds"] != pred["R"]["binds"]:
                raise Exception

            pred["TR"] = {
                "full": {},
                "bin": {},
                "smooth": {},
                "smooth_refadj": {},
                "smooth_refadj_scl": {},
            }
            smplist = specd["T"]["smplist"]
            smpT = np.array(smplist)
            asT = np.argsort(smpT)
            arrTR = pred["T"]["full"]["sig"] / (1 - pred["R"]["full"]["sig"][asT, :, :])
            pred["TR"]["full"]["sig"] = arrTR
            omTR = 1 - pred["T"]["full"]["sig"] - pred["R"]["full"]["sig"][asT, :, :]
            omT = 1 - pred["T"]["full"]["sig"]
            pred["TR"]["full"]["omTR"] = omTR
            pred["TR"]["full"]["omT"] = omT
            pred["TR"]["full"]["abs"] = -np.log(arrTR)
            for copyk in ("binds", "rsi", "hv", "dx"):
                pred["TR"][copyk] = pred["T"][copyk]
            pred["TR"]["bin"]["wl"] = pred["T"]["bin"]["wl"]

        elif specd.get("T", {}) and not specd.get("R", {}):  # T_UVVIS only
            smplist = specd["T"]["smplist"]
            pred["T"]["full"]["abs"] = -np.log(pred["T"]["full"]["sig"])
            omT = 1 - pred["T"]["full"]["sig"]
            pred["T"]["full"]["omT"] = omT

        elif specd.get("R", {}) and not specd.get("T", {}):  # DR_UVVIS only
            smplist = specd["R"]["smplist"]
            pred["R"]["full"]["abs"] = (1.0 - np.log(pred["R"]["full"]["sig"])) ** 2 / (
                2.0 * pred["R"]["full"]["sig"]
            )

        for sk in [pk for pk in pred.keys() if pk in ("T", "R", "TR")]:
            # bin full arrays that haven't been binned
            for k, arr in pred[sk]["full"].items():
                if k not in pred[sk]["bin"].keys():
                    pred[sk]["bin"][k] = [
                        arr[:, :, inds].mean(axis=-1) for inds in binds
                    ]
                    pred[sk]["bin"][k] = np.array(pred[sk]["bin"][k]).transpose(
                        (1, 2, 0)
                    )
            # smooth binned arrays that haven't been smoothed
            for k, arr in pred[sk]["bin"].items():
                if (k != "abs" or sk == "T") and k not in pred[sk]["smooth"].keys():
                    v = arr
                    v[np.isnan(v)] = 0.1
                    pred[sk]["smooth"][k] = handlenan_savgol_filter(
                        v,
                        window_length=params["window_length"],
                        polyorder=params["poly_order"],
                        delta=params["delta"],
                        deriv=0,
                    )

            (
                pred[sk]["min_rescaled"],
                pred[sk]["max_rescaled"],
                pred[sk]["smooth_refadj"]["sig"],
            ) = refadjust(
                pred[sk]["smooth"]["sig"],
                params["min_mthd_allowed"],
                params["max_mthd_allowed"],
                params["min_limit"],
                params["max_limit"],
            )

            if specd.get("T", {}) and specd.get("R", {}):
                pred[sk]["smooth_refadj"]["abs"] = -np.log(
                    pred[sk]["smooth_refadj"]["sig"]
                )
            elif specd.get("R", {}) and not specd.get("T", {}):
                pred[sk]["smooth_refadj"]["abs"] = (
                    1.0 - np.log(pred[sk]["smooth_refadj"]["sig"])
                ) ** 2 / (2.0 * pred[sk]["smooth_refadj"]["sig"])
            elif specd.get("T", {}) and not specd.get("R", {}):
                _, _, pred[sk]["smooth_refadj"]["abs"] = refadjust(
                    pred[sk]["smooth"]["abs"],
                    params["min_mthd_allowed"],
                    params["max_mthd_allowed"],
                    params["min_limit"],
                    params["max_limit"],
                )

            pred[sk]["smooth_refadj"]["DA_unscl"] = (
                pred[sk]["smooth_refadj"]["abs"] * pred[sk]["hv"]
            ) ** 2
            pred[sk]["smooth_refadj"]["DA"] = pred[sk]["smooth_refadj"][
                "DA_unscl"
            ] / np.nanmax(pred[sk]["smooth_refadj"]["DA_unscl"])
            pred[sk]["smooth_refadj"]["IA_unscl"] = (
                pred[sk]["smooth_refadj"]["abs"] * pred[sk]["hv"]
            ) ** 0.5
            pred[sk]["smooth_refadj"]["IA"] = pred[sk]["smooth_refadj"][
                "IA_unscl"
            ] / np.nanmax(pred[sk]["smooth_refadj"]["IA_unscl"])
            pred[sk]["smooth_refadj"]["DF_unscl"] = (
                pred[sk]["smooth_refadj"]["abs"] * pred[sk]["hv"]
            ) ** (2.0 / 3.0)
            pred[sk]["smooth_refadj"]["DF"] = pred[sk]["smooth_refadj"][
                "DF_unscl"
            ] / np.nanmax(pred[sk]["smooth_refadj"]["DF_unscl"])
            pred[sk]["smooth_refadj"]["IF_unscl"] = (
                pred[sk]["smooth_refadj"]["abs"] * pred[sk]["hv"]
            ) ** (1.0 / 3.0)
            pred[sk]["smooth_refadj"]["IF"] = pred[sk]["smooth_refadj"][
                "IF_unscl"
            ] / np.nanmax(pred[sk]["smooth_refadj"]["IF_unscl"])

            # abs_smooth_refadj_scl
            pred[sk]["smooth_refadj_scl"]["abs"] = pred[sk]["smooth_refadj"][
                "abs"
            ] / np.nanmax(pred[sk]["smooth_refadj"]["abs"])
            sv = pred[sk]["smooth_refadj_scl"]["abs"][::-1]
            sv[np.isnan(sv)] = 0.1
            sdx = -1 * pred[sk]["dx"][::-1]
            pred[sk]["smooth_refadj_scl"]["abs_1stderiv"] = (
                handlenan_savgol_filter(
                    sv,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=params["delta"],
                    deriv=1,
                )
                / sdx
            )
            pred[sk]["smooth_refadj_scl"]["abs_2ndderiv"] = (
                handlenan_savgol_filter(
                    sv,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=params["delta"],
                    deriv=2,
                )
                / sdx**2
            )

        datadict = {}
        interd = {}
        # assemble datadict with scalar FOMs
        if specd.get("T", {}) and specd.get("R", {}):  # TR_UVVIS technique
            interd = pred["TR"]

            evp = params["ev_parts"]
            for i in range(len(evp) - 1):
                lo, hi = evp[i], evp[i + 1]
                evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
                datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][
                    :, :, evrange
                ].mean(axis=-1)
                datadict[f"1-T_av_{lo}_{hi}"] = interd["smooth"]["omT"][
                    :, :, evrange
                ].mean(axis=-1)
            # full range
            lo, hi = evp[0], evp[-1]
            evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
            datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][
                :, :, evrange
            ].mean(axis=-1)
            datadict[f"1-T_av_{lo}_{hi}"] = interd["smooth"]["omT"][:, :, evrange].mean(
                axis=-1
            )
            datadict["TplusR_0to1"] = np.bitwise_and(
                (interd["smooth"]["omTR"] > 0.0), (interd["smooth"]["omTR"] < 1.0)
            ).all(axis=-1)

            datadict["T_0to1"] = np.bitwise_and(
                (pred["T"]["smooth"]["sig"] > 0.0), (pred["T"]["smooth"]["sig"] < 1.0)
            ).all(axis=-1)
            datadict["R_0to1"] = np.bitwise_and(
                (pred["R"]["smooth"]["sig"] > 0.0), (pred["R"]["smooth"]["sig"] < 1.0)
            ).all(axis=-1)

        elif specd.get("T", {}) and not specd.get("R", {}):  # T_UVVIS only
            interd = pred["T"]
            evp = params["ev_parts"]
            for i in range(len(evp) - 1):
                lo, hi = evp[i], evp[i + 1]
                evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
                datadict[f"1-T_av_{lo}_{hi}"] = interd["smooth"]["omT"][
                    :, :, evrange
                ].mean(axis=-1)
            # full range
            lo, hi = evp[0], evp[-1]
            evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
            datadict[f"1-T_av_{lo}_{hi}"] = interd["smooth"]["omT"][:, :, evrange].mean(
                axis=-1
            )
            datadict["T_0to1"] = np.bitwise_and(
                (pred["T"]["smooth"]["sig"] > 0.0), (pred["T"]["smooth"]["sig"] < 1.0)
            ).all(axis=-1)

        elif specd.get("R", {}) and not specd.get("T", {}):  # DR_UVVIS only
            interd = pred["R"]
            datadict["DR_0to1"] = np.bitwise_and(
                (pred["R"]["smooth"]["sig"] > 0.0), (pred["R"]["smooth"]["sig"] < 1.0)
            ).all(axis=-1)

        datadict["max_abs"] = np.nanmax(interd["smooth_refadj"]["abs"], axis=-1)
        checknanrange = np.bitwise_and(
            (interd["bin"]["wl"] >= 410), (interd["bin"]["wl"] <= 850)
        )
        datadict["abs_hasnan"] = np.any(
            np.isnan(interd["smooth_refadj"]["abs"][:, :, checknanrange]), axis=-1
        )

        evp = params["ev_parts"]
        for i in range(len(evp) - 1):
            lo, hi = evp[i], evp[i + 1]
            evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
            datadict[f"abs_{lo}_{hi}"] = -1 * np.trapz(
                interd["smooth_refadj"]["abs"][:, :, evrange], x=interd["hv"][evrange]
            )
        # full range
        lo, hi = evp[0], evp[-1]
        evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
        datadict[f"abs_{lo}_{hi}"] = -1 * np.trapz(
            interd["smooth_refadj"]["abs"][:, :, evrange], x=interd["hv"][evrange]
        )

        datadict["max_abs2ndderiv"] = np.nanmax(
            interd["smooth_refadj_scl"]["abs_2ndderiv"], axis=-1
        )
        datadict["min_abs1stderiv"] = np.nanmin(
            interd["smooth_refadj_scl"]["abs_1stderiv"], axis=-1
        )

        for z in ("DA", "IA", "DF", "IF"):
            v = interd["smooth_refadj"][z]
            v[np.isnan(v)] = 0.1
            sv = v[::-1]
            sv[np.isnan(sv)] = 0.1
            sdx = -1 * interd["dx"][::-1]
            slope = (
                handlenan_savgol_filter(
                    v,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=1.0,
                    deriv=1,
                )
                / sdx
            )
            datadict[f"{z}_minslope"] = np.nanmin(slope, axis=-1)

        datadict["sample_label"] = smplist
        datadict["min_rescaled"] = interd["min_rescaled"]
        datadict["max_rescaled"] = interd["max_rescaled"]

        for spectype in ["T", "R"]:
            if spectype in specd.keys():
                datadict[f"{spectype}__action_uuid"] = specd[spectype]["action_uuids"]

        # TODO: export interd vectors
        arraydict = defaultdict(dict)

        for rk, rd in refd.items():
            for sk, sd in rd.items():
                ad = {
                    "sample_label": sd["smplist"],
                    "action_uuids": sd["action_uuids"],
                    "wavelength": sd["wlarr"].tolist(),
                    "data": sd["siglist"],
                }
                arraydict[f"rawlen_{rk}__{sk}"] = ad

        lenmap = {
            "full": "trunclen_bkgsub",
            "bin": "interlen_binned",
            "smooth": "interlen_smooth",
            "smooth_refadj": "interlen_smoothrefadj",
            "smooth_refadj_scl": "interlen_smoothrefadjscl",
        }
        keymap = {"omTR": "one_minus_T_minus_R", "omT": "one_minus_T", "abs": "abs"}

        for sk, sd in pred.items():
            for bk, bd in sd.items():
                if not isinstance(bd, dict):
                    continue
                for ik in ["sig", "abs", "omT", "omTR"]:
                    if ik in bd.keys() and ik == "sig":
                        arrayname = f"{lenmap[bk]}__{sk}"
                    elif ik in bd.keys():
                        arrayname = f"{lenmap[bk]}__{keymap[ik]}"
                    else:
                        continue
                    uk = "T" if sk == "TR" else sk
                    ad = {
                        "sample_label": specd[uk]["smplist"],
                        "action_uuids": specd[uk]["action_uuids"],
                        "epoch": sd["bin"]["epoch"].tolist(),
                        "wavelength": sd["bin"]["wl"].tolist()
                        if bk.startswith("smooth")
                        else bd["wl"].tolist(),
                        "data": bd[ik].tolist(),
                    }
                    arraydict[f"{arrayname}"] = ad

        datadict = squeeze_foms(datadict)

        return datadict, arraydict

    async def check_co2_purge_level(self, activeobj: Active):
        params = activeobj.action.action_params
        co2_ppm_thresh = params["co2_ppm_thresh"]
        purge_if = params["purge_if"]
        present_syringe_volume_ul = params["present_syringe_volume_ul"]
        repeat_experiment_name = params["repeat_experiment_name"]
        repeat_experiment_params = params["repeat_experiment_params"]
        kwargs = params["repeat_experiment_kwargs"]
        seq_reldir = activeobj.action.get_sequence_dir()
        # seq_dict = self.get_seq_dict(seq_reldir)

        max_repeats = repeat_experiment_params.get("max_repeats", 5)

        hlo_dict = self.gather_seq_data(seq_reldir, "acquire_co2")
        all_exps = self.gather_seq_exps(seq_reldir, "*")
        latest = hlo_dict[sorted(hlo_dict.keys())[-1]]

        mean_co2_ppm = np.mean(latest["data"]["co2_ppm"])
        if isinstance(purge_if, str):
            if purge_if == "below":
                loop_condition = mean_co2_ppm < co2_ppm_thresh
            elif purge_if == "above":
                loop_condition = mean_co2_ppm > co2_ppm_thresh
            else:
                LOGGER.info("'purge_if' parameter was an unsupported string, using value 'above'")
                loop_condition = mean_co2_ppm > co2_ppm_thresh
        else:
            purge_if = float(purge_if)
            if abs(purge_if) >= 1.0:
                LOGGER.info("abs('purge_if') parameter is numerical and > 1.0, treating as percentage of threshold")
                purge_if = purge_if / 100
            else:
                LOGGER.info("abs('purge_if') parameter is numerical and < 1.0, treating as fraction of threshold")
            ## old behavior: signed value determines over or under threshold
            ## purge_if<0 means purge if current ppm is below pct diff
            ## purge_if>0 means purge if current ppm is above pct diff
            # loop_condition = (
            #     np.sign(purge_if) * (mean_co2_ppm - co2_ppm_thresh) / co2_ppm_thresh
            #     > np.sign(purge_if) * purge_if
            # )
            ## adjust next loop params in case loop condition is met (double purge_if every 2 loops)
            # repeat_experiment_params["purge_if"] = (
            #     abs(purge_if) * 2**0.5 * np.sign(purge_if)
            # )
            ## new behavior: symmetric pct difference around threshold
            loop_condition = (
                np.abs(mean_co2_ppm - co2_ppm_thresh) / co2_ppm_thresh > purge_if
            )

        if (
            present_syringe_volume_ul < 15000
        ):  # hard coded 15000ul check for syringe volume
            repeat_experiment_params["need_fill"] = True

        repeat_experiment_idxs = [
            i
            for i, x in enumerate(sorted(all_exps.keys()))
            if repeat_experiment_name in x
        ]
        current_experiment_idx = max(repeat_experiment_idxs)
        num_consecutive_repeats = 0
        for i in range(current_experiment_idx):
            if current_experiment_idx - i - 1 in repeat_experiment_idxs:
                num_consecutive_repeats += 1
            else:
                break

        if loop_condition and num_consecutive_repeats > max_repeats:
            LOGGER.info(f"mean_co2_ppm: {mean_co2_ppm} does not meet threshold condition but max_repeats ({max_repeats}) reached. Exiting.")
        elif loop_condition:
            LOGGER.info(f"mean_co2_ppm: {mean_co2_ppm} does not meet threshold condition. Looping.")
            rep_exp = Experiment(
                experiment_name=repeat_experiment_name,
                experiment_params=repeat_experiment_params,
                **kwargs,
            )
            LOGGER.info("queueing repeat experiment request on Orch")
            resp, error = await async_private_dispatcher(
                self.base.orch_key,
                self.base.orch_host,
                self.base.orch_port,
                "insert_experiment",
                params_dict={},
                json_dict={
                    "idx": 0,
                    "experiment": rep_exp.clean_dict(),
                },
            )
            LOGGER.info(f"insert_experiment got response: {resp}")
            LOGGER.info(f"insert_experiment returned error: {error}")
        else:
            LOGGER.info(f"mean_co2_ppm: {mean_co2_ppm} meets threshold condition. Exiting.")

        return_dict = {
            "epoch": float(time.time()),
            "mean_co2_ppm": float(mean_co2_ppm),
            "redo_purge": bool(loop_condition),
        }
        return return_dict

    async def fill_syringe_volume_check(self, activeobj: Active):
        params = activeobj.action.action_params
        check_volume_ul = params["check_volume_ul"]
        target_volume_ul = params["target_volume_ul"]
        present_volume_ul = params["present_volume_ul"]

        repeat_experiment_name = params["repeat_experiment_name"]
        repeat_experiment_params = params["repeat_experiment_params"]
        kwargs = params["repeat_experiment_kwargs"]

        if present_volume_ul < check_volume_ul:
            fill_needed = True
            fill_vol = target_volume_ul - present_volume_ul
            repeat_experiment_params = {"fill_volume_ul": fill_vol}
            LOGGER.info(f"current syringe volume: {present_volume_ul} does not meet threshold condition. Refilling")
        elif check_volume_ul == 0:
            fill_needed = True
            fill_vol = target_volume_ul - present_volume_ul
            repeat_experiment_params = {"fill_volume_ul": fill_vol}
            LOGGER.info(f"Refilling to target volume: {target_volume_ul}")
        else:
            fill_needed = False
            LOGGER.info(f"current syringe volume: {present_volume_ul} does meet threshold condition. No action needed.")

        if fill_needed:
            rep_exp = Experiment(
                experiment_name=repeat_experiment_name,
                experiment_params=repeat_experiment_params,
                **kwargs,
            )
            LOGGER.info("queueing repeat experiment request on Orch")
            resp, error = await async_private_dispatcher(
                self.base.orch_key,
                self.base.orch_host,
                self.base.orch_port,
                "insert_experiment",
                params_dict={},
                json_dict={
                    "idx": 0,
                    "experiment": rep_exp.clean_dict(),
                },
            )
            LOGGER.info(f"insert_experiment got response: {resp}")
            LOGGER.info(f"insert_experiment returned error: {error}")

        return_dict = {
            "epoch": float(time.time()),
            "syringe_present_volume_ul": float(present_volume_ul),
        }
        return return_dict

    def shutdown(self):
        pass
