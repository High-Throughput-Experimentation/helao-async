"""The post-CA (presitu) un-aggregated arrays come from the presitu spectra."""

from types import SimpleNamespace

import numpy as np

from helao.deploy.hte.drivers.data.analyses.echeuvis_stability import (
    ANALYSIS_DEFAULTS,
    EcheUvisAnalysis,
)

WL = np.linspace(400.0, 800.0, 60)


def _hlo(epochs, value):
    data = {"epoch_s": list(epochs)}
    data.update({f"ch_{i:03d}": [value] * len(epochs) for i in range(len(WL))})
    return {"meta": {"optional": {"wl": WL.tolist()}}, "data": data}


def test_presitu_noagg_arrays_use_presitu_spectra():
    ana = object.__new__(EcheUvisAnalysis)
    ana.analysis_params = {
        **ANALYSIS_DEFAULTS,
        "lower_wl": 420,
        "upper_wl": 780,
        "window_length": 5,
        "poly_order": 2,
        "skip_first_n": 1,
    }
    ana.inputs = SimpleNamespace(
        baseline_spec=_hlo(np.arange(6.0), 0.5),
        insitu_spec=_hlo(np.arange(8.0), 0.4),  # differs from presitu
        presitu_spec=_hlo(100.0 + np.arange(5.0), 0.7),
    )
    assert ana.calc_output() is True
    out = ana.outputs
    assert out.noagg_presitu_epoch == [101.0, 102.0, 103.0, 104.0]
    assert np.allclose(np.array(out.noagg_omt_presitu), 1 - 0.7)
    assert np.allclose(np.array(out.noagg_omt_insitu), 1 - 0.4)
