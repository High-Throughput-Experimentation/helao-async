"""downsample_to_1mV_precision must not collapse frames that are already ~1 mV apart."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helao.deploy.hte.processors.libs.hispec_calibrate_downsample_parquet import (
    downsample_to_1mV_precision,
    read_spec_times_from_hlo,
)


def _frame(ewe, t):
    return pd.DataFrame(
        {
            "t_s": t,
            "Ewe_V": ewe,
            "cycle": np.zeros(len(t), dtype=int),
            "direction": ["anodic"] * (len(t) // 2)
            + ["cathodic"] * (len(t) - len(t) // 2),
            "400.0": np.arange(len(t), dtype=float),
        }
    )


def test_frames_already_at_1mV_are_not_binned():
    """98 fps at 100 mV/s is 1.02 mV/frame -- the HiSpec SpEC case.

    Binning by 1 mV then averaging t_s merges both sides of the apex into
    one turning-point time; skipping leaves every frame's t_s intact.
    """
    fps = 98.0
    scan_rate = 0.1
    n = 40
    t = np.arange(n) / fps
    du = scan_rate / fps
    half = n // 2
    ewe = np.empty(n)
    ewe[:half] = np.arange(half) * du
    ewe[half:] = ewe[half - 1] - np.arange(1, n - half + 1) * du
    out = downsample_to_1mV_precision(_frame(ewe, t), precision=0.001)
    assert len(out) == n
    assert list(out["t (s)"]) == pytest.approx(list(t))


def test_coarse_frames_are_still_binned():
    """10 mV steps into 1 mV bins: the original grouping still runs."""
    ewe = np.array([-0.02, -0.01, 0.0, 0.01, 0.02])
    t = np.arange(5, dtype=float)
    out = downsample_to_1mV_precision(_frame(ewe, t), precision=0.001)
    assert len(out) == 5
    assert "t (s)" in out.columns


def test_spec_times_accept_elapsed_time_s(tmp_path):
    """New Andor HLOs write elapsed_time_s; older ones wrote tick_time."""
    hlo = Path(tmp_path) / "andor.hlo"
    hlo.write_text(
        "action_name: ANDORSPEC\n"
        "epoch_ns: 1700000000000000000\n"
        "%%\n"
        '{"elapsed_time_s": [10.0, 10.01, 10.02], "ch_0000": [1, 2, 3]}\n',
        encoding="utf-8",
    )
    times = read_spec_times_from_hlo(str(hlo))
    assert list(times["t_s"]) == pytest.approx([0.0, 0.01, 0.02])


def test_spec_times_still_read_tick_time(tmp_path):
    hlo = Path(tmp_path) / "andor.hlo"
    hlo.write_text(
        "action_name: ANDORSPEC\n"
        "epoch_ns: 1700000000000000000\n"
        "%%\n"
        '{"tick_time": [100.0, 100.01], "ch_0000": [1, 2]}\n',
        encoding="utf-8",
    )
    times = read_spec_times_from_hlo(str(hlo))
    assert list(times["t_s"]) == pytest.approx([0.0, 0.01])
