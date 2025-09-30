__all__ = ["RunUse"]
from enum import Enum


class RunUse(str, Enum):
    data = "data"
    ref = "ref"
    ref_light = "ref_light"
    ref_dark = "ref_dark"
    ref_bkg = "ref_bkg"
    baseline = "baseline"
    standard = "standard"
    blank = "blank"
    preca_baseline = "preca_baseline"
