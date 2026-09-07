"""Minimal valid action parameters per EClib2 technique, for tests.

A plain module rather than a ``conftest.py`` fixture so it can be imported from
several test files without touching a shared file. Keys are spelled as the
EClib1 backend's ``parameter_map`` keys them, which is what makes these doubles
meaningful: if a key here has to change, the backend has stopped being a
drop-in.
"""

MINIMAL_PARAMS: dict[str, dict] = {
    "OCV": {
        "Tval__s": 2.0,
        "AcqInterval__s": 0.1,
        "AcqInterval__V": 10.0,
    },
    "CA": {
        "Vval__V": 0.5,
        "Tval__s": 1.0,
        "AcqInterval__s": 0.05,
        "AcqInterval__A": 1e-3,
    },
    "CP": {
        "Ival__A": 1e-4,
        "Tval__s": 1.0,
        "AcqInterval__s": 0.05,
        "AcqInterval__V": 0.01,
    },
    "CV": {
        "Vinit__V": 0.0,
        "Vapex1__V": 0.25,
        "Vapex2__V": -0.25,
        "Vfinal__V": 0.0,
        "ScanRate__V_s": 0.5,
        "Cycles": 1,
        "AcqInterval__V": 0.01,
    },
    "PEIS": {
        "Vinit__V": 0.3,
        "Vamp__V": 0.02,
        "Finit__Hz": 1e6,
        "Ffinal__Hz": 1.0,
        "FrequencyNumber": 30,
        "Duration__s": 0.5,
        "AcqInterval__s": 0.05,
        "SweepMode": "log",
        "Repeats": 1,
        "DelayFraction": 0.1,
    },
    "GEIS": {
        "Iinit__A": 1e-4,
        "Iamp__A": 2e-5,
        "Finit__Hz": 1e5,
        "Ffinal__Hz": 1.0,
        "FrequencyNumber": 20,
        "Duration__s": 0.5,
        "AcqInterval__s": 0.05,
        "SweepMode": "lin",
        "Repeats": 1,
        "DelayFraction": 0.1,
    },
    "CAOCV": {
        "CA_Vval__V_list": [0.4, 0.6],
        "CA_Tval__s_list": [1.0, 2.0],
        "CA_AcqInterval__s": 0.05,
        "CA_AcqInterval__A": 1e-3,
        "OCV_Tval__s": 3.0,
        "OCV_AcqInterval__s": 0.1,
        "OCV_AcqInterval__V": 10.0,
    },
}


def params(name: str, **overrides) -> dict:
    """Minimal valid params for ``name``, with ``overrides`` applied."""
    return {**MINIMAL_PARAMS[name], **overrides}
