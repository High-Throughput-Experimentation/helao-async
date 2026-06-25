"""Enum tagging how an action's produced data is intended to be used."""

__all__ = ["RunUse", "YmlType"]
from enum import Enum


class YmlType(str, Enum):
    """Top-level kinds of HELAO YAML records (ports legacy
    ``helao.core.drivers.data.enum.YmlType``). Used by the data-packing driver to
    branch on whether a `.yml` record is an action / experiment / sequence."""

    action = "action"
    experiment = "experiment"
    sequence = "sequence"


class RunUse(str, Enum):
    """Intended use of the data produced by a run.

    Members:
        data: Standard experiment data.
        ref: Generic reference measurement.
        ref_light: Light reference (spectroscopy).
        ref_dark: Dark reference (spectroscopy).
        ref_bkg: Background reference.
        baseline: Baseline measurement.
        standard: Calibration standard.
        blank: Blank measurement.
        preca_baseline: Pre-calibration baseline.
        pre_anneal: Measurement taken before annealing.
        post_anneal: Measurement taken after annealing.
        shutter_closed: Measurement with the shutter closed.
        izero: I-zero (incident intensity) reference.
        energy_calib: Energy calibration scan.
    """

    data = "data"
    ref = "ref"
    ref_light = "ref_light"
    ref_dark = "ref_dark"
    ref_bkg = "ref_bkg"
    baseline = "baseline"
    standard = "standard"
    blank = "blank"
    preca_baseline = "preca_baseline"
    pre_anneal = "pre_anneal"
    post_anneal = "post_anneal"
    shutter_closed = "shutter_closed"
    izero = "izero"
    energy_calib = "energy_calib"
