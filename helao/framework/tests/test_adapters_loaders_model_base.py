"""Tests for the framework adapter loaders model_base (HelaoDataModelMixin).

Verifies that the mixin's property/method logic works correctly on a concrete
subclass that supplies a ``json`` property returning a metadata dict.
"""

from helao.framework.adapters.loaders.model_base import HelaoDataModelMixin


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------

_SAMPLE_META = {
    "files": [
        {
            "file_name": "run_data.hlo",
            "file_type": "helao__file",
            "data_keys": ["t_s", "Ewe_V"],
            "action_uuid": "aaa-111",
        },
        {
            "file_name": "config.json",
            "file_type": "helao__json_file",
            "data_keys": [],
            "action_uuid": "aaa-111",
        },
        {
            "file_name": "photo.png",
            "file_type": "image__file",
            "data_keys": [],
            "action_uuid": "aaa-111",
        },
    ]
}


class _ConcreteDataModel(HelaoDataModelMixin):
    """Minimal concrete subclass — ``json`` returns a fixed metadata dict."""

    @property
    def json(self) -> dict:
        return _SAMPLE_META


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_data_files_returns_hlo_and_json_entries():
    obj = _ConcreteDataModel()
    df = obj.data_files
    # .hlo and helao__json_file entries should be included
    assert len(df) == 2
    names = [x["file_name"] for x in df]
    assert "run_data.hlo" in names
    assert "config.json" in names


def test_other_files_returns_non_data_entries():
    obj = _ConcreteDataModel()
    of = obj.other_files
    assert len(of) == 1
    assert of[0]["file_name"] == "photo.png"


def test_hlo_file_tup_returns_name_type_keys():
    obj = _ConcreteDataModel()
    name, ftype, dkeys = obj.hlo_file_tup
    assert name == "run_data.hlo"
    assert ftype == "helao__file"
    assert dkeys == ["t_s", "Ewe_V"]


def test_hlo_file_tup_type_with_contains_filter():
    obj = _ConcreteDataModel()
    # Filter matches
    name, ftype, dkeys = obj.hlo_file_tup_type(contains="helao")
    assert name == "run_data.hlo"

    # Filter that doesn't match
    name2, ftype2, dkeys2 = obj.hlo_file_tup_type(contains="nonexistent")
    assert name2 == ""
    assert ftype2 == ""
    assert dkeys2 == []


def test_hlo_file_returns_first_data_file():
    obj = _ConcreteDataModel()
    hf = obj.hlo_file
    assert hf["file_name"] == "run_data.hlo"


def test_data_files_empty_when_no_files():
    class _EmptyModel(HelaoDataModelMixin):
        @property
        def json(self):
            return {}

    obj = _EmptyModel()
    assert obj.data_files == []
    assert obj.other_files == []


def test_data_files_json_file_type_variants():
    """Both 'helao__json_file' and 'json__file' file_type values are included."""

    class _JsonTypeModel(HelaoDataModelMixin):
        @property
        def json(self):
            return {
                "files": [
                    {
                        "file_name": "a.json",
                        "file_type": "json__file",
                        "data_keys": [],
                    },
                    {
                        "file_name": "b.txt",
                        "file_type": "text__file",
                        "data_keys": [],
                    },
                ]
            }

    obj = _JsonTypeModel()
    df = obj.data_files
    assert len(df) == 1
    assert df[0]["file_name"] == "a.json"
