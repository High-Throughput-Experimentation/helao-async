"""Reader tests for the legacy JCAP archive format (synthetic zips only)."""

import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from helao.helpers.legacy_api import (
    HTELegacyAPI,
    FileAttrs,
    labview_epoch_to_utc,
    parse_file_attrs,
    rcp_text_to_dict,
    read_eche_file,
    read_exp,
    read_run_rcp,
    rename_column,
    resolve_run_zip,
    split_technique,
)

EXP_TEXT = """exp_version: 3
plate_ids: 3500
name: 20160720.163219

run__1:
    run_path: /eche/hte-eche-06/20160720_X_35008/20160720.153523.copied-20160720162356675PDT.zip
    run_use: data
    name: 20160720.153523
    parameters:
        plate_id: 3500
        platemap_file_path: J:\\hte_jcap_app_proto\\plate\\3500\\3500-8742.map
    files_technique__CP3:
        pstat_files:
            Sample212_x51_y80_Ni0Fe0_CP3.txt: eche_gamry_txt_file;t(s),Ewe(V),Ach(V),I(A),Toggle;15;150;212
run__1:
    name: duplicate
"""


def test_rcp_text_nesting_and_colon_values():
    d = rcp_text_to_dict(EXP_TEXT)
    assert d["exp_version"] == "3"
    r1 = d["run__1"][0]
    assert r1["parameters"]["platemap_file_path"].startswith("J:\\hte")
    files = r1["files_technique__CP3"]["pstat_files"]
    assert list(files) == ["Sample212_x51_y80_Ni0Fe0_CP3.txt"]


def test_rcp_text_duplicate_key_becomes_list():
    d = rcp_text_to_dict(EXP_TEXT)
    assert isinstance(d["run__1"], list) and d["run__1"][1] == {"name": "duplicate"}


def test_rcp_text_empty_container_is_empty_string():
    assert rcp_text_to_dict("a:\nb: 1\n") == {"a": "", "b": "1"}


def _zip(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return str(path)


def test_read_exp_member_name_differs(tmp_path):
    z = _zip(
        tmp_path / "20160720.163219.copied-1PDT.zip", {"renamed.exp": b"name: x\n"}
    )
    assert read_exp(z) == {"name": "x"}


def test_read_exp_requires_exactly_one_member(tmp_path):
    z = _zip(tmp_path / "a.zip", {"a.exp": b"n: 1\n", "b.exp": b"n: 2\n"})
    with pytest.raises(ValueError):
        read_exp(z)


def test_read_exp_zero_members_raises(tmp_path):
    z = _zip(tmp_path / "a.zip", {"a.rcp": b"n: 1\n"})
    with pytest.raises(ValueError):
        read_exp(z)


def test_read_run_rcp_cp1252(tmp_path):
    z = _zip(tmp_path / "r.zip", {"r.rcp": "unit: \xb5A\n".encode("cp1252")})
    assert read_run_rcp(z) == {"unit": "\u00b5A"}


@pytest.mark.parametrize(
    "fn,value,expected",
    [
        (
            "a.csv",
            "xrfs_batch_csv_file;",
            FileAttrs("xrfs_batch_csv_file", (), None, None, 0),
        ),
        (
            "Sample7_CA1.txt",
            "eche_gamry_txt_file;7",
            FileAttrs("eche_gamry_txt_file", (), None, None, 7),
        ),
        (
            "Sample7_CA1.txt",
            "t;t(s),I(A);7",
            FileAttrs("t", ("t(s)", "I(A)"), None, None, 7),
        ),
        ("x.txt", "t;a,b;15;150", FileAttrs("t", ("a", "b"), 15, 150, 0)),
        ("x.txt", "t;a,b;15;150;212", FileAttrs("t", ("a", "b"), 15, 150, 212)),
        ("Sample9_CA1.txt", "t;a,b;15;150;", FileAttrs("t", ("a", "b"), 15, 150, 9)),
        ("x.png", "img;;5", FileAttrs("img", (), None, None, 5)),
        ("t.txt", "t;;15;150;212", FileAttrs("t", (), 15, 150, 212)),
        ("t.txt", "t;t(s),I(A)", FileAttrs("t", ("t(s)", "I(A)"), None, None, 0)),
    ],
)
def test_parse_file_attrs_variants(fn, value, expected):
    assert parse_file_attrs(fn, value) == expected


def test_split_technique_multidigit():
    assert split_technique("CA12") == ("CA", 12)
    assert split_technique("CV3") == ("CV", 3)
    assert split_technique("XRFS") == ("XRFS", 0)


def test_resolve_run_zip_fallbacks(tmp_path):
    d = tmp_path / "eche" / "m" / "day"
    d.mkdir(parents=True)
    (d / "20160720.153523.copied-20160720162356675PDT.zip").write_bytes(b"")
    root = str(tmp_path)
    exact = "/eche/m/day/20160720.153523.copied-20160720162356675PDT.zip"
    assert resolve_run_zip(root, exact).endswith("675PDT.zip")
    # .exp sometimes stores the unzipped folder name (no .zip)
    assert resolve_run_zip(root, exact[:-4]).endswith("675PDT.zip")
    # copy stamp differs (PST re-copy): fall back on the 15-char timestamp
    assert resolve_run_zip(root, "/eche/m/day/20160720.153523.done").endswith(
        "675PDT.zip"
    )
    assert resolve_run_zip(root, "/eche/m/day/20990101.000000.done") is None


ECHE_TXT = (
    "%Plate=\n%Sample=212\n%x=51.0 mm\n%y=80.0 mm\n%elements=Ni\tFe\n"
    "%compositions=0.5\t0.5\n%code=0\n%TechniqueParamsName=3\n%TechniqueName=CP\n"
    "%ExperimentVIpath=C:\\INST\\a.vi\n%ExperimentParamsVIpath=C:\\INST\\b.vi\n"
    "%ToggleValue=1\n%Epoch=3551899182.9\n%Version=4.00\n"
    "%column_headings=t(s)\tEwe(V)\tAch(V)\tI(A)\tToggle\n"
    "1.0E-1\t8.15E-1\t-7.9E-4\t3.0E-5\t0.0E+0\n"
    "2.0E-1\t8.16E-1\t-7.8E-4\t3.0E-5\t1.0E+0\n"
)


def test_labview_epoch_known_value():
    assert labview_epoch_to_utc(3551899182.9) == datetime(
        2016, 7, 20, 22, 39, 42, 900000, tzinfo=timezone.utc
    )


def test_rename_column():
    assert [
        rename_column(c) for c in ["t(s)", "Ewe(V)", "I(A)", "Ach(V)", "Toggle"]
    ] == ["t_s", "Ewe_V", "I_A", "Ach_V", "Toggle"]


def test_read_eche_file(tmp_path):
    p = tmp_path / "r.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Sample212_CP3.txt", ECHE_TXT)
    with zipfile.ZipFile(p, "r") as z:
        header, cols = read_eche_file(z, "Sample212_CP3.txt")
    assert header["Sample"] == "212" and header["TechniqueName"] == "CP"
    assert list(cols) == ["t_s", "Ewe_V", "Ach_V", "I_A", "Toggle"]
    assert cols["I_A"] == [3.0e-5, 3.0e-5]


def test_read_eche_file_cp1252_crlf(tmp_path):
    p = tmp_path / "r.zip"
    body = (
        ECHE_TXT.replace("%Plate=", "%Plate=\xb5")
        .replace("\n", "\r\n")
        .encode("cp1252")
    )
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("f.txt", body)
    with zipfile.ZipFile(p, "r") as z:
        header, cols = read_eche_file(z, "f.txt")
    assert header["Plate"] == "\u00b5"
    assert len(cols["t_s"]) == 2


def test_rcp_text_malformed_indent_nests():
    # depth is the raw leading-space count: any deeper indent nests
    assert rcp_text_to_dict("a:\n  b: 1\n") == {"a": {"b": "1"}}


def test_rcp_to_dict_text_cp1252(tmp_path):
    p = tmp_path / "1.info"
    p.write_bytes(b"unit: \xb5A\n")
    assert HTELegacyAPI().rcp_to_dict(str(p)) == {"unit": "\u00b5A"}


def test_eche_row_cell_count_mismatch_raises(tmp_path):
    body = "%column_headings=a\tb\n1\t2\n3\t\t4\n"
    p = tmp_path / "r.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("f.txt", body)
    with zipfile.ZipFile(p) as z:
        with pytest.raises(ValueError, match=r"f\.txt:3"):
            read_eche_file(z, "f.txt")


def test_eche_missing_headings_raises(tmp_path):
    p = tmp_path / "r.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("f.txt", "%Plate=\n1\t2\n")
    with zipfile.ZipFile(p) as z:
        with pytest.raises(ValueError):
            read_eche_file(z, "f.txt")


def test_resolve_run_zip_non_stamp_dir_is_none(tmp_path):
    d = tmp_path / "day"
    d.mkdir()
    (d / "unrelated.zip").write_bytes(b"")
    assert resolve_run_zip(str(tmp_path), "/day/") is None


def test_resolve_run_zip_picks_lexically_last(tmp_path):
    d = tmp_path / "day"
    d.mkdir()
    for n in ("20160720.153523.copied-1PDT.zip", "20160720.153523.copied-2PST.zip"):
        (d / n).write_bytes(b"")
    assert resolve_run_zip(str(tmp_path), "/day/20160720.153523.x").endswith("2PST.zip")
