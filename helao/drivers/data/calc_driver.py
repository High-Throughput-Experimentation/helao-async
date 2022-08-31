import os
import numpy as np
from scipy.signal import savgol_filter
from ruamel.yaml import YAML
from pathlib import Path
from glob import glob

from helaocore.models.data import DataModel
from helao.servers.base import Base
from helao.helpers.read_hlo import read_hlo


class Calc:
    """_summary_"""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.yaml = YAML(typ="safe")

    def gather_sequence_data(self, seq_reldir: str):
        # get all files from current sequence directory
        # produce tuples, (run_type, technique_name, run_use, hlo_path)
        active_save_dir = self.base.save_root.__str__()
        diag = os.path.join(active_save_dir.replace("ACTIVE", "DIAG"), seq_reldir)
        finished = os.path.join(
            active_save_dir.replace("ACTIVE", "FINISHED"), seq_reldir
        )
        synced = os.path.join(active_save_dir.replace("ACTIVE", "SYNCED"), seq_reldir)
        hlo_dict = {}
        for prefix in (diag, finished, synced):
            for p in glob(
                os.path.join(prefix, "*__UVIS_sub_measure", "*__acquire_spec", "*.hlo")
            ):
                try:
                    meta, data = read_hlo(p)
                except FileNotFoundError:
                    p.replace("FINISHED", "SYNCED")
                    meta, data = read_hlo(p)

                actp = os.path.join(glob(os.path.dirname(p))[0], "*.yml")
                try:
                    actd = self.yaml.load(Path(actp))
                except FileNotFoundError:
                    actp.replace("FINISHED", "SYNCED")
                    actd = self.yaml.load(Path(actp))

                expp = os.path.join(
                    glob(os.path.dirname(os.path.dirname(p)))[0], "*.yml"
                )
                try:
                    expd = self.yaml.load(Path(expp))
                except FileNotFoundError:
                    expp.replace("FINISHED", "SYNCED")
                    expd = self.yaml.load(Path(expp))

                hlo_dict[p] = {
                    "meta": meta,
                    "data": data,
                    "actd": actd,
                    "expd": expd,
                }

        return hlo_dict

    def calc_uvis_abs(self, activeobj):
        seq_reldir = activeobj.action.get_sequence_dir()
        hlo_dict = self.gather_sequence_data(seq_reldir)

        spec_types = ["T", "R"]
        specd = {}
        for spec in spec_types:
            rud = {
                ru: {
                    p: d
                    for p, d in hlo_dict.items()
                    if d["actd"]["run_use"] == ru and d["expd"]["spec_type"] == spec
                }
                for ru in ("ref_dark", "ref_light", "data")
            }

            for hlod in rud.values():
                for d in hlod.values():
                    rud["technique_name"] = d["expd"]["technique_name"]
                    data = d["data"]
                    vals = [
                        data[dk]
                        for dk in sorted(
                            [k for k in data.keys() if k.startswith("ch_")],
                            key=lambda x: int(x.split("_")[-1]),
                        )
                    ]
                    arr = np.array(vals).transpose()
                    d.update(
                        {
                            "raw": arr,
                            "median": np.median(arr, axis=0),
                            "mean": arr.mean(axis=0),
                        }
                    )

            refdark = np.concatenate(
                [d["mean"] for d in rud["ref_dark"].values()], axis=0
            )
            reflight = np.concatenate(
                [d["mean"] for d in rud["ref_light"].values()], axis=0
            )
            mindark = refdark.min(axis=0)
            maxlight = reflight.max(axis=0)

            actuuids = []
            smplist = []
            wllist = []
            bsnlist = []

            for d in rud["data"].values():
                wllist.append(d["meta"]["wl"])
                actd = d["actd"]
                actuuids.append(actd["action_uuid"])
                smplist.append(
                    [
                        s["global_label"]
                        for s in actd["samples_in"]
                        if s["sample_type"] == "solid"
                    ][0]
                )
                bsnlist.append((d["mean"] - mindark) / maxlight)

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
                [y for y in range(x, x + params["bin_width"]) if y < wl.shape[0]]
                for x in range(0, wl.shape[0], params["bin_width"])
            ]
            pred[k]["binds"] = binds
            rsi = [np.median(inds) for inds in pred[k]["binds"]]
            pred[k]["rsi"] = rsi
            pred[k]["bin"]["wl"] = np.array([np.median(wl[inds]) for inds in binds])
            hv = [1239.8 / x for x in pred[k]["bin"]["wl"]]
            pred[k]["hv"] = hv
            dx = hv[1] - hv[0]
            dx += [(hv[idx + 1] - hv[idx - 1]) / 2.0 for idx in range(1, len(rsi - 1))]
            dx += hv[-1] - hv[-2]
            pred[k]["dx"] = dx

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
                    pred[sk]["smooth"][k] = savgol_filter(
                        v,
                        window_length=params["window_length"],
                        polyorder=params["poly_order"],
                        delta=params["delta"],
                        deriv=0,
                    )

            # smooth sig
            v = pred[sk]["smooth"]["sig"]
            pred[sk]["smooth_refadj"]["sig"] = v
            pred[sk]["min_rescaled"] = False
            pred[sk]["max_rescaled"] = False
            if min(v) >= params["min_mthd_allowed"] and min(v) < params["min_limit"]:
                pred[sk]["min_rescaled"] = True
                pred[sk]["smooth_refadj"]["sig"] = v - min(v) + params["min_limit"]
            v = pred[sk]["smooth_refadj"]["sig"]
            if max(v) <= params["max_mthd_allowed"] and max(v) >= params["max_limit"]:
                pred[sk]["max_rescaled"] = True
                pred[sk]["smooth_refadj"]["sig"] = v / (max(v) + 0.02)

            # smooth abs
            if len(specd.keys()) == 1 and "R" in specd.keys():
                pred[sk]["smooth_refadj"]["abs"] = -np.log(
                    pred[sk]["smooth_refadj"]["sig"]
                )
            else:
                pred[sk]["smooth_refadj"]["abs"] = (
                    1.0 - np.log(pred[sk]["smooth_refadj"]["sig"])
                ) ** 2 / (2.0 * pred[sk]["smooth_refadj"]["sig"])
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
            v = pred[sk]["smooth_refadj_scl"]["abs"]
            v[np.isnan(v)] = 0.1
            pred[sk]["smooth_refadj_scl"]["abs_1stderiv"] = (
                savgol_filter(
                    v,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=params["delta"],
                    deriv=1,
                )
                / pred[sk]["dx"]
            )
            pred[sk]["smooth_refadj_scl"]["abs_2ndderiv"] = (
                savgol_filter(
                    v,
                    window_length=params["window_length"],
                    polyorder=params["poly_order"],
                    delta=params["delta"],
                    deriv=2,
                )
                / pred[sk]["dx"] ** 2
            )

        datadict = {}
        # assemble datadict with scalar FOMs and intermediate outputs
        if len(specd.keys()) == 2:  # TR_UVVIS technique
            interd = pred["TR"]
            
            evp = params["ev_parts"]
            for i in range(len(evp) - 1):
                lo, hi = evp[i], evp[i + 1]
                evrange = (interd["hv"] > lo) and (interd["hv"] < hi)
                datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][:,evrange].mean(axis=1)
            # full range
            lo, hi = evp[0], evp[-1]
            evrange = (interd["hv"] > lo) and (interd["hv"] < hi)
            datadict[f"1-T-R_av_{lo}_{hi}"] = interd["smooth"]["omTR"][:,evrange].mean(axis=1)
            datadict["TplusR_0to1"] = np.all((interd["smooth"]["omTR"] > 0.0) and (interd["smooth"]["omTR"] < 1.0))

            datadict["T_0to1"] = np.all((pred["T"]["smooth"]["sig"] > 0.0) and (pred["T"]["smooth"]["sig"] < 1.0))
            datadict["R_0to1"] = np.all((pred["R"]["smooth"]["sig"] > 0.0) and (pred["R"]["smooth"]["sig"] < 1.0))

        elif len(specd.keys()) == 1 and "T" in specd.keys():  # T_UVVIS only
            interd = pred["T"]
            datadict["T_0to1"] = np.all((pred["T"]["smooth"]["sig"] > 0.0) and (pred["T"]["smooth"]["sig"] < 1.0))

        elif len(specd.keys()) == 1 and "R" in specd.keys():  # DR_UVVIS only
            interd = pred["R"]
            datadict["DR_0to1"] = np.all((pred["R"]["smooth"]["sig"] > 0.0) and (pred["R"]["smooth"]["sig"] < 1.0))

        datadict["max_abs"] = np.nanmax(interd["smooth_refadj"]["abs"], axis=1)
        checknanrange = (interd["bin"]["wl"] >= 410) and (interd["bin"]["wl"] <= 850)
        datadict["abs_hasnan"] = np.any(
            np.isnan(interd["smooth_refadj"]["abs"][:, checknanrange]), axis=1
        )
        evp = params["ev_parts"]
        for i in range(len(evp) - 1):
            lo, hi = evp[i], evp[i + 1]
            evrange = (interd["hv"] > lo) and (interd["hv"] < hi)
            datadict[f"abs_{lo}_{hi}"] = np.trapz(
                interd["smooth_refadj"]["abs"][:, evrange], x=interd["hv"][evrange]
            )
        # full range
        lo, hi = evp[0], evp[-1]
        evrange = (interd["hv"] > lo) and (interd["hv"] < hi)
        datadict[f"abs_{lo}_{hi}"] = np.trapz(
            interd["smooth_refadj"]["abs"][:, evrange], x=interd["hv"][evrange]
        )

        datadict["max_abs2ndderiv"] = np.nanmax(interd["smooth_refadj_scl"]["abs_2ndderiv"], axis=1)
        datadict["min_abs1stderiv"] = np.nanmin(interd["smooth_refadj_scl"]["abs_1stderiv"], axis=1)

        for z in ("DA", "IA", "DF", "IF"):
            v = interd["smooth_refadj"][z]
            v[np.isnan(v)] = 0.1
            slope = savgol_filter(
                v, 
                window_length=params["window_length"],
                polyorder=params["poly_order"],
                delta=1.0,
                deriv=1
            ) / interd["dx"]
            datadict[f"{z}_minslope"] = np.nanmin(slope, axis=1)

        datadict["sample_label"] = smplist
        
        #TODO: export interd vectors

        return datadict
