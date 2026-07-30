"""Unit tests for the ``MetaFileWriter`` collaborator extracted from ``Base``
(CARDS P6, Stage S3): the action/experiment/sequence meta-yml writers
(``_write_meta_atomic``/``write_act``/``write_exp``/``write_seq``) and the
file-connection-key helpers (``new_file_conn_key``/``dflt_file_conn_key``).

``test_active_golden_master.py --check`` already exercises ``write_act`` (and
transitively ``dflt_file_conn_key``) end-to-end through ``Active``'s lifecycle
and is the byte-gate for meta output; this module is the S3-specific
behavior-preservation gate that also directly covers ``write_exp``/
``write_seq``/``new_file_conn_key``, none of which the golden master drives.

Mirrors the ``Base.__new__`` bypass fixture used by
``test_active_golden_master.py``'s ``_make_base``: a bare ``Base`` built
without ``Base.__init__`` (no FastAPI app, no disk I/O beyond a temp
``save_root``), populated only with the attributes ``MetaFileWriter`` methods
touch, then ``_init_collaborators()`` is called so ``base.meta_writer``
exists exactly as it would after the real ``__init__``.

Hermetic: no network; real (temp-dir) disk I/O so the atomic-write + yml
round-trip is checked against genuine filesystem behavior, not a stand-in.
"""

__all__ = ["base_meta_writer_unit_test"]

import asyncio
import hashlib
import os
import tempfile
import traceback
from types import SimpleNamespace
from uuid import UUID

from helao.core.servers.base import Base
from helao.core.tests._test_utils import TestReporter
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.yml_tools import yml_load


def _make_base(save_root: str) -> Base:
    """Build a bare ``Base`` with every attribute ``MetaFileWriter`` methods touch."""
    base = Base.__new__(Base)
    base.helaodirs = SimpleNamespace(save_root=save_root)
    base._init_collaborators()
    return base


def _mk_action() -> Action:
    """Build a fully-initialised manual ``Action`` (no parent sequence/experiment)."""
    action = Action(action_name="metatest", action_abbr="meta")
    action.init_act()
    return action


def _mk_experiment() -> Experiment:
    experiment = Experiment(
        experiment_name="metatest_exp",
        sequence_name="metatest_seq",
        sequence_label="gm",
    )
    experiment.init_seq()
    experiment.init_exp()
    return experiment


def _mk_sequence() -> Sequence:
    sequence = Sequence(sequence_name="metatest_seq", sequence_label="gm")
    sequence.init_seq()
    return sequence


# ---------------------------------------------------------------------------
# new_file_conn_key / dflt_file_conn_key
# ---------------------------------------------------------------------------


def _check_new_file_conn_key() -> bool:
    base = _make_base(tempfile.mkdtemp())
    expected = UUID(hashlib.md5("some_key".encode("utf-8")).hexdigest())
    return base.new_file_conn_key("some_key") == expected


def _check_dflt_file_conn_key() -> bool:
    base = _make_base(tempfile.mkdtemp())
    expected = base.new_file_conn_key(str(None))
    return base.dflt_file_conn_key() == expected


# ---------------------------------------------------------------------------
# _write_meta_atomic
# ---------------------------------------------------------------------------


async def _check_write_meta_atomic() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    output_file = os.path.join(save_root, "sub", "dir", "out.yml")
    await base._write_meta_atomic(output_file, "a: 1\nb: 2")
    with open(output_file, "r") as f:
        content = f.read()
    # no leftover temp file
    leftovers = [
        fn for fn in os.listdir(os.path.dirname(output_file)) if fn.startswith(".")
    ]
    return content == "a: 1\nb: 2\n" and leftovers == []


# ---------------------------------------------------------------------------
# write_act / write_exp / write_seq
# ---------------------------------------------------------------------------


async def _check_write_act() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    action = _mk_action()
    await base.write_act(action)

    ts = action.action_timestamp.strftime("%y%m%d.%H%M%S%f")
    output_file = os.path.join(save_root, action.action_output_dir, f"{ts}-act.yml")
    assert os.path.isfile(output_file), f"expected act file at {output_file}"
    loaded = yml_load(output_file)
    return (
        loaded["file_type"] == "action"
        and loaded["action_name"] == "metatest"
        and loaded["action_uuid"] == str(action.action_uuid)
    )


async def _check_write_act_save_act_false() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    action = _mk_action()
    action.save_act = False
    await base.write_act(action)
    ts = action.action_timestamp.strftime("%y%m%d.%H%M%S%f")
    output_file = os.path.join(save_root, action.action_output_dir, f"{ts}-act.yml")
    return not os.path.isfile(output_file)


async def _check_write_exp() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    experiment = _mk_experiment()
    await base.write_exp(experiment)

    ts = experiment.experiment_timestamp.strftime("%y%m%d.%H%M%S%f")
    output_file = os.path.join(
        save_root, experiment.get_experiment_dir(), f"{ts}-exp.yml"
    )
    assert os.path.isfile(output_file), f"expected exp file at {output_file}"
    loaded = yml_load(output_file)
    return (
        loaded["file_type"] == "experiment"
        and loaded["experiment_name"] == "metatest_exp"
        and loaded["experiment_uuid"] == str(experiment.experiment_uuid)
    )


async def _check_write_seq() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    sequence = _mk_sequence()
    await base.write_seq(sequence)

    ts = sequence.sequence_timestamp.strftime("%y%m%d.%H%M%S%f")
    output_file = os.path.join(save_root, sequence.get_sequence_dir(), f"{ts}-seq.yml")
    assert os.path.isfile(output_file), f"expected seq file at {output_file}"
    loaded = yml_load(output_file)
    return (
        loaded["file_type"] == "sequence"
        and loaded["sequence_name"] == "metatest_seq"
        and loaded["sequence_uuid"] == str(sequence.sequence_uuid)
    )


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "new_file_conn_key": _check_new_file_conn_key(),
        "dflt_file_conn_key": _check_dflt_file_conn_key(),
        "write_meta_atomic": await _check_write_meta_atomic(),
        "write_act": await _check_write_act(),
        "write_act_save_act_false": await _check_write_act_save_act_false(),
        "write_exp": await _check_write_exp(),
        "write_seq": await _check_write_seq(),
    }


def base_meta_writer_unit_test() -> bool:
    reporter = TestReporter("base_meta_writer")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("new_file_conn_key / dflt_file_conn_key")
    reporter.check(
        "new_file_conn_key returns md5(key)-derived UUID",
        lambda: res["new_file_conn_key"],
    )
    reporter.check(
        "dflt_file_conn_key delegates to new_file_conn_key(str(None))",
        lambda: res["dflt_file_conn_key"],
    )

    reporter.section("_write_meta_atomic")
    reporter.check(
        "writes exact bytes (with trailing newline) via temp-file + os.replace, "
        "leaving no leftover temp file",
        lambda: res["write_meta_atomic"],
    )

    reporter.section("write_act / write_exp / write_seq")
    reporter.check(
        "write_act writes '<ts>-act.yml' with file_type=action and matching identity",
        lambda: res["write_act"],
    )
    reporter.check(
        "write_act is a no-op when action.save_act is False",
        lambda: res["write_act_save_act_false"],
    )
    reporter.check(
        "write_exp writes '<ts>-exp.yml' with file_type=experiment and matching identity",
        lambda: res["write_exp"],
    )
    reporter.check(
        "write_seq writes '<ts>-seq.yml' with file_type=sequence and matching identity",
        lambda: res["write_seq"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_meta_writer_unit_test() else 1)
