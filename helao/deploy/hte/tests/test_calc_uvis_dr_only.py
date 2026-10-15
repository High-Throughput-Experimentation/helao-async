"""calc_uvis_abs on an R-only (DR_UVVIS) sequence takes wavelengths from "R", not "T"."""

from helao.deploy.hte.drivers.data.calc_driver import Calc
from helao.deploy.hte.tests.test_calc_uvis_trapezoid import EV_PARTS, BIN, _entry


def _as_r(entry):
    entry["actd"]["action_server"]["server_name"] = "UVIS_R_server"
    entry["actd"]["technique_name"] = "DR_UVVIS"
    return entry


def test_calc_uvis_abs_dr_only(monkeypatch):
    calc = Calc(config={})
    hlo = {
        "a_dark.hlo": _as_r(_entry("ref_dark", 0.0, "s1")),
        "a_light.hlo": _as_r(_entry("ref_light", 1.0, "s1")),
        "a_data.hlo": _as_r(_entry("data", 0.5, "s1")),
    }
    monkeypatch.setattr(calc, "gather_seq_data", lambda *a, **k: hlo)
    params = dict(
        skip_nspec=0,
        lower_wl=400.0,
        upper_wl=900.0,
        bin_width=BIN,
        window_length=5,
        poly_order=2,
        delta=1.0,
        min_mthd_allowed=-1.0,
        max_mthd_allowed=2.0,
        min_limit=0.0,
        max_limit=0.9,
        ev_parts=EV_PARTS,
    )
    datadict, _ = calc.calc_uvis_abs("unused", params)
    assert "DR_0to1" in datadict
