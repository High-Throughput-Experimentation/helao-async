"""The HISPEC pipeline must feed the CV-window-filtered frame onward."""

import pandas as pd

from helao.deploy.hte.processors.libs import hispec_calibrate_downsample_parquet as hp


def test_spectra_after_the_cv_end_do_not_reach_downsampling(monkeypatch):
    spectra = pd.DataFrame({"t_s": [1.0, 2.0, 9.0], "t (s)": [1.0, 2.0, 9.0]})
    cv = pd.DataFrame({"t_s": [0.0, 5.0]})
    seen = {}

    def _downsample(calibrated_spectra, precision):
        seen["t"] = list(calibrated_spectra["t_s"])
        return calibrated_spectra

    ident = lambda **kw: kw.get("calibration_df", kw.get("spec_times"))  # noqa: E731
    monkeypatch.setattr(hp, "read_spec_times_from_parquet", lambda **kw: spectra)
    monkeypatch.setattr(hp, "generate_interpolation_function", lambda *a, **k: None)
    monkeypatch.setattr(hp, "interpolate_spec_time_to_U", ident)
    monkeypatch.setattr(hp, "get_cycles_for_spec_times", ident)
    monkeypatch.setattr(hp, "calcualte_scan_direction_for_spec_times", ident)
    monkeypatch.setattr(hp, "error_correct_scan_direction_for_all_cycles", ident)
    monkeypatch.setattr(hp, "read_in_spectra_calibrate", lambda **kw: spectra)
    monkeypatch.setattr(hp, "downsample_to_1mV_precision", _downsample)
    monkeypatch.setattr(
        hp, "interpolate_spectral_time_to_current", lambda **kw: kw["spectral_df_calib"]
    )
    hp.fully_read_and_calibrate_parquet(cv, "unused.parquet")
    assert seen["t"] == [1.0, 2.0]
