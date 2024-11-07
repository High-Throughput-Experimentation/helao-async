__all__ = ["Electrolyte"]
from enum import Enum


class Electrolyte(str, Enum):
    slf10 = "SLF10"
    oer10 = "OER10"
    pslf10 = "PSLF10"
    oer9 = "OER9"
    slf7 = "SLF7"
    slf9 = "SLF9"
    oer3 = "OER3"
    met1 = "MET1"
    met3 = "MET3"
    h2so4 = "1MH2SO4"
    naoh = "1MNaOH"
    oer13 = "OER13"
    fcn7 = "FCN7"
    her1 = "HER1"
    other = "other-see-comment"
    