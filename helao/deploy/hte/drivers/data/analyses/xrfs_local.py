"""Local-zip XRF spectroscopy quantification analysis.

Reads XRF count files from a sequence zip, looks up the matching
calibration library (by voltage, current and spot size), fits a
per-transition OLS model relating element density to counts, and emits
atomic-fraction figures of merit per sample via :class:`XrfsAnalysis`.
"""

import os
import re
import sys
from glob import glob
from uuid import UUID
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd
import statsmodels.api as sm

from helao.core.version import get_filehash
from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput

from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
from helao.core.drivers.data.loaders.localfs import (
    HelaoProcess,
    HelaoAction,
    LocalLoader,
)

CM_SCALE = {"nm": 1e-7, "um": 1e-4, "mm": 0.1, "cm": 1}


class XrfsInputs(AnalysisInput):
    """Process/action pair backing a single XRF analysis.

    Attributes:
        xrfs: Process row carrying the XRF metadata.
        xrfs_act: Action row whose HLO holds the count spectra.
        global_sample_label: Solid-sample global label discovered in
            the process file list.
        process_params: ``process_params`` dict from the process row
            (used to look up spot size, voltage and current).
    """

    xrfs: HelaoProcess
    xrfs_act: HelaoAction
    global_sample_label: str
    process_params: dict

    def __init__(self, process_uuid: UUID, local_loader: LocalLoader):
        """Locate the XRF process and the action that produced its counts.

        Args:
            process_uuid: Target process UUID inside the zip.
            local_loader: Zip-backed :class:`LocalLoader`.
        """
        self.xrfs = local_loader.get_prc(
            local_loader.processes.query("process_uuid==@process_uuid").index[0]
        )
        self.process_params = self.xrfs.process_params
        filed = [
            d
            for d in self.xrfs.json["files"]
            if d["file_type"]
            in [
                "xrfcount_helao__file",
                "xrfcount_json__file",
                "xrfcount_helao__json_file",
            ]
        ][0]
        self.global_sample_label = [x for x in filed["sample"] if "__solid__" in x][0]
        action_uuid = filed["action_uuid"]
        action_dir = [
            d
            for d in self.xrfs.json["dispatched_actions_abbr"]
            if d["action_uuid"] == action_uuid
        ][0]["action_output_dir"]
        action_reldir = "/".join(action_dir.split("/")[-2:])
        self.xrfs_act = local_loader.get_act(
            local_loader.actions.query(
                "action_localpath.str.contains(@action_reldir)"
            ).index[0]
        )

    @property
    def counts(self):
        """Loaded HLO payload for the XRF action."""
        return self.xrfs_act.hlo

    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        """Return a one-element list describing the XRF count file."""
        filename, filetype, datakeys = self.xrfs_act.hlo_file_tup_type(
            "xrfcount_helao__file"
        )
        adm = AnalysisDataModel(
            action_uuid=self.xrfs_act.action_uuid,
            run_use=self.xrfs_act.json["run_use"],
            raw_data_path=f"raw_data/{self.xrfs_act.action_uuid}/{filename}",
            global_sample_label=self.global_sample_label,
            file_name=filename,
            file_type=filetype,
            data_keys=datakeys,
        )
        return [adm]


class XrfsOutputs(AnalysisOutput):
    """XRF quantification payload emitted by :class:`XrfsAnalysis`.

    Attributes:
        element: Element symbols per row.
        transition: Transition labels (``"<el>.<line>"``) per row.
        counts: Raw counts per row.
        nanomoles: Nanomoles per row (over the spot area).
        nanomoles_2sig: 2-sigma uncertainty on ``nanomoles``.
        nanomoles_per_cm2: Areal density per row.
        atomic_fraction: Per-row atomic fraction renormalised over
            ``norm_elements`` (NaN for transitions outside that set).
        global_sample_label: Solid sample under analysis.
    """

    element: list
    transition: list
    counts: list
    nanomoles: list
    nanomoles_2sig: list
    nanomoles_per_cm2: list
    atomic_fraction: list
    global_sample_label: str


class XrfsAnalysis(BaseAnalysis):
    """XRF quantification with per-acquisition calibration libraries.

    Attributes:
        inputs: Resolved :class:`XrfsInputs`.
        outputs: Populated :class:`XrfsOutputs` after
            :meth:`calc_output`.
        global_sample_label: Solid sample under analysis.
    """

    inputs: XrfsInputs
    outputs: XrfsOutputs
    global_sample_label: str

    def __init__(
        self,
        process_uuid: UUID,
        local_loader: LocalLoader,
        analysis_params: dict,
    ):
        """Build inputs and generate the analysis UUID.

        Args:
            process_uuid: Target XRF process UUID.
            local_loader: Zip-backed :class:`LocalLoader`.
            analysis_params: Optional overrides; supports
                ``norm_elements``, ``calibration_file_path`` and
                ``force_latest_calibration``.
        """
        self.analysis_name = "XRFS_quantification_analysis"
        self.analysis_timestamp = datetime.now()
        self.analysis_params = analysis_params
        # from analysis params, need (1) list of elements to normalize, (2) calibration file path
        self.inputs = XrfsInputs(process_uuid, local_loader)
        self.process_uuid = self.inputs.xrfs.process_uuid

        # additional attrs
        self.process_timestamp = self.inputs.xrfs.process_timestamp
        self.process_name = self.inputs.xrfs.technique_name
        self.run_type = self.inputs.xrfs.meta_dict.get("run_type", "xrfs")
        self.run_use = self.inputs.xrfs.meta_dict["run_use"]
        self.technique_name = self.inputs.xrfs.technique_name
        self.sequence_uuid = self.inputs.xrfs.meta_dict.get("sequence_uuid", None)

        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
        self.analysis_codepath = sys._getframe().f_code.co_filename
        self.analysis_classname = self.__class__.__name__
        self.global_sample_label = self.inputs.global_sample_label
        self.analysis_uuid = self.gen_uuid(self.inputs.global_sample_label)

    def calc_output(self) -> bool:
        """Quantify each transition against the chosen calibration library.

        Locates a calibration CSV matching the run's
        ``voltage_kv``/``current_ma``/``spot_size`` (preferring the
        latest one older than the data, unless
        ``force_latest_calibration`` is set), fits an OLS model per
        transition to predict ug/cm^2 from counts, converts to
        nanomoles using the spot area, and computes atomic fractions
        over the requested ``norm_elements``.

        Returns:
            ``True`` once :attr:`outputs` has been populated.
        """

        _, hlo_data = self.inputs.counts
        hlo_els = hlo_data["element"]
        hlo_counts = hlo_data["cps"]

        area_str = self.inputs.process_params["spot_size"]
        kv = self.inputs.process_params["voltage_kv"]
        current = self.inputs.process_params["current_ma"]

        diam_str, unit = re.findall(r"([0-9]+)[\s]*([a-z]+)", area_str)[0]
        diam = float(diam_str)
        unit = unit.strip()

        area = (CM_SCALE[unit] * (diam / 2)) ** 2 * 3.14159

        calib_prefix = f"multi-{kv:.0f}-{current:.0f}-{diam_str.strip()}-vacu-"
        force_latest_calibration = self.analysis_params.get("force_latest_calibration", False)
        calib_path = self.analysis_params.get("calibration_file_path", "")

        norm_els = self.analysis_params.get("norm_elements", [])
        seq_dir = os.path.basename(
            os.path.dirname(
                os.path.dirname(self.inputs.xrfs_act.meta_dict["action_output_dir"])
            )
        )
        yw_dir = os.path.basename(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(
                            self.inputs.xrfs_act.meta_dict["action_output_dir"]
                        )
                    )
                )
            )
        )
        md_dir = os.path.basename(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(self.inputs.xrfs_act.meta_dict["action_output_dir"])
                )
            )
        )
        ymd_dir = yw_dir.split(".")[0] + md_dir
        seq_label = seq_dir.split("__")[-1]
        if not norm_els:
            norm_els = [
                x
                for x in re.findall("([A-Z][a-z]*)", seq_label)
                if x not in ("O", "Ar", "N", "H")
            ]

        if not calib_path:
            calglob = (
                rf"K:\experiments\xrfs\user\calibration_libraries\{calib_prefix}*.csv"
                if sys.platform == "win32"
                else f"/mnt/k/experiments/xrfs/user/calibration_libraries/{calib_prefix}*.csv"
            )
            calib_libs = glob(calglob)
            if not force_latest_calibration:
                filtered_libs = [
                    x
                    for x in calib_libs
                    if int(x.split("__")[-1].split("-")[0][2:]) < int(ymd_dir)
                ]
            else:
                filtered_libs = calib_libs
            latest_lib = sorted(
                filtered_libs, key=lambda x: int(x.split("__")[-1].split("-")[0][2:])
            )[-1]
            calib_path = latest_lib

        self.analysis_params["calibration_file_path"] = calib_path
        self.analysis_params["norm_elements"] = norm_els
        self.analysis_params["calibration_list"] = []

        # calibd = pd.read_csv(calib_path).set_index("transition").to_dict("index")
        caldf = pd.read_csv(calib_path)

        elements = []
        transitions = []
        counts = []
        nanomoles = []
        nanomoles_2sig = []
        nanomoles_per_cm2 = []

        for trans, count in zip(hlo_els, hlo_counts):
            elements.append(trans.split(".")[0])
            transitions.append(trans)
            counts.append(count)

            edf = caldf.query("transition_str==@trans")[
                [
                    "serial_no",
                    "symbol",
                    "transition_str",
                    "mean",
                    "sd",
                    "median",
                    "n",
                    "element_dens",
                    "atomic_mass",
                ]
            ]
            if edf.shape[0] > 0:
                Y = edf.element_dens.to_numpy()
                X = edf["mean"].to_numpy()
                sm.add_constant(X)
                model = sm.OLS(Y, X, hasconst=True).fit()
                pred = (
                    model.get_prediction(count)
                    .summary_frame(alpha=0.05)
                    .rename(
                        {
                            "mean": "ug_per_cm2",
                            "mean_se": "std_err",
                            "mean_ci_lower": "ci_95pct_lower",
                            "mean_ci_upper": "ci_95pct_upper",
                        },
                        axis=1,
                    )
                    .to_dict(orient="records")[0]
                )
                atomic_mass = edf.iloc[0].atomic_mass
                mole_density = pred["ug_per_cm2"] * 1e-6 / atomic_mass
                nanomole_density = mole_density * 1e9

                nanomoles_per_cm2.append(nanomole_density)
                nanomoles.append(nanomole_density * area)
                nanomoles_2sig.append(pred["std_err"] * 1e-6 / atomic_mass * 1e9 * area)

                calib_list = (
                    edf.rename(
                        {
                            "serial_no": "calib_std_serial_no",
                            "symbol": "element",
                            "mean": "counts_mean",
                            "sd": "counts_stdev",
                            "n": "num_acq",
                            "element_dens": "ug_per_cm2",
                        },
                        axis=1,
                    )
                    .drop("atomic_mass", axis=1)
                    .to_dict(orient="records")
                )
                self.analysis_params["calibration_list"] += calib_list
            else:
                nanomoles.append(np.nan)
                nanomoles_2sig.append(np.nan)
                nanomoles_per_cm2.append(np.nan)

        # atomic_fraction
        norm_nmoles = []
        norm_trans = []

        for el in norm_els:
            if len([x for x in elements if x == el]) > 1:
                el_trans = sorted(
                    [
                        x
                        for x in transitions
                        if x.startswith(f"{el}.") and x in caldf.transition_str.values
                    ]
                )
            else:
                el_trans = [
                    x
                    for x in transitions
                    if x.startswith(f"{el}.") and x in caldf.transition_str.values
                ]
            norm_nmoles.append(nanomoles[transitions.index(el_trans[-1])])
            norm_trans.append(el_trans[-1])

        sum_nanomoles = sum(norm_nmoles)
        atomic_fraction = [
            np.nan if trans not in norm_trans else nmoles / sum_nanomoles
            for trans, nmoles in zip(transitions, nanomoles)
        ]

        # create output model
        self.outputs = XrfsOutputs(
            element=elements,
            transition=transitions,
            counts=counts,
            nanomoles=nanomoles,
            nanomoles_2sig=nanomoles_2sig,
            nanomoles_per_cm2=nanomoles_per_cm2,
            atomic_fraction=atomic_fraction,
            global_sample_label=self.global_sample_label,
            output_type="composition.xrfs_quantification",
        )
        return True
