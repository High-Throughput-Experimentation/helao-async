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
        if len(specd.keys()) == 2:  # TR_UVVIS technique
            wlT = np.array(specd["T"]["wlarr"])
            flT = np.where((wlT > params["lower_wl"]) & (wlT < params["upper_wl"]))[0]
            arrT = np.array(specd["T"]["bsnlist"])[:, flT]
            smpT = np.array(specd["T"]["smplist"])
            bindT = [
                list(range(x, x + params["bin_width"]))
                for x in range(0, wlT.shape[0], params["bin_width"])
            ]
            bwlT = [np.median(wlT[inds]) for inds in bindT]
            barrT = [arrT[:, inds].mean(axis=1) for inds in bindT]

            asT = np.argsort(smpT)
            wlR = np.array(specd["R"]["wlarr"])
            flR = np.where((wlR > params["lower_wl"]) & (wlR < params["upper_wl"]))[0]
            arrR = np.array(specd["R"]["bsnlist"])[asT, flR]
            smpR = np.array(specd["R"]["smplist"])[asT]
            bindR = [
                list(range(x, x + params["bin_width"]))
                for x in range(0, wlR.shape[0], params["bin_width"])
            ]
            bwlR = [np.median(wlR[inds]) for inds in bindR]
            barrR = [arrR[:, inds].mean(axis=1) for inds in bindR]

            rsi = [np.median(inds) for inds in bindT]
            hv = [1239.8 / x for x in bwlT]

            arrTR = arrT / (1 - arrR)
            omTR = 1 - arrT - arrR
            absTR = -np.log(arrTR)

            barrTR = [arrTR[:, inds].mean(axis=1) for inds in bindT]
            bomTR = [omTR[:, inds].mean(axis=1) for inds in bindT]
            babsTR = [absTR[:, inds].mean(axis=1) for inds in bindT]



        elif len(specd.keys()) == 1 and "T" in specd.keys():  # T_UVVIS only
            wlT = np.array(specd["T"]["wlarr"])
            flT = np.where((wlT > params["lower_wl"]) & (wlT < params["upper_wl"]))[0]
            arrT = np.array(specd["T"]["bsnlist"])[:, flT]
            smpT = np.array(specd["T"]["smplist"])
            bindT = [
                list(range(x, x + params["bin_width"]))
                for x in range(0, wlT.shape[0], params["bin_width"])
            ]
            bwlT = [np.median(wlT[inds]) for inds in bindT]
            barrT = [arrT[:, inds].mean(axis=1) for inds in bindT]

            rsi = [np.median(inds) for inds in bindT]
            hv = [1239.8 / x for x in bwlT]

        elif len(specd.keys()) == 1 and "R" in specd.keys():  # DR_UVVIS only
            wlR = np.array(specd["R"]["wlarr"])
            flR = np.where((wlR > params["lower_wl"]) & (wlR < params["upper_wl"]))[0]
            arrR = np.array(specd["R"]["bsnlist"])[:, flR]
            smpR = np.array(specd["R"]["smplist"])
            bindR = [
                list(range(x, x + params["bin_width"]))
                for x in range(0, wlR.shape[0], params["bin_width"])
            ]
            bwlR = [np.median(wlR[inds]) for inds in bindR]
            barrR = [arrR[:, inds].mean(axis=1) for inds in bindR]

            rsi = [np.median(inds) for inds in bindR]
            hv = [1239.8 / x for x in bwlR]

        return datadict
