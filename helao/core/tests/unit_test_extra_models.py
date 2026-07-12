"""Unit tests for the smaller pydantic models under ``helao.core.models``.

The action/experiment/sequence test module already covers the queue
models; this module covers everything else under ``helao.core.models``
and the loader enums:

* :class:`RunUse`, :class:`ProcessContrib`, :class:`Electrolyte`,
  :class:`YmlType` — full enum membership/value coverage.
* :class:`HelaoDirs` — defaults and ``Path`` round-trip via ``as_dict``.
* :class:`S3Locator` — ``url`` property and ``s3://`` formatting.
* :class:`ProcessModel` / :class:`ShortProcessModel` — defaults,
  required vs. optional fields, ``hlo_version`` factory.
* :class:`DataModel` / :class:`DataPackageModel` — defaults, error list,
  status default, action_name/uuid passthrough.
* :class:`AnalysisDataModel` / :class:`AnalysisOutputModel` /
  :class:`ShortAnalysisModel` / :class:`AnalysisModel` — including the
  custom ``__init__`` that auto-stamps ``analysis_timestamp``.
"""

__all__ = ["extra_models_unit_test"]

import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from helao.core.drivers.data.enum import YmlType
from helao.core.error import ErrorCodes
from helao.core.models.analysis import (
    AnalysisDataModel,
    AnalysisModel,
    AnalysisOutputModel,
    ShortAnalysisModel,
)
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.electrolyte import Electrolyte
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.hlostatus import HloStatus
from helao.core.models.process import ProcessModel, ShortProcessModel
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_dir import RunDir
from helao.core.models.run_use import RunUse
from helao.core.models.s3locator import S3Locator
from helao.core.tests._test_utils import TestReporter


def extra_models_unit_test() -> bool:
    """Run all extra-model assertions and report pass/fail."""
    reporter = TestReporter("extra_models")

    try:
        reporter.section("RunUse enum")
        reporter.check(
            "RunUse.data is the default-data tag",
            lambda: RunUse.data.value == "data",
        )
        reporter.check(
            "RunUse round-trips through its value",
            lambda: RunUse(RunUse.ref_light.value) is RunUse.ref_light,
        )
        reporter.check(
            "RunUse exposes every documented spectroscopy reference",
            lambda: {RunUse.ref, RunUse.ref_light, RunUse.ref_dark, RunUse.ref_bkg}
            .issubset(set(RunUse)),
        )

        reporter.section("ProcessContrib enum")
        reporter.check(
            "ProcessContrib has the six documented members",
            lambda: {m.name for m in ProcessContrib}
            == {
                "action_params",
                "files",
                "samples_in",
                "samples_out",
                "run_use",
                "technique_name",
            },
        )
        reporter.check(
            "ProcessContrib.technique_name round-trips through its value",
            lambda: ProcessContrib("technique_name") is ProcessContrib.technique_name,
        )

        reporter.section("Electrolyte enum")
        reporter.check(
            "Electrolyte.other is the escape-hatch member",
            lambda: Electrolyte.other.value == "other-see-comment",
        )
        reporter.check(
            "all Electrolyte values are non-empty unique strings",
            lambda: len({e.value for e in Electrolyte}) == len(list(Electrolyte))
            and all(isinstance(e.value, str) and e.value for e in Electrolyte),
        )

        reporter.section("YmlType enum")
        reporter.check(
            "YmlType has the three top-level kinds",
            lambda: {m.value for m in YmlType}
            == {"action", "experiment", "sequence"},
        )

        reporter.section("HelaoDirs defaults and Path round-trip")
        hd = HelaoDirs()
        reporter.check(
            "HelaoDirs defaults every directory to None",
            lambda: all(
                getattr(hd, k) is None
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
                )
            ),
        )
        hd2 = HelaoDirs(
            root=Path("/tmp/helao"),
            save_root=Path(f"/tmp/helao/{RunDir.FINISHED.value}"),
            log_root=Path("/tmp/helao/LOGS"),
        )
        dumped = hd2.as_dict()
        reporter.check(
            "HelaoDirs.as_dict serialises Path values to posix strings",
            lambda: dumped["root"] == "/tmp/helao"
            and dumped["save_root"] == f"/tmp/helao/{RunDir.FINISHED.value}",
        )

        reporter.section("S3Locator url property")
        loc = S3Locator(bucket="helao.data", key="action/abcd.json", region="us-east-2")
        reporter.check(
            "S3Locator.url renders s3://bucket/key",
            lambda: loc.url == "s3://helao.data/action/abcd.json",
        )

        reporter.section("ShortProcessModel + ProcessModel")
        sp = ShortProcessModel()
        reporter.check(
            "ShortProcessModel.hlo_version comes from the default factory",
            lambda: isinstance(sp.hlo_version, str) and len(sp.hlo_version) > 0,
        )
        reporter.check(
            "ShortProcessModel default process_uuid is None",
            lambda: sp.process_uuid is None,
        )
        proc_uuid = uuid4()
        pm = ProcessModel(
            process_uuid=proc_uuid,
            technique_name="test_tech",
            process_params={"k": "v"},
        )
        reporter.check(
            "ProcessModel inherits ShortProcessModel",
            lambda: isinstance(pm, ShortProcessModel),
        )
        reporter.check(
            "ProcessModel default run_use is RunUse.data",
            lambda: pm.run_use is RunUse.data,
        )
        reporter.check(
            "ProcessModel default access is 'hte'",
            lambda: pm.access == "hte",
        )
        reporter.check(
            "ProcessModel preserves the supplied technique_name",
            lambda: pm.technique_name == "test_tech",
        )
        reporter.check(
            "ProcessModel.as_dict round-trips the process_params dict",
            lambda: pm.as_dict()["process_params"] == {"k": "v"},
        )

        reporter.section("DataModel + DataPackageModel")
        conn_uuid = uuid4()
        act_uuid = uuid4()
        dm = DataModel(data={conn_uuid: {"t_s": [0.0], "v": [0.1]}})
        reporter.check(
            "DataModel default status is HloStatus.active",
            lambda: dm.status is HloStatus.active,
        )
        reporter.check(
            "DataModel default errors is empty list",
            lambda: dm.errors == [],
        )
        reporter.check(
            "DataModel.data is keyed by file_conn_key UUID",
            lambda: conn_uuid in dm.data and dm.data[conn_uuid]["v"] == [0.1],
        )

        pkg = DataPackageModel(
            action_uuid=act_uuid,
            action_name="record",
            datamodel=dm,
            errors=[ErrorCodes.none],
        )
        reporter.check(
            "DataPackageModel preserves action_uuid",
            lambda: pkg.action_uuid == act_uuid,
        )
        reporter.check(
            "DataPackageModel preserves action_name",
            lambda: pkg.action_name == "record",
        )
        reporter.check(
            "DataPackageModel embeds the wrapped DataModel",
            lambda: pkg.datamodel is dm,
        )
        reporter.check(
            "DataPackageModel.as_dict serialises ErrorCodes by name",
            lambda: pkg.as_dict()["errors"] == ["none"],
        )

        reporter.section("ShortAnalysisModel auto-stamps timestamp on init")
        sa = ShortAnalysisModel()
        reporter.check(
            "ShortAnalysisModel populates analysis_timestamp via __init__",
            lambda: isinstance(sa.analysis_timestamp, datetime),
        )
        explicit_ts = datetime(2024, 1, 2, 3, 4, 5)
        sa2 = ShortAnalysisModel(analysis_timestamp=explicit_ts)
        reporter.check(
            "ShortAnalysisModel keeps an explicit analysis_timestamp",
            lambda: sa2.analysis_timestamp == explicit_ts,
        )

        reporter.section("AnalysisDataModel + AnalysisOutputModel")
        adm = AnalysisDataModel(
            action_uuid=act_uuid,
            raw_data_path="raw_data/abc.hlo",
            data_keys=["t_s", "v"],
        )
        reporter.check(
            "AnalysisDataModel default run_use is RunUse.data",
            lambda: adm.run_use is RunUse.data,
        )
        reporter.check(
            "AnalysisDataModel preserves data_keys list",
            lambda: adm.data_keys == ["t_s", "v"],
        )
        aom = AnalysisOutputModel(
            analysis_output_path=S3Locator(
                bucket="b", key="k", region="us-east-1"
            ),
            content_type="application/json",
            output_type="curve",
            output={"slope": 1.5, "ok": True},
        )
        reporter.check(
            "AnalysisOutputModel embeds the S3Locator path",
            lambda: aom.analysis_output_path.url == "s3://b/k",
        )
        reporter.check(
            "AnalysisOutputModel preserves the inline output dict",
            lambda: aom.output == {"slope": 1.5, "ok": True},
        )

        reporter.section("AnalysisModel composes inputs + outputs")
        am = AnalysisModel(
            analysis_name="ana",
            analysis_params={"window": 5},
            inputs=[adm],
            outputs=[aom],
        )
        reporter.check(
            "AnalysisModel inherits ShortAnalysisModel",
            lambda: isinstance(am, ShortAnalysisModel),
        )
        reporter.check(
            "AnalysisModel default access is 'hte'",
            lambda: am.access == "hte" and not am.dummy and not am.simulation,
        )
        reporter.check(
            "AnalysisModel.inputs[0] preserved with raw_data_path",
            lambda: am.inputs[0].raw_data_path == "raw_data/abc.hlo",
        )
        reporter.check(
            "AnalysisModel.outputs[0] preserved with content_type",
            lambda: am.outputs[0].content_type == "application/json",
        )
        am_dump = am.as_dict()
        reporter.check(
            "AnalysisModel.as_dict round-trips analysis_params",
            lambda: am_dump["analysis_params"] == {"window": 5},
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
