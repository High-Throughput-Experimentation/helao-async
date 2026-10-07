"""Python 3.9 sim env: vendor easyxafs fixes the sidecar depends on."""
import os
from pathlib import Path
import pytest

from helao.deploy.hte.drivers.xafs.sidecar import sim_hw


def test_saved_path_set(tmp_path, monkeypatch):
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
    s._thread.join(timeout=30)  # wait_until_complete() races the saves

    assert Path(s.saved_path).name.startswith("Zn_Scan0000_Sample1_X0.000_Y0.000")
    assert "cache" not in Path(s.saved_path).parts
    assert s.saved_path.endswith("_000_exd.csv.zip")
    assert os.path.isfile(s.saved_path)


def test_saved_path_not_set_if_archive_write_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sim_hw.install_sim(str(tmp_path))
    import easyxafs.saveable_scan as ss
    import easyxafs.scan as scan

    s = scan.NormalScan(
        crystal2d="Si(5,5,3)", beta_offset=0, theta_offset=0, analyzer_radius=500,
        roi_bragg=80, roi_min=800, roi_max=1000,
        measurement_mode="XAFS_Fluorescence", saveaftercomplete=False,
    )
    s.create_zone_constant_step(9600, 9620, 5, 0.01)
    s.start()
    s._thread.join(timeout=30)
    assert s.saved_path is None
    monkeypatch.setattr(ss.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        s._save_scan_data(str(tmp_path / "Zn_fail"))
    assert s.saved_path is None


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_thetascan_exception_sets_finished(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = sim_hw.install_sim(str(tmp_path))
    # ThetaScan calls mono.move_to_bragg_angle only once (the axis moves go via
    # mono.Theta etc., which FakeMono lacks), so fail the 1st call, and stub the
    # one FakeMono gap that would otherwise raise first.
    h.mono.fail_on_call = 1
    h.mono.set_theta_speed_acc = lambda: None
    import easyxafs.scan as scan

    s = scan.ThetaScan(
        crystal2d="Si(5,5,3)", analyzer_radius=500, angle=80,
        theta_min=79.9, theta_max=80.1, theta_step=0.05, duration=0.01,
        roi_bragg=80, roi_min=800, roi_max=1000,
        savename=str(tmp_path / "theta"),
        measurement_mode="XAFS_Fluorescence", scan_mode="Standard",
    )
    s.start()
    s._thread.join(10)  # wait_until_complete() has no timeout and would hang pre-fix
    assert not s._thread.is_alive()
    assert s._finished is True

