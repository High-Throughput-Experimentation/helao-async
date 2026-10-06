"""Pure filename and coordinate helpers for the xafs action server."""

import re

import pytest

from helao.deploy.hte.drivers.xafs.naming import (
    apply_affine,
    reference_name_from_label,
    reference_savename,
    sample_savename,
)

CONVERTER_RE = re.compile(
    r"^(.*?)_(Scan\d{4}_Sample\d+_)?(X[-.\d]+_Y[-.\d]+|EnergyCalib.*?|IzeroRef.*?)_\d{3}_exd\.csv\.zip$"
)


def test_sample_savename():
    assert (
        sample_savename("Zn", 0, 13983, -39.341, -0.225)
        == "Zn_Scan0000_Sample13983_X-39.341_Y-0.225"
    )


def test_reference_savenames():
    assert reference_savename("Zn", "izero", "Cu2O_pellet") == "Zn_IzeroRef_Cu2O_pellet"
    assert (
        reference_savename("Zn", "energy_calib", "ZnO_film") == "Zn_EnergyCalib_ZnO_film"
    )


def test_reference_savename_rejects_data():
    with pytest.raises(ValueError):
        reference_savename("Zn", "data", "ZnO_film")


def test_names_match_converter_regex():
    names = [
        sample_savename("Zn", 12, 5, 10.0, -3.5),
        reference_savename("Zn", "izero", "Cu2O_pellet"),
        reference_savename("Zn", "energy_calib", "ZnO_film"),
    ]
    for n in names:
        assert CONVERTER_RE.match(n + "_000_exd.csv.zip"), n


def test_apply_affine():
    assert apply_affine([[1, 0, 2], [0, 1, -3]], 1, 1) == (3, -2)
    assert apply_affine([[0, 1, 0], [-1, 0, 0]], 2, 5) == (5, -2)


def test_reference_name_from_label():
    refs = {"xafs-std__solid__1_1": {"name": "ZnO_film", "x_mm": 1.0, "y_mm": 2.0}}
    assert reference_name_from_label("xafs-std__solid__1_1", refs) == "ZnO_film"
    with pytest.raises(KeyError):
        reference_name_from_label("nope", refs)
