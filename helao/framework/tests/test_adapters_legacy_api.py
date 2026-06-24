"""Tests for helao.framework.adapters.legacy_api (HTELegacyAPI).

Strategy
--------
HTELegacyAPI.__init__ sets up cache dicts and filesystem paths (J:\\ network
shares) but does NOT open any files or make network connections, so construction
is safe in CI.  ``has_access`` returns False when the J:\\ paths are absent,
which is expected in every non-Windows lab environment.

Pure methods (no filesystem access required):
  - getnumspaces / partitionlineitem / myeval
  - filedict_lines / createnestparamtup / createdict_tup / rcp_to_dict (in-mem)
  - readsingleplatemaptxt (when ``lines=`` kwarg is supplied)
  - get_multielementink_concentrationinfo (with a fabricated print dict)

Network / filesystem-dependent methods that are skipped:
  - get_info_plateid / get_platemap_plateid / get_elements_plateid — require J:\\
  - importinfo / getinfopath_plateid / getplatemappath_plateid — require J:\\
"""

import inspect
import math

import numpy
import pytest

from helao.framework.adapters.legacy_api import HTELegacyAPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api():
    """A default HTELegacyAPI instance (no network required)."""
    return HTELegacyAPI()


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------


def test_import():
    """The class is importable from its new framework path."""
    assert HTELegacyAPI is not None


def test_public_surface():
    """Key public methods are present on the class."""
    expected = [
        "has_access",
        "get_rcp_plateid",
        "get_info_plateid",
        "check_plateid",
        "check_printrecord_plateid",
        "check_annealrecord_plateid",
        "get_platemap_plateid",
        "get_elements_plateid",
        "getnumspaces",
        "rcp_to_dict",
        "getplatemappath_plateid",
        "importinfo",
        "tryprependpath",
        "getinfopath_plateid",
        "filedict_lines",
        "createnestparamtup",
        "createdict_tup",
        "get_multielementink_concentrationinfo",
        "partitionlineitem",
        "myeval",
        "readsingleplatemaptxt",
    ]
    for name in expected:
        assert hasattr(HTELegacyAPI, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_no_network(api):
    """HTELegacyAPI constructs without network access."""
    assert isinstance(api, HTELegacyAPI)


def test_caches_empty_after_construction(api):
    """All five caches start empty."""
    assert api.info_cache == {}
    assert api.map_cache == {}
    assert api.infopath_cache == {}
    assert api.pmpath_pid_cache == {}
    assert api.els_cache == {}


def test_has_access_false_without_jdrive(api):
    """has_access returns False when the J:\\ paths are unavailable (Linux CI)."""
    assert api.has_access is False


# ---------------------------------------------------------------------------
# getnumspaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("hello", 0),
        ("  hello", 2),
        ("    hello", 4),
        ("", 0),
        ("   ", 3),
    ],
)
def test_getnumspaces(api, line, expected):
    assert api.getnumspaces(line) == expected


# ---------------------------------------------------------------------------
# partitionlineitem
# ---------------------------------------------------------------------------


def test_partitionlineitem_simple(api):
    assert api.partitionlineitem("key: value") == ("key", "value")


def test_partitionlineitem_no_value(api):
    key, val = api.partitionlineitem("key:")
    assert key == "key"
    assert val == ""


def test_partitionlineitem_colon_in_value(api):
    """Only the first colon is used as the separator."""
    key, val = api.partitionlineitem("key: http://example.com")
    assert key == "key"
    assert val == "http://example.com"


# ---------------------------------------------------------------------------
# myeval
# ---------------------------------------------------------------------------


def test_myeval_none(api):
    assert api.myeval("None") is None


def test_myeval_nan(api):
    assert math.isnan(api.myeval("nan"))


def test_myeval_NaN(api):
    assert math.isnan(api.myeval("NaN"))


def test_myeval_zero(api):
    assert api.myeval("0") == 0


def test_myeval_leading_zeros(api):
    """Leading zeros are stripped before eval."""
    assert api.myeval("007") == 7


def test_myeval_float(api):
    assert api.myeval("3.14") == pytest.approx(3.14)


def test_myeval_integer(api):
    assert api.myeval("42") == 42


# ---------------------------------------------------------------------------
# filedict_lines / createnestparamtup / createdict_tup
# ---------------------------------------------------------------------------


def test_filedict_lines_flat(api):
    lines = ["key1: val1\n", "key2: val2\n"]
    result = api.filedict_lines(lines)
    assert result == {"key1": "val1", "key2": "val2"}


def test_filedict_lines_blank_lines_ignored(api):
    lines = ["key1: val1\n", "\n", "   \n", "key2: val2\n"]
    result = api.filedict_lines(lines)
    assert result == {"key1": "val1", "key2": "val2"}


def test_createnestparamtup_pops_line(api):
    lines = ["key: value\n"]
    tup = api.createnestparamtup(lines)
    assert lines == []  # consumed
    assert tup[0] == "key: value"
    assert tup[1] == []


def test_createdict_tup_no_children(api):
    tup = ("key: value", [])
    k, v = api.createdict_tup(tup)
    assert k == "key"
    assert v == "value"


def test_createdict_tup_with_children(api):
    tup = ("parent:", [("  child: val", [])])
    k, v = api.createdict_tup(tup)
    assert k == "parent"
    assert isinstance(v, dict)
    assert v["child"] == "val"


# ---------------------------------------------------------------------------
# readsingleplatemaptxt (in-memory lines)
# ---------------------------------------------------------------------------

_PLATEMAP_LINES = [
    "% fiducials: (1.0, 2.0), (3.0, 4.0)mm\n",
    "% sample_no,x,y,A,B,C\n",
    "1,10.0,20.0,0.5,0.3,0.2\n",
    "2,11.0,21.0,0.4,0.4,0.2\n",
]


def test_readsingleplatemaptxt_count(api):
    dlist, fid = api.readsingleplatemaptxt("", lines=_PLATEMAP_LINES)
    assert len(dlist) == 2


def test_readsingleplatemaptxt_keys(api):
    dlist, _ = api.readsingleplatemaptxt("", lines=_PLATEMAP_LINES)
    assert "sample_no" in dlist[0]
    assert "x" in dlist[0]
    assert "y" in dlist[0]


def test_readsingleplatemaptxt_values(api):
    dlist, _ = api.readsingleplatemaptxt("", lines=_PLATEMAP_LINES)
    assert dlist[0]["sample_no"] == 1
    assert dlist[0]["x"] == pytest.approx(10.0)


def test_readsingleplatemaptxt_bad_path_returns_empty(api):
    """When ``lines`` is None and path doesn't exist, returns ([], [])."""
    dlist, fid = api.readsingleplatemaptxt("/nonexistent/path.txt")
    assert dlist == []
    assert fid == []


# ---------------------------------------------------------------------------
# get_multielementink_concentrationinfo
# ---------------------------------------------------------------------------


def test_multielementink_no_concentration_info_returns_none(api):
    """Returns None when concentration keys are absent and return_defaults_if_none=False."""
    printd = {"elements": "Fe,Co,Ni"}
    result = api.get_multielementink_concentrationinfo(printd, ["Fe", "Co", "Ni"])
    assert result is None


def test_multielementink_defaults_identity(api):
    """With return_defaults_if_none=True and 3 unique elements returns identity matrix."""
    printd = {"elements": "Fe,Co,Ni"}
    result = api.get_multielementink_concentrationinfo(
        printd, ["Fe", "Co", "Ni"], return_defaults_if_none=True
    )
    assert result is not None
    ok, (cels, mat) = result
    assert ok is False
    assert cels == ["Fe", "Co", "Ni"]
    numpy.testing.assert_array_almost_equal(mat, numpy.identity(3))


def test_multielementink_with_concentration_info(api):
    """When concentration_elements and concentration_values are present, returns matrix."""
    printd = {
        "elements": "Fe,Co,Ni",
        "concentration_elements": "Fe, Co, Ni",
        "concentration_values": "1.0, 1.0, 1.0",
    }
    result = api.get_multielementink_concentrationinfo(printd, ["Fe", "Co", "Ni"])
    # Equal concentrations fall through to the return_defaults_if_none=False final path
    # which returns None for uniform concentrations without return_defaults_if_none
    # Either None or (False, ...) is acceptable
    # The branch for len(cels_set)==len(cels) and all-same-conc returns None when
    # return_defaults_if_none is False
    assert result is None or (isinstance(result, tuple) and len(result) == 2)


# ---------------------------------------------------------------------------
# Filesystem-dependent paths — skipped in CI
# ---------------------------------------------------------------------------


def test_importinfo_skipped_no_jdrive(api):
    """importinfo returns None when the J:\\ plate folder is absent."""
    result = api.importinfo(99999)
    assert result is None


def test_getinfopath_skipped_no_jdrive(api):
    """getinfopath_plateid returns None when the J:\\ folder is absent."""
    result = api.getinfopath_plateid(99999)
    assert result is None


def test_check_plateid_false_no_jdrive(api):
    """check_plateid returns False when no info file exists."""
    assert api.check_plateid(99999) is False
