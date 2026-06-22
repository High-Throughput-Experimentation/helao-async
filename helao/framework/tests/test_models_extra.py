"""Pytest port of ``helao/core/tests/unit_test_extra_models.py``.

The legacy module was a single ``extra_models_unit_test() -> bool`` that
ran a list of lambda checks and printed pass/fail. Here each behavior is a
real ``def test_*`` with ``assert``.

Covers the smaller pydantic models under ``helao.framework.models`` and
their enums:

* :class:`RunUse`, :class:`ProcessContrib`, :class:`Electrolyte` — enum
  membership / value round-trip.
* :class:`HelaoDirs` — defaults and ``Path`` round-trip via ``as_dict``.
* :class:`S3Locator` — ``url`` property and ``s3://`` formatting.
* :class:`ProcessModel` / :class:`ShortProcessModel` — defaults, required
  vs. optional fields, ``hlo_version`` factory.
* :class:`DataModel` / :class:`DataPackageModel` — defaults, error list,
  status default, action_name/uuid passthrough.
* :class:`AnalysisDataModel` / :class:`AnalysisOutputModel` /
  :class:`ShortAnalysisModel` / :class:`AnalysisModel` — including the
  custom ``__init__`` that auto-stamps ``analysis_timestamp``.

The legacy ``YmlType`` section is intentionally omitted: ``YmlType`` lives in
``helao.core.drivers.data.enum`` (a driver enum), which is out of scope for
the framework ``models/`` layer and has no framework equivalent.
"""
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from helao.framework.models.analysis import (
    AnalysisDataModel,
    AnalysisModel,
    AnalysisOutputModel,
    ShortAnalysisModel,
)
from helao.framework.models.data import DataModel, DataPackageModel
from helao.framework.models.electrolyte import Electrolyte
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.helaodirs import HelaoDirs
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.process import ProcessModel, ShortProcessModel
from helao.framework.models.process_contrib import ProcessContrib
from helao.framework.models.run_use import RunUse
from helao.framework.models.s3locator import S3Locator


# --------------------------------------------------------------------------- #
# RunUse enum
# --------------------------------------------------------------------------- #
def test_run_use_data_is_default_data_tag():
    assert RunUse.data.value == "data"


def test_run_use_round_trips_through_value():
    assert RunUse(RunUse.ref_light.value) is RunUse.ref_light


def test_run_use_exposes_spectroscopy_references():
    assert {RunUse.ref, RunUse.ref_light, RunUse.ref_dark, RunUse.ref_bkg}.issubset(
        set(RunUse)
    )


# --------------------------------------------------------------------------- #
# ProcessContrib enum
# --------------------------------------------------------------------------- #
def test_process_contrib_has_six_documented_members():
    assert {m.name for m in ProcessContrib} == {
        "action_params",
        "files",
        "samples_in",
        "samples_out",
        "run_use",
        "technique_name",
    }


def test_process_contrib_technique_name_round_trips():
    assert ProcessContrib("technique_name") is ProcessContrib.technique_name


# --------------------------------------------------------------------------- #
# Electrolyte enum
# --------------------------------------------------------------------------- #
def test_electrolyte_other_is_escape_hatch():
    assert Electrolyte.other.value == "other-see-comment"


def test_electrolyte_values_are_nonempty_unique_strings():
    values = [e.value for e in Electrolyte]
    assert len(set(values)) == len(values)
    assert all(isinstance(v, str) and v for v in values)


# --------------------------------------------------------------------------- #
# HelaoDirs defaults and Path round-trip
# --------------------------------------------------------------------------- #
def test_helaodirs_defaults_every_directory_to_none():
    hd = HelaoDirs()
    for k in (
        "root",
        "save_root",
        "log_root",
        "states_root",
        "db_root",
        "user_exp",
        "user_seq",
        "ana_root",
        "process_root",
    ):
        assert getattr(hd, k) is None


def test_helaodirs_as_dict_serialises_paths_to_posix_strings():
    hd = HelaoDirs(
        root=Path("/tmp/helao"),
        save_root=Path("/tmp/helao/RUNS_FINISHED"),
        log_root=Path("/tmp/helao/LOGS"),
    )
    dumped = hd.as_dict()
    assert dumped["root"] == "/tmp/helao"
    assert dumped["save_root"] == "/tmp/helao/RUNS_FINISHED"


# --------------------------------------------------------------------------- #
# S3Locator url property
# --------------------------------------------------------------------------- #
def test_s3locator_url_renders_s3_bucket_key():
    loc = S3Locator(bucket="helao.data", key="action/abcd.json", region="us-east-2")
    assert loc.url == "s3://helao.data/action/abcd.json"


# --------------------------------------------------------------------------- #
# ShortProcessModel + ProcessModel
# --------------------------------------------------------------------------- #
def test_short_process_model_hlo_version_from_factory():
    sp = ShortProcessModel()
    assert isinstance(sp.hlo_version, str) and len(sp.hlo_version) > 0


def test_short_process_model_default_process_uuid_is_none():
    assert ShortProcessModel().process_uuid is None


def test_process_model_inherits_short_process_model():
    pm = ProcessModel(process_uuid=uuid4())
    assert isinstance(pm, ShortProcessModel)


def test_process_model_default_run_use_is_data():
    assert ProcessModel(process_uuid=uuid4()).run_use is RunUse.data


def test_process_model_default_access_is_hte():
    assert ProcessModel(process_uuid=uuid4()).access == "hte"


def test_process_model_preserves_supplied_technique_name():
    pm = ProcessModel(process_uuid=uuid4(), technique_name="test_tech")
    assert pm.technique_name == "test_tech"


def test_process_model_as_dict_round_trips_process_params():
    pm = ProcessModel(process_uuid=uuid4(), process_params={"k": "v"})
    assert pm.as_dict()["process_params"] == {"k": "v"}


# --------------------------------------------------------------------------- #
# DataModel + DataPackageModel
# --------------------------------------------------------------------------- #
def test_data_model_default_status_is_active():
    conn_uuid = uuid4()
    dm = DataModel(data={conn_uuid: {"t_s": [0.0], "v": [0.1]}})
    assert dm.status is HloStatus.active


def test_data_model_default_errors_is_empty_list():
    dm = DataModel(data={uuid4(): {"v": [0.1]}})
    assert dm.errors == []


def test_data_model_data_keyed_by_file_conn_key_uuid():
    conn_uuid = uuid4()
    dm = DataModel(data={conn_uuid: {"t_s": [0.0], "v": [0.1]}})
    assert conn_uuid in dm.data
    assert dm.data[conn_uuid]["v"] == [0.1]


def test_data_package_preserves_action_uuid_and_name():
    act_uuid = uuid4()
    dm = DataModel(data={uuid4(): {"v": [0.1]}})
    pkg = DataPackageModel(action_uuid=act_uuid, action_name="record", datamodel=dm)
    assert pkg.action_uuid == act_uuid
    assert pkg.action_name == "record"


def test_data_package_embeds_wrapped_data_model():
    dm = DataModel(data={uuid4(): {"v": [0.1]}})
    pkg = DataPackageModel(action_uuid=uuid4(), action_name="record", datamodel=dm)
    assert pkg.datamodel is dm


def test_data_package_as_dict_serialises_errorcodes_by_name():
    dm = DataModel(data={uuid4(): {"v": [0.1]}})
    pkg = DataPackageModel(
        action_uuid=uuid4(),
        action_name="record",
        datamodel=dm,
        errors=[ErrorCodes.none],
    )
    assert pkg.as_dict()["errors"] == ["none"]


# --------------------------------------------------------------------------- #
# ShortAnalysisModel auto-stamps timestamp on init
# --------------------------------------------------------------------------- #
def test_short_analysis_model_auto_stamps_timestamp():
    sa = ShortAnalysisModel()
    assert isinstance(sa.analysis_timestamp, datetime)


def test_short_analysis_model_keeps_explicit_timestamp():
    explicit_ts = datetime(2024, 1, 2, 3, 4, 5)
    sa = ShortAnalysisModel(analysis_timestamp=explicit_ts)
    assert sa.analysis_timestamp == explicit_ts


# --------------------------------------------------------------------------- #
# AnalysisDataModel + AnalysisOutputModel
# --------------------------------------------------------------------------- #
def test_analysis_data_model_default_run_use_is_data():
    adm = AnalysisDataModel(
        action_uuid=uuid4(), raw_data_path="raw_data/abc.hlo", data_keys=["t_s", "v"]
    )
    assert adm.run_use is RunUse.data


def test_analysis_data_model_preserves_data_keys():
    adm = AnalysisDataModel(
        action_uuid=uuid4(), raw_data_path="raw_data/abc.hlo", data_keys=["t_s", "v"]
    )
    assert adm.data_keys == ["t_s", "v"]


def test_analysis_output_model_embeds_s3_locator_path():
    aom = AnalysisOutputModel(
        analysis_output_path=S3Locator(bucket="b", key="k", region="us-east-1"),
        content_type="application/json",
        output_type="curve",
        output={"slope": 1.5, "ok": True},
    )
    assert aom.analysis_output_path.url == "s3://b/k"


def test_analysis_output_model_preserves_inline_output_dict():
    aom = AnalysisOutputModel(
        analysis_output_path=S3Locator(bucket="b", key="k", region="us-east-1"),
        content_type="application/json",
        output_type="curve",
        output={"slope": 1.5, "ok": True},
    )
    assert aom.output == {"slope": 1.5, "ok": True}


# --------------------------------------------------------------------------- #
# AnalysisModel composes inputs + outputs
# --------------------------------------------------------------------------- #
def _make_analysis_model():
    adm = AnalysisDataModel(
        action_uuid=uuid4(), raw_data_path="raw_data/abc.hlo", data_keys=["t_s", "v"]
    )
    aom = AnalysisOutputModel(
        analysis_output_path=S3Locator(bucket="b", key="k", region="us-east-1"),
        content_type="application/json",
        output_type="curve",
        output={"slope": 1.5, "ok": True},
    )
    return AnalysisModel(
        analysis_name="ana",
        analysis_params={"window": 5},
        inputs=[adm],
        outputs=[aom],
    )


def test_analysis_model_inherits_short_analysis_model():
    assert isinstance(_make_analysis_model(), ShortAnalysisModel)


def test_analysis_model_default_access_and_flags():
    am = _make_analysis_model()
    assert am.access == "hte"
    assert not am.dummy
    assert not am.simulation


def test_analysis_model_preserves_inputs_and_outputs():
    am = _make_analysis_model()
    assert am.inputs[0].raw_data_path == "raw_data/abc.hlo"
    assert am.outputs[0].content_type == "application/json"


def test_analysis_model_as_dict_round_trips_analysis_params():
    am = _make_analysis_model()
    assert am.as_dict()["analysis_params"] == {"window": 5}
