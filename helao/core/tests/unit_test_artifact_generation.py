"""Unit tests for YAML and HLO artifact generation/parsing.

Covers:

* :func:`helao.helpers.yml_tools.yml_dumps` / :func:`yml_load` round-trip,
  including the HELAO ``null`` representer and an ``ActionModel`` dumped
  through ``HelaoDict.as_dict``.
* HLO file reading via :func:`helao.helpers.hlo_data.read_hlo` and
  :func:`read_hlo_header` against a synthetic ``%%``-separated artifact.
* :func:`hlo_to_parquet` round-trip and the
  :func:`read_helao_metadata` accessor.
* ``FileInfo`` and ``HloHeaderModel`` defaults and their interaction with
  ``yml_dumps`` so we don't silently regress the YAML header layout.
"""

__all__ = ["artifact_generation_unit_test"]

import json
import os
import tempfile
import traceback

from helao.core.models.file import (
    FileInfo,
    HloHeaderModel,
    HloFileGroup,
)
from helao.core.models.machine import MachineModel
from helao.core.models.action import ActionModel
from helao.helpers.hlo_data import (
    read_hlo,
    read_hlo_header,
    hlo_to_parquet,
    read_helao_metadata,
)
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.core.tests._test_utils import TestReporter


def _write_synthetic_hlo(path: str) -> dict:
    """Write a tiny synthetic HLO file at ``path`` and return its header dict."""
    header = {
        "hlo_version": "0.0.0-test",
        "action_name": "synthetic",
        "column_headings": ["t_s", "v"],
        "optional": {"wl": [1.0, 2.0, 3.0], "note": "synthetic"},
        "epoch_ns": 1234567890,
    }
    rows = [
        {"t_s": 0.0, "v": 0.1},
        {"t_s": 0.1, "v": 0.2},
        {"t_s": 0.2, "v": 0.3},
    ]
    with open(path, "w") as fh:
        fh.write(yml_dumps(header))
        fh.write("%%\n")
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return header


def artifact_generation_unit_test() -> bool:
    """Run all YAML/HLO artifact assertions and report pass/fail."""
    reporter = TestReporter("artifact_generation")

    try:
        reporter.section("yml_dumps / yml_load round-trip")
        sample = {
            "run_type": "simulation",
            "dummy": True,
            "nullable": None,
            "list_field": [1, 2, 3],
            "nested": {"a": 1.5, "b": "two"},
        }
        dumped = yml_dumps(sample)
        reporter.check(
            "yml_dumps emits 'null' for None values",
            lambda: "nullable: null" in dumped,
        )
        reloaded = yml_load(dumped)
        reporter.check(
            "round-trip preserves top-level scalar fields",
            lambda: reloaded["run_type"] == "simulation"
            and reloaded["dummy"] is True
            and reloaded["nullable"] is None,
        )
        reporter.check(
            "round-trip preserves nested dict",
            lambda: dict(reloaded["nested"]) == {"a": 1.5, "b": "two"},
        )
        reporter.check(
            "round-trip preserves list ordering",
            lambda: list(reloaded["list_field"]) == [1, 2, 3],
        )

        reporter.section("yml_load can read from a Path")
        tmpdir = tempfile.mkdtemp(prefix="helao_test_yml_")
        ypath = os.path.join(tmpdir, "x.yml")
        with open(ypath, "w") as fh:
            fh.write(dumped)
        from_path = yml_load_path(ypath)
        reporter.check(
            "yml_load reads from a filesystem path",
            lambda: from_path["run_type"] == "simulation",
        )

        reporter.section("HloHeaderModel + FileInfo defaults")
        header_model = HloHeaderModel(
            action_name="meas", column_headings=["t", "v"], epoch_ns=42
        )
        reporter.check(
            "HloHeaderModel.optional defaults to empty dict",
            lambda: header_model.optional == {},
        )
        reporter.check(
            "HloHeaderModel.hlo_version populated by default factory",
            lambda: isinstance(header_model.hlo_version, str)
            and len(header_model.hlo_version) > 0,
        )
        finfo = FileInfo(file_name="x.hlo")
        reporter.check(
            "FileInfo.nosync defaults False",
            lambda: finfo.nosync is False,
        )
        reporter.check(
            "HloFileGroup.helao_files enum value",
            lambda: HloFileGroup.helao_files.value == "helao_files",
        )

        reporter.section("ActionModel.as_dict round-trips through yml_dumps")
        action = ActionModel(
            action_name="record",
            action_server=MachineModel(server_name="A", hostname="h", port=1),
            files=[FileInfo(file_name="rec.hlo", file_type="helao__file")],
        )
        act_yml = yml_dumps(action.as_dict())
        act_back = yml_load(act_yml)
        reporter.check(
            "ActionModel.as_dict YAML round-trip preserves action_name",
            lambda: act_back["action_name"] == "record",
        )
        reporter.check(
            "ActionModel.as_dict YAML round-trip preserves files entry",
            lambda: act_back["files"][0]["file_name"] == "rec.hlo",
        )

        reporter.section("read_hlo on a synthetic HLO file")
        hlo_path = os.path.join(tmpdir, "synthetic.hlo")
        original_header = _write_synthetic_hlo(hlo_path)
        meta, data = read_hlo(hlo_path)
        reporter.check(
            "read_hlo recovers the action_name from the header",
            lambda: meta["action_name"] == original_header["action_name"],
        )
        reporter.check(
            "read_hlo recovers the column_headings list",
            lambda: list(meta["column_headings"]) == original_header["column_headings"],
        )
        reporter.check(
            "read_hlo column 't_s' has three entries",
            lambda: data["t_s"] == [0.0, 0.1, 0.2],
        )
        reporter.check(
            "read_hlo column 'v' has the expected values",
            lambda: data["v"] == [0.1, 0.2, 0.3],
        )

        reporter.section("read_hlo keep_keys / omit_keys filtering")
        # keep_keys and omit_keys are OR-combined in the current implementation,
        # so to keep only one column populate both arguments explicitly.
        meta_k, data_k = read_hlo(hlo_path, keep_keys=["t_s"], omit_keys=["v"])
        reporter.check(
            "keep_keys + omit_keys retains only the requested column",
            lambda: list(data_k.keys()) == ["t_s"],
        )
        meta_o, data_o = read_hlo(hlo_path, omit_keys=["v"])
        reporter.check(
            "omit_keys drops the named column",
            lambda: "v" not in data_o and "t_s" in data_o,
        )

        reporter.section("read_hlo_header reports the data-start index")
        header_dict, start_index = read_hlo_header(hlo_path)
        reporter.check(
            "read_hlo_header returns positive data_start_index",
            lambda: start_index > 0,
        )
        reporter.check(
            "read_hlo_header header has matching action_name",
            lambda: header_dict["action_name"] == original_header["action_name"],
        )

        reporter.section("hlo_to_parquet round-trip and metadata")
        parquet_path = os.path.join(tmpdir, "synthetic.parquet")
        hlo_to_parquet(hlo_path, parquet_path, chunk_size=2)
        reporter.check(
            "hlo_to_parquet wrote a parquet file",
            lambda: os.path.exists(parquet_path),
        )
        metadict = read_helao_metadata(parquet_path)
        reporter.check(
            "read_helao_metadata recovers the optional header block",
            lambda: metadict.get("note") == "synthetic",
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


def yml_load_path(path):
    """Wrap :func:`yml_load` with a ``Path`` to exercise that resolution path."""
    from pathlib import Path

    return yml_load(Path(path))
