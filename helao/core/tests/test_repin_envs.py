"""`repin_envs.regenerate` rewrites a pinned env file against solved versions."""

from repin_envs import read_dev, regenerate

PINNED = """name: helao
channels:
  - conda-forge
dependencies:
  - fastapi=0.141.1=h76d476e_0
  - gone=1.0=h0_0
  - python=3.14.7
  - pip:
      - reflex==0.9.8
      - pyft232==0.12
      - https://github.com/meerstetter/pyMeCom/archive/master.zip
"""


def test_regenerate_updates_drops_and_keeps():
    new, report = regenerate(
        PINNED,
        conda={"fastapi": "0.142.2", "python": "3.14.7", "added": "1.0"},
        pip={"reflex": "0.9.12"},
    )
    lines = new.splitlines()
    assert "  - fastapi=0.142.2" in lines  # new version, build string gone
    assert "  - python=3.14.7" in lines
    assert not [ln for ln in lines if "gone" in ln]  # not in the solve: dropped
    assert not [ln for ln in lines if "added" in ln]  # new to the solve: not added
    assert "      - reflex==0.9.12" in lines
    assert "      - pyft232==0.12" in lines  # unresolved pip pin kept
    assert lines[-1].endswith("pyMeCom/archive/master.zip")  # URL never pinned
    assert any("drop gone" in r for r in report)


def test_regenerate_keeps_crlf():
    new, _ = regenerate(PINNED.replace("\n", "\r\n"), {"python": "3.14.7"}, {})
    assert new.count("\r\n") == new.count("\n")


def test_read_dev_splits_channels_conda_and_pip(tmp_path):
    dev = tmp_path / "x_dev_linux-64.yml"
    dev.write_text(
        "name: helao\nchannels:\n  - conda-forge\ndependencies:\n  - pip:\n"
        "    - reflex\n    - https://example.org/a.zip\n  - python=3.14\n"
        "  - sqlmodel>=0.0.42\n",
        encoding="utf-8",
    )
    channels, conda, pip = read_dev(dev)
    assert channels == ["conda-forge"]
    assert conda == ["python=3.14", "sqlmodel>=0.0.42"]
    assert pip == ["reflex"]
