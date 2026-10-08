"""Python 3.9 sim env: install_sim fakes let the vendor easyxafs scan loop run."""
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helao.deploy.hte.drivers.xafs.sidecar import sim_hw


def test_install_sim_imports_easyxafs(tmp_path):
    h = sim_hw.install_sim(str(tmp_path))
    import easyxafs.scan

    assert easyxafs.scan.mono is h.mono
    assert isinstance(easyxafs.scan.mono, sim_hw.FakeMono)


def test_normalscan_runs_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # vendor scan also writes ./cache/
    sim_hw.install_sim(str(tmp_path))
    import easyxafs.scan as scan

    s = scan.NormalScan(
        crystal2d="Si(5,5,3)", beta_offset=0, theta_offset=0, analyzer_radius=500,
        roi_bragg=80, roi_min=800, roi_max=1000,
        measurement_mode="XAFS_Fluorescence", saveaftercomplete=True,
        savename=str(tmp_path / "Zn_Scan0000_Sample1_X0.000_Y0.000"),
    )
    s.create_zone_constant_step(9600, 9620, 5, 0.01)
    s.start()
    s.wait_until_complete()

    zips = list(Path(tmp_path).glob("*_exd.csv.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
        assert "scan_def.json" in names and "metadata.json" in names
        csvs = [n for n in names if n.endswith(".csv")]
        npzs = [n for n in names if n.endswith("_mcas.npz")]
        assert len(csvs) == 1 and len(npzs) == 1
        assert "Time" in pd.read_csv(z.open(csvs[0])).columns
        with z.open(npzs[0]) as f:
            assert np.load(f)["mcas"].shape == (4, 4096)
        json.loads(z.read("scan_def.json"))


def test_fake_hooks(tmp_path):
    h = sim_hw.install_sim(str(tmp_path))
    h.mono.fail_on_call = 2
    h.mono.move_to_bragg_angle(80.0)
    with pytest.raises(RuntimeError, match="fake mono failure"):
        h.mono.move_to_bragg_angle(81.0)
    h.mono.move_to_bragg_angle(82.0)  # only call N fails
    assert h.mono.calls == [80.0, 82.0]
    assert list(h.ketek.get_statistics()) == list(sim_hw.STAT_KEYS)
    assert h.ketek.get_spectrum().shape == (4096,)
    assert h.proto.get_shutter_status() == "Open" and h.proto.readback_kv_ma()[0] == 50
    h.proto.close_shutter()
    assert h.proto.get_shutter_status() == "Closed"
