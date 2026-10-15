"""calc_uvis_abs integrates with np.trapezoid (np.trapz is gone in numpy 2.x)."""

import numpy as np

from helao.deploy.hte.drivers.data.calc_driver import Calc

NWL = 100
WL = np.linspace(400.0, 900.0, NWL)
BIN = 5
EV_PARTS = [2.2, 2.6, 3.0]


def _entry(run_use, value, label):
    data = {"epoch_s": np.zeros(2)}
    data.update({f"ch_{i}": np.full(2, value) for i in range(NWL)})
    return {
        "meta": {"optional": {"wl": WL.tolist()}},
        "data": data,
        "actd": {
            "run_use": run_use,
            "action_server": {"server_name": "UVIS_T_server"},
            "technique_name": "T_UVVIS",
            "action_uuid": f"uuid-{run_use}",
            "samples_in": [{"sample_type": "solid", "global_label": label}],
        },
        "expd": {},
    }


def test_calc_uvis_abs_trapezoid(monkeypatch):
    calc = Calc(config={})
    hlo = {
        "a_dark.hlo": _entry("ref_dark", 0.0, "s1"),
        "a_light.hlo": _entry("ref_light", 1.0, "s1"),
        "a_data.hlo": _entry("data", 0.5, "s1"),
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

    # constant T=0.5 -> abs = ln 2 everywhere; independent oracle for the integral
    full = WL[1:-1]  # lower_wl/upper_wl bounds are exclusive
    n = len(full)
    rsi = [int(np.median(range(i, min(i + BIN, n)))) for i in range(0, n, BIN)]
    hv = 1239.8 / full[rsi]
    lo, hi = EV_PARTS[0], EV_PARTS[1]
    sel = hv[(hv > lo) & (hv < hi)]
    expected = -1 * np.log(2) * (sel[-1] - sel[0])
    got = np.asarray(datadict[f"abs_{lo}_{hi}"])
    assert np.allclose(got, expected, rtol=1e-6)


def test_calc_uvis_abs_emits_data_epochs(monkeypatch):
    calc = Calc(config={})
    data = _entry("data", 0.5, "s1")
    data["data"]["epoch_s"] = np.array([10.0, 11.0])
    hlo = {
        "a_dark.hlo": _entry("ref_dark", 0.0, "s1"),
        "a_light.hlo": _entry("ref_light", 1.0, "s1"),
        "a_data.hlo": data,
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
    _, arraydict = calc.calc_uvis_abs("unused", params)
    eps = [ad["epoch"] for ad in arraydict.values() if "epoch" in ad]
    assert eps and all(e == [[10.0, 11.0]] for e in eps)
