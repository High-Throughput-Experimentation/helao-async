import os
import numpy as np
from copy import copy
from scipy.signal import savgol_filter
from ruamel.yaml import YAML

from helaocore.models.data import DataModel
from helao.servers.base import Base
from helao.helpers.file_mapper import FileMapper


def handlenan_savgol_filter(
    d_arr, window_length, polyorder, delta=1.0, deriv=0, replacenan_value=0.1
):
    """Custom savgol_filter from JCAPDataProcess uvis_basics.py, updated for array ops."""
    nans = np.isnan(d_arr)
    xarr = np.arange(len(d_arr))
    if len(nans) > 1 and len(nans) < len(d_arr):
        d_arr[nans] = np.interp(xarr[nans], xarr[~nans], d_arr[~nans])
        naninds = np.where(np.isnan(d_arr))[0]
        if len(naninds) > 1:
            d_arr[naninds] = np.array(
                [
                    np.nanmean(d_arr[max(0, nind - 3) : min(nind + 3, len(d_arr))])
                    for nind in naninds
                ]
            )
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
        (w.min(axis=1) >= min_mthd_allowed),
        (w.min(axis=1) < min_limit),
    )
    w[min_rescaled, :] = (
        w[min_rescaled, :] - w[min_rescaled, :].min(axis=1).reshape(-1, 1) + min_limit
    )
    max_rescaled = np.bitwise_and(
        (w.max(axis=1) <= max_mthd_allowed),
        (w.max(axis=1) >= max_limit),
    )
    w[max_rescaled, :] = w[max_rescaled, :] / (
        w[max_rescaled, :].max(axis=1).reshape(-1, 1) + 0.02
    )

    return min_rescaled, max_rescaled, w


class Calc:
    """In-sequence FOM calculation driver."""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.yaml = YAML(typ="safe")

    def gather_spec_data(self, seq_reldir: str):
        """Get all spectrum files using FileMapper to traverse ACTIVE/FINISHED/SYNCED."""
        # get all files from current sequence directory
        # produce tuples, (run_type, technique_name, run_use, hlo_path)
        active_save_dir = self.base.helaodirs.save_root.__str__()
        seq_absdir = os.path.join(active_save_dir, seq_reldir)
        FM = FileMapper(seq_absdir)
        aspec_paths = [x for x in FM.relstrs if "acquire_spec" in x]
        aspec_hlos = sorted([x for x in aspec_paths if x.endswith(".hlo")])
        aspec_ymls = sorted([x for x in aspec_paths if x.endswith(".yml")])

        if len(aspec_hlos) != len(aspec_ymls):
            self.base.print_message(
                f"mismatch number of data files ({len(aspec_hlos)}), metadata files ({len(aspec_ymls)})",
                error=True,
            )
            return {}

        hlo_dict = {}
        for hp, yp in zip(aspec_hlos, aspec_ymls):
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

    def calc_uvis_abs(self, activeobj):
        """Figure of merit calculator for UVIS TR, DR, and T techniques."""
        seq_reldir = activeobj.action.get_sequence_dir()
        hlo_dict = self.gather_spec_data(seq_reldir)

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
        for spec in spec_types:
            # run_use dict 'rud' holds per-sample averaged signals
            rud = {
                ru: {
                    p: d
                    for p, d in hlo_dict.items()
                    if (d["actd"]["run_use"] == ru)
                    and (d["expd"]["experiment_params"]["spec_type"] == spec)
                }
                for ru in ru_keys
            }

            for rk in list(rud.keys()):
                for dk in list(rud[rk].keys()):
                    rud["technique_name"] = rud[rk][dk]["expd"]["experiment_params"][
                        "technique_name"
                    ]
                    data = rud[rk][dk]["data"]
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
                        }
                    )

            if rud["ref_dark"] and rud["ref_light"] and rud["data"]:
                refdark = np.vstack([d["mean"] for d in rud["ref_dark"].values()])
                reflight = np.vstack([d["mean"] for d in rud["ref_light"].values()])
                mindark = refdark.min(axis=0)
                maxlight = reflight.max(axis=0)
                actuuids = []
                smplist = []
                wllist = []
                bsnlist = []

                for d in rud["data"].values():
                    wllist.append(d["meta"]["optional"]["wl"])
                    actd = d["actd"]
                    actuuids.append(actd["action_uuid"])
                    smplist.append(
                        [
                            s["global_label"]
                            for s in actd["samples_in"]
                            if s["sample_type"] == "solid"
                        ][0]
                    )
                    bsnlist.append((d["mean"] - mindark) / (maxlight - mindark))

                wlarr = np.array(wllist).mean(axis=0)
                specd[spec] = {
                    "smplist": smplist,
                    "action_uuids": actuuids,
                    "bsnlist": bsnlist,
                    "wlarr": wlarr,
                    "technique": rud["technique_name"],
                }

        params = activeobj.action.action_params
        pred = {}
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
            pred[k]["full"]["sig"] = np.array(sd["bsnlist"])[:, wlmask]
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
            pred[k]["bin"]["wl"] = pred["T"]["full"]["wl"][rsi]  # center index of bin
            hv = [
                1239.8 / x for x in pred[k]["bin"]["wl"]
            ]  # convert binned wl[nm] to energy[eV]
            pred[k]["hv"] = np.array(hv)
            dx = [hv[1] - hv[0]]
            dx += [(hv[idx + 1] - hv[idx - 1]) / 2.0 for idx in range(1, len(rsi) - 1)]
            dx += [hv[-1] - hv[-2]]
            pred[k]["dx"] = np.array(dx)

        if len(specd.keys()) == 2:  # TR_UVVIS technique
            if pred["T"]["binds"] != pred["R"]["binds"]:
                raise Exception

            pred["TR"] = {
                "full": {},
                "bin": {},
                "smooth": {},
                "smooth_refadj": {},
                "smooth_refadj_scl": {},
            }
            smpT = np.array(specd["T"]["smplist"])
            asT = np.argsort(smpT)
            arrTR = pred["T"]["full"]["sig"] / (1 - pred["R"]["full"]["sig"][asT, :])
            pred["TR"]["full"]["sig"] = arrTR
            omTR = 1 - pred["T"]["full"]["sig"] - pred["R"]["full"]["sig"][asT, :]
            pred["TR"]["full"]["omTR"] = omTR
            pred["TR"]["full"]["abs"] = -np.log(arrTR)
            for copyk in ("binds", "rsi", "hv", "dx"):
                pred["TR"][copyk] = pred["T"][copyk]
            pred["TR"]["bin"]["wl"] = pred["T"]["bin"]["wl"]

        elif len(specd.keys()) == 1 and "T" in specd.keys():  # T_UVVIS only
            pred["T"]["full"]["abs"] = -np.log(pred["T"]["full"]["sig"])

        elif len(specd.keys()) == 1 and "R" in specd.keys():  # DR_UVVIS only
            pred["R"]["full"]["abs"] = (1.0 - np.log(pred["R"]["full"]["sig"])) ** 2 / (
                2.0 * pred["R"]["full"]["sig"]
            )

        for sk in [pk for pk in pred.keys() if pk in ("T", "R", "TR")]:
            # bin full arrays that haven't been binned
            for k, arr in pred[sk]["full"].items():
                if k not in pred[sk]["bin"].keys():
                    pred[sk]["bin"][k] = [arr[:, inds].mean(axis=1) for inds in binds]
                    pred[sk]["bin"][k] = np.array(pred[sk]["bin"][k]).transpose()
            # smooth binned arrays that haven't been smoothed
            for k, arr in pred[sk]["bin"].items():
                if k != "abs" and k not in pred[sk]["smooth"].keys():
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

            if len(specd.keys()) == 2:
                pred[sk]["smooth_refadj"]["abs"] = -np.log(
                    pred[sk]["smooth_refadj"]["sig"]
                )
            elif len(specd.keys()) == 1 and "R" in specd.keys():
                pred[sk]["smooth_refadj"]["abs"] = (
                    1.0 - np.log(pred[sk]["smooth_refadj"]["sig"])
                ) ** 2 / (2.0 * pred[sk]["smooth_refadj"]["sig"])
            else:
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
                k
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
        # assemble datadict with scalar FOMs
        if len(specd.keys()) == 2:  # TR_UVVIS technique
            interd = pred["TR"]

            evp = params["ev_parts"]
            for i in range(len(evp) - 1):
                lo, hi = evp[i], evp[i + 1]
                evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
                datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][
                    :, evrange
                ].mean(axis=1)
            # full range
            lo, hi = evp[0], evp[-1]
            evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
            datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][:, evrange].mean(
                axis=1
            )
            datadict["TplusR_0to1"] = np.bitwise_and(
                (interd["smooth"]["omTR"] > 0.0), (interd["smooth"]["omTR"] < 1.0)
            ).all(axis=1)

            datadict["T_0to1"] = np.bitwise_and(
                (pred["T"]["smooth"]["sig"] > 0.0), (pred["T"]["smooth"]["sig"] < 1.0)
            ).all(axis=1)
            datadict["R_0to1"] = np.bitwise_and(
                (pred["R"]["smooth"]["sig"] > 0.0), (pred["R"]["smooth"]["sig"] < 1.0)
            ).all(axis=1)

        elif len(specd.keys()) == 1 and "T" in specd.keys():  # T_UVVIS only
            interd = pred["T"]
            datadict["T_0to1"] = np.bitwise_and(
                (pred["T"]["smooth"]["sig"] > 0.0), (pred["T"]["smooth"]["sig"] < 1.0)
            ).all(axis=1)

        elif len(specd.keys()) == 1 and "R" in specd.keys():  # DR_UVVIS only
            interd = pred["R"]
            datadict["DR_0to1"] = np.bitwise_and(
                (pred["R"]["smooth"]["sig"] > 0.0), (pred["R"]["smooth"]["sig"] < 1.0)
            ).all(axis=1)

        datadict["max_abs"] = np.nanmax(interd["smooth_refadj"]["abs"], axis=1)
        checknanrange = np.bitwise_and(
            (interd["bin"]["wl"] >= 410), (interd["bin"]["wl"] <= 850)
        )
        datadict["abs_hasnan"] = np.any(
            np.isnan(interd["smooth_refadj"]["abs"][:, checknanrange]), axis=1
        )
        evp = params["ev_parts"]
        for i in range(len(evp) - 1):
            lo, hi = evp[i], evp[i + 1]
            evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
            datadict[f"abs_{lo}_{hi}"] = -1 * np.trapz(
                interd["smooth_refadj"]["abs"][:, evrange], x=interd["hv"][evrange]
            )
        # full range
        lo, hi = evp[0], evp[-1]
        evrange = np.bitwise_and((interd["hv"] > lo), (interd["hv"] < hi))
        datadict[f"abs_{lo}_{hi}"] = -1 * np.trapz(
            interd["smooth_refadj"]["abs"][:, evrange], x=interd["hv"][evrange]
        )

        datadict["max_abs2ndderiv"] = np.nanmax(
            interd["smooth_refadj_scl"]["abs_2ndderiv"], axis=1
        )
        datadict["min_abs1stderiv"] = np.nanmin(
            interd["smooth_refadj_scl"]["abs_1stderiv"], axis=1
        )

        for z in ("DA", "IA", "DF", "IF"):
            v = interd["smooth_refadj"][z]
            v[np.isnan(v)] = 0.1
            slope = (
                handlenan_savgol_filter(
                    v,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=1.0,
                    deriv=1,
                )
                / interd["dx"]
            )
            datadict[f"{z}_minslope"] = np.nanmin(slope, axis=1)

        datadict["sample_label"] = smplist
        datadict["min_rescaled"] = interd["min_rescaled"]
        datadict["max_rescaled"] = interd["max_rescaled"]

        # TODO: export interd vectors

        datadict = {
            k: v.tolist() if isinstance(v, np.ndarray) else v
            for k, v in datadict.items()
        }

        return datadict

    def shutdown(self):
        pass
