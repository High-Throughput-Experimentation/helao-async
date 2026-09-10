"""NativeMetaFileWriter (P2b-1): verbatim re-body of legacy MetaFileWriter
(helao/core/servers/base_meta_writer.py). Source-parity-pinned + behavior
checks on a real tmp tree (atomic tmp+os.replace, trailing newline,
file_type first key, RUNS_ACTIVE->RUNS_DIAG manual swap, md5 conn keys)."""

import asyncio
import os
from uuid import UUID

import pytest

from helao.core.models.run_dir import RunDir
from helao.core.servers.base_meta_writer import MetaFileWriter
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.tests.native_fixtures import (
    assert_source_parity,
    make_base,
    mk_action,
)

METHODS = [
    "__init__",
    "_write_meta_atomic",
    "write_act",
    "write_exp",
    "write_seq",
    "new_file_conn_key",
    "dflt_file_conn_key",
]


def test_source_parity_with_legacy():
    assert_source_parity(NativeMetaFileWriter, MetaFileWriter, METHODS)


def _swap(base, tmp_path):
    base.meta_writer = NativeMetaFileWriter(base)  # type: ignore[reportAttributeAccessIssue]
    return base


@pytest.mark.asyncio
async def test_write_act_layout(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action(save_act=True)
    await base.write_act(action)
    out_dir = os.path.join(save_root, str(action.action_output_dir))
    files = [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]
    assert files == ["260102.030405678901-act.yml"]
    text = open(os.path.join(out_dir, files[0])).read()
    assert text.startswith("file_type: action\n")  # file_type first key
    assert text.endswith("\n")  # trailing newline
    assert not [f for f in os.listdir(out_dir) if f.endswith(".tmp")]


@pytest.mark.asyncio
async def test_write_meta_atomic_tmp_shape(tmp_path):
    """Atomic write goes through a short .<hex>.tmp sibling then os.replace
    (base_meta_writer.py:76-79)."""
    base = _swap(make_base(str(tmp_path)), tmp_path)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["src"], seen["dst"] = src, dst
        return real_replace(src, dst)

    import helao.hexagon.adapters.native.meta_writer as mw

    orig = mw.os.replace
    mw.os.replace = spy
    try:
        # A real meta filename, not a short stand-in: the length invariant
        # below is only meaningful against the names actually written.
        target = str(tmp_path / "sub" / "260909.091017525964-act.yml")
        await base.meta_writer._write_meta_atomic(target, "k: v")
    finally:
        mw.os.replace = orig
    assert seen["dst"] == target
    tmp_base = os.path.basename(seen["src"])
    # Dotfile + .tmp: both shapes are what keep a staging file out of the
    # syncer's upload glob.
    assert tmp_base.startswith(".") and tmp_base.endswith(".tmp")
    # The staging name must never be longer than the file it stages, or a
    # run dir that fits under Windows MAX_PATH fails its staging write while
    # the final path would have been writable (station bug, 2026-09-09:
    # 232-char -act.yml, 270-char temp, FileNotFoundError).
    assert len(tmp_base) <= len(os.path.basename(target))
    assert os.path.dirname(seen["src"]) == os.path.dirname(target)
    assert open(target).read() == "k: v\n"


@pytest.mark.asyncio
async def test_manual_action_diag_swap(tmp_path):
    save_root = str(tmp_path / RunDir.ACTIVE.value)
    diag_root = str(tmp_path / RunDir.DIAG.value)
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action(save_act=True, manual_action=True, run_type="manual")
    await base.write_act(action)
    out_dir = os.path.join(diag_root, str(action.action_output_dir))
    assert os.path.isdir(out_dir)
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_write_exp_and_seq(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action()
    await base.write_exp(action)
    await base.write_seq(action)
    exp_dir = os.path.join(save_root, str(action.get_experiment_dir()))
    seq_dir = os.path.join(save_root, str(action.get_sequence_dir()))
    assert [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")]
    assert [f for f in os.listdir(seq_dir) if f.endswith("-seq.yml")]
    exp_text = open(
        os.path.join(
            exp_dir, [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")][0]
        )
    ).read()
    assert exp_text.startswith("file_type: experiment\n")


def test_conn_keys_md5(tmp_path):
    base = make_base(str(tmp_path))
    native = NativeMetaFileWriter(base)
    base.meta_writer = native  # type: ignore[reportAttributeAccessIssue]
    assert native.dflt_file_conn_key() == UUID("6adf97f83acf6453d4a6a4b1070f3754")
    assert native.new_file_conn_key("abc") == UUID("900150983cd24fb0d6963f7d28e17f72")
