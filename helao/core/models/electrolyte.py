"""Enum of named electrolyte formulations used by HTE experiments."""

__all__ = ["Electrolyte"]
from enum import Enum


class Electrolyte(str, Enum):
    """Catalog of supported electrolyte identifiers.

    Member values are the canonical short names used in configs and file
    headers; the `other` member is the escape hatch for one-off mixtures.
    """

    slf10 = "SLF10"
    oer10 = "OER10"
    pslf10 = "PSLF10"
    hispeca = "HISPEC-A"  # HISPEC acid screening - 0.1 M HClO4 in 0.9 M NaClO4
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
