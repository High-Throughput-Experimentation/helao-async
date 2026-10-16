"""`repin_envs` rewrites pinned env and requirements files against solved versions."""

from repin_envs import read_dev, regenerate, regenerate_pip

PINNED = """name: helao
channels:
  - conda-forge
dependencies:
  - fastapi=0.141.1=h76d476e_0
  - gone=1.0=h0_0
  - python=3.14.7
"""

PINNED_PIP = """reflex==0.9.8
pyft232==0.12
https://github.com/meerstetter/pyMeCom/archive/master.zip
"""


def test_regenerate_updates_drops_and_keeps():
    new, report = regenerate(
        PINNED, conda={"fastapi": "0.142.2", "python": "3.14.7", "added": "1.0"}
    )
    lines = new.splitlines()
    assert "  - fastapi=0.142.2" in lines  # new version, build string gone
    assert "  - python=3.14.7" in lines
    assert not [ln for ln in lines if "gone" in ln]  # not in the solve: dropped
    assert not [ln for ln in lines if "added" in ln]  # new to the solve: not added
    assert any("drop gone" in r for r in report)


def test_regenerate_pip_updates_and_keeps():
    new, report = regenerate_pip(PINNED_PIP, pip={"reflex": "0.9.12"})
    lines = new.splitlines()
    assert "reflex==0.9.12" in lines
    assert "pyft232==0.12" in lines  # unresolved pip pin kept
    assert lines[-1].endswith("pyMeCom/archive/master.zip")  # URL never pinned
    assert any("pyft232" in r and "kept" in r for r in report)


def test_regenerate_keeps_crlf():
    new, _ = regenerate(PINNED.replace("\n", "\r\n"), {"python": "3.14.7"})
    assert new.count("\r\n") == new.count("\n")
    new, _ = regenerate_pip(PINNED_PIP.replace("\n", "\r\n"), {})
    assert new.count("\r\n") == new.count("\n")


def test_read_dev_splits_channels_conda_and_pip(tmp_path):
    dev = tmp_path / "x_dev_linux-64.yml"
    dev.write_text(
        "name: helao\nchannels:\n  - conda-forge\ndependencies:\n"
        "  - python=3.14\n  - sqlmodel>=0.0.42\n",
        encoding="utf-8",
    )
    req = tmp_path / "requirements.txt"
    req.write_text(
        "reflex\n\n# comment\nhttps://example.org/a.zip\nxy[reflex]\n",
        encoding="utf-8",
    )
    channels, conda, pip = read_dev(dev, req)
    assert channels == ["conda-forge"]
    assert conda == ["python=3.14", "sqlmodel>=0.0.42"]
    assert pip == ["reflex", "xy[reflex]"]
