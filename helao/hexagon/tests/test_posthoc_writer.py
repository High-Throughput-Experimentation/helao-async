"""Tests for the post-hoc run-artifact face (``adapters/native/posthoc_writer.py``).

This face replaces a private deployment's forked copy of the write path used by
its offline converters. The fork and the core writers had drifted in 11 places;
this module pins the face's side of each disposition.

**Fixtures here are synthetic.** They are shaped like real HELAO run artifacts
(same directory layout, same field names, same file grammar) but every
identifier -- plate, sample label, machine, sequence and experiment names -- is
invented. The golden-derived *byte* comparison against real converted output
lives in the private deployment's own tests (P6d Step 5 runs it through the
GM-C capture diffs); it cannot live here because this repository is a public
remote.

Three of the dispositions were decided by measurement rather than by reading.
Each measurement is recorded in the docstring of the test that pins it:

- ``test_probe1_*``  -- ``FileInfo`` serialization of ``nosync``.
- ``test_probe4_*``  -- whether a repeat write to one filename is ever
  exercised by the captured converter runs.
- ``test_probe8_*``  -- whether a ``None`` sample label ever reaches a write.
"""

import os
from datetime import datetime
from uuid import UUID

import pytest
import yaml

from helao.core.models.file import FileInfo, HloFileGroup
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.run_dir import RunDir
from helao.core.models.run_use import RunUse
from helao.core.models.sample import SolidSample
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.yml_tools import yml_dumps

from helao.hexagon.adapters.native.posthoc_writer import (
    PostHocRunWriter,
    RepeatWriteError,
    default_save_root,
)

# --------------------------------------------------------------------------
# synthetic fixtures -- invented identifiers, real artifact shape
# --------------------------------------------------------------------------

TS = datetime(2026, 1, 2, 3, 4, 5, 678901)
TS_STAMP = "260102.030405678901"
SEQ_UUID = UUID(int=0x5E0)
EXP_UUID = UUID(int=0xE8B)
ACT_UUID = UUID(int=0xAC7)
LABEL = "demo__solid__99__1"


def _sequence() -> Sequence:
    seq = Sequence(
        sequence_name="batch__demo",
        sequence_label="demo-label",
        sequence_params={"plate_id": 1},
        sequence_timestamp=TS,
        sequence_uuid=SEQ_UUID,
    )
    seq.init_seq()
    return seq


def _experiment(seq: Sequence) -> Experiment:
    exp = Experiment(
        sequence_name=seq.sequence_name,
        sequence_label=seq.sequence_label,
        sequence_params=seq.sequence_params,
        sequence_timestamp=TS,
        sequence_uuid=seq.sequence_uuid,
        sequence_output_dir=seq.sequence_output_dir,
        experiment_name="demo_sub_exp",
        experiment_timestamp=TS,
        experiment_uuid=EXP_UUID,
    )
    exp.init_exp()
    return exp


def _action(exp: Experiment, **overrides) -> Action:
    act = Action(
        orchestrator=MachineModel(server_name="ORCH", machine_name="demo-host"),
        action_name="run_demo",
        run_type="demo",
        run_use=RunUse.data,
        sequence_name=exp.sequence_name,
        sequence_label=exp.sequence_label,
        sequence_timestamp=TS,
        sequence_uuid=exp.sequence_uuid,
        sequence_output_dir=exp.sequence_output_dir,
        experiment_name=exp.experiment_name,
        experiment_timestamp=TS,
        experiment_uuid=exp.experiment_uuid,
        experiment_output_dir=exp.experiment_output_dir,
        action_timestamp=TS,
        action_uuid=ACT_UUID,
        action_abbr="demo",
        orch_submit_order=0,
        action_order=0,
        action_retry=0,
        action_split=0,
        action_server=MachineModel(server_name="DEMO", machine_name="demo-host"),
        action_status=[HloStatus.finished],
        files=[],
        **overrides,
    )
    act.init_act()
    return act


def _sample() -> SolidSample:
    return SolidSample(sample_no=1, plate_id=99, machine_name="demo-host")


@pytest.fixture
def run(tmp_path):
    """A save_root plus a synthetic sequence/experiment/action triple."""
    seq = _sequence()
    exp = _experiment(seq)
    act = _action(exp)
    save_root = str(tmp_path / RunDir.ACTIVE.value)
    return {
        "save_root": save_root,
        "writer": PostHocRunWriter(save_root),
        "seq": seq,
        "exp": exp,
        "act": act,
    }


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# write_file -- grammar, filenum, required params
# --------------------------------------------------------------------------


def test_write_file_produces_header_separator_body_exactly(run):
    """The HLO grammar is header + ``%%\\n`` + payload, with nothing else."""
    act, writer = run["act"], run["writer"]
    payload = '{"t_s": [0.0, 0.5], "signal": [1.0, 2.0]}'
    out = writer.write_file(
        act,
        output_str=payload,
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
        header={"scan_index": 1, "label": "demo"},
        json_data_keys=["t_s", "signal"],
        file_sample_label=LABEL,
    )
    assert _read(out) == "scan_index: 1\nlabel: demo\n%%\n" + payload


def test_write_file_without_header_starts_at_the_separator(run):
    act, writer = run["act"], run["writer"]
    out = writer.write_file(
        act,
        output_str='{"a": 1}',
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    assert _read(out) == '%%\n{"a": 1}'


def test_write_file_lands_under_the_actions_output_dir(run):
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    out = writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    assert os.path.dirname(out) == os.path.join(save_root, str(act.action_output_dir))
    assert os.path.basename(out) == "demo-0.0.0.0__0.hlo"


@pytest.mark.parametrize("filenum", [0, 1, 2])
def test_filenum_is_honoured_verbatim_in_the_generated_filename(run, filenum):
    """Load-bearing: a downstream analysis locates the quantification HLO by
    its filename index (``__2.hlo``). Re-deriving the index from file-connection
    ordering -- which is what the core writer does -- would rename the file and
    break that lookup, so the face takes ``filenum`` from the caller."""
    act, writer = run["act"], run["writer"]
    out = writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=filenum,
        file_group=HloFileGroup.helao_files,
    )
    assert os.path.basename(out) == f"demo-0.0.0.0__{filenum}.hlo"
    assert act.files[-1].file_name == f"demo-0.0.0.0__{filenum}.hlo"


def test_three_filenums_produce_three_distinct_files(run):
    act, writer = run["act"], run["writer"]
    outs = [
        writer.write_file(
            act,
            output_str='{"n": %d}' % n,
            file_type="demo_helao__file",
            filenum=n,
            file_group=HloFileGroup.helao_files,
        )
        for n in (0, 1, 2)
    ]
    assert len({os.path.basename(o) for o in outs}) == 3
    assert _read(outs[2]) == '%%\n{"n": 2}'
    assert [f.file_name for f in act.files] == [os.path.basename(o) for o in outs]


def test_file_group_selects_the_extension(run):
    act, writer = run["act"], run["writer"]
    hlo = writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    csv = writer.write_file(
        act,
        output_str="a,b\n1,2\n",
        file_type="demo_aux__file",
        filenum=1,
        file_group=HloFileGroup.aux_files,
    )
    assert hlo.endswith("__0.hlo")
    assert csv.endswith("__1.csv")


def test_write_file_requires_filenum(run):
    """Divergence 3/2: no defaulted guess. Omitting ``filenum`` is an error."""
    act, writer = run["act"], run["writer"]
    with pytest.raises(TypeError, match="filenum"):
        writer.write_file(
            act,
            output_str="{}",
            file_type="demo_helao__file",
            file_group=HloFileGroup.helao_files,
        )


def test_write_file_requires_file_group(run):
    """Divergence 3: the fork defaulted to helao_files, core to aux_files.
    Neither default survives -- the caller states which it wants."""
    act, writer = run["act"], run["writer"]
    with pytest.raises(TypeError, match="file_group"):
        writer.write_file(
            act,
            output_str="{}",
            file_type="demo_helao__file",
            filenum=0,
        )


def test_explicit_filename_overrides_the_generated_one(run):
    act, writer = run["act"], run["writer"]
    out = writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filename="explicit_name.hlo",
        filenum=7,
        file_group=HloFileGroup.helao_files,
    )
    assert os.path.basename(out) == "explicit_name.hlo"


def test_write_file_is_skipped_when_save_data_is_false(run):
    exp = run["exp"]
    act = _action(exp, save_data=False)
    out = run["writer"].write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    assert out is None
    assert act.files == []


def test_write_file_records_a_fileinfo_on_the_action(run):
    act, writer = run["act"], run["writer"]
    writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=1,
        file_group=HloFileGroup.helao_files,
        json_data_keys=["t_s", "signal"],
        file_sample_label=LABEL,
    )
    (info,) = act.files
    assert info.file_name == "demo-0.0.0.0__1.hlo"
    assert info.file_type == "demo_helao__file"
    assert info.data_keys == ["t_s", "signal"]
    assert info.sample == [LABEL]
    assert info.action_uuid == ACT_UUID
    assert info.run_use == RunUse.data


# --------------------------------------------------------------------------
# probe 4 -- repeat write
# --------------------------------------------------------------------------


def test_probe4_repeat_write_raises_instead_of_appending(run):
    """PROBE 4 (measured 2026-08-08). Scanned all five GM-C golden captures,
    both runs each: 220 action records carrying a ``files`` list, 660 total
    ``files`` entries, 270 ``.hlo`` payloads. Duplicate ``file_name`` within one
    action's ``files`` list -- the fork's repeat-write signature, since it
    appends a ``FileInfo`` on every call -- was found **0 times**, and **0**
    ``.hlo`` bodies carried more than one payload after the separator. Both
    detectors were calibrated against planted fixtures first and did fire on
    them, so the zero is a measurement and not a broken scan.

    Repeat write is therefore never exercised, and the face raises. The fork
    appended ``"\\n" + output_str`` with **no** ``%%`` separator, which makes a
    reader parse two payloads as one body -- silent corruption. If this
    assertion is ever flipped to "reproduce the grammar", the measurement above
    has to be re-run first.
    """
    act, writer = run["act"], run["writer"]
    first = writer.write_file(
        act,
        output_str='{"n": 1}',
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    before = _read(first)
    with pytest.raises(RepeatWriteError) as excinfo:
        writer.write_file(
            act,
            output_str='{"n": 2}',
            file_type="demo_helao__file",
            filenum=0,
            file_group=HloFileGroup.helao_files,
        )
    assert "demo-0.0.0.0__0.hlo" in str(excinfo.value)
    # the first payload must be untouched -- no append, no truncation
    assert _read(first) == before == '%%\n{"n": 1}'
    # and the rejected write must not have been recorded on the action
    assert [f.file_name for f in act.files] == ["demo-0.0.0.0__0.hlo"]


def test_probe4_repeat_write_detection_covers_a_preexisting_file(run, tmp_path):
    """A file left by an earlier run counts as a repeat write too: appending to
    it produces exactly the same corrupted two-payload body."""
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    target_dir = os.path.join(save_root, str(act.action_output_dir))
    os.makedirs(target_dir, exist_ok=True)
    stale = os.path.join(target_dir, "demo-0.0.0.0__0.hlo")
    with open(stale, "w", encoding="utf-8") as f:
        f.write("%%\n{}")
    with pytest.raises(RepeatWriteError):
        writer.write_file(
            act,
            output_str='{"n": 1}',
            file_type="demo_helao__file",
            filenum=0,
            file_group=HloFileGroup.helao_files,
        )
    assert _read(stale) == "%%\n{}"


# --------------------------------------------------------------------------
# track_file
# --------------------------------------------------------------------------


def test_track_file_copies_immediately_and_returns_the_fileinfo(run, tmp_path):
    """Divergence 7: post-hoc composition has no finalizer to relocate a
    queued path later, so the copy happens at call time and
    ``aux_file_paths`` is left empty."""
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    src = tmp_path / "instrument_export.raw"
    src.write_bytes(b"\x00\x01raw-payload\x02")

    info = writer.track_file(
        act,
        src_path=str(src),
        file_type="demo_raw__file",
        samples=[_sample()],
    )

    dest = os.path.join(save_root, str(act.action_output_dir), "instrument_export.raw")
    assert os.path.isfile(dest)
    with open(dest, "rb") as f:
        assert f.read() == b"\x00\x01raw-payload\x02"
    assert isinstance(info, FileInfo)
    assert info.file_name == "instrument_export.raw"
    assert info.file_type == "demo_raw__file"
    assert info.sample == [_sample().get_global_label()]
    assert act.files[-1] is info
    assert act.aux_file_paths == []


def test_track_file_skips_the_copy_when_the_source_is_already_in_place(run):
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    target_dir = os.path.join(save_root, str(act.action_output_dir))
    os.makedirs(target_dir, exist_ok=True)
    src = os.path.join(target_dir, "already_here.raw")
    with open(src, "wb") as f:
        f.write(b"in-place")
    writer.track_file(
        act, src_path=src, file_type="demo_raw__file", samples=[_sample()]
    )
    with open(src, "rb") as f:
        assert f.read() == b"in-place"
    assert act.files[-1].file_name == "already_here.raw"
    assert act.aux_file_paths == []


# --------------------------------------------------------------------------
# probe 8 -- None sample labels
# --------------------------------------------------------------------------


class _UnlabelledSample:
    """A sample whose ``get_global_label()`` yields ``None``."""

    def get_global_label(self):
        return None


def test_probe8_none_sample_labels_are_dropped_but_never_occur(run, tmp_path):
    """PROBE 8 (measured 2026-08-08). Same scan as probe 4: across the five
    GM-C captures (both runs each), 660 ``files`` entries carried **0** null
    entries in their ``sample`` lists. The detector was calibrated on a planted
    null and did fire on it. Core's walrus filter is therefore a no-op guard on
    every path the converters actually take -- adopted for safety, not to fix an
    observed defect.

    Both halves are asserted so the pin fails if either answer flips: with only
    real labels the filter changes nothing (the no-op property), and a ``None``
    label -- were one ever introduced -- is dropped rather than serialized as a
    null that a reader would have to handle.
    """
    act, writer = run["act"], run["writer"]
    src_a = tmp_path / "a.raw"
    src_a.write_bytes(b"a")
    src_b = tmp_path / "b.raw"
    src_b.write_bytes(b"b")
    label = _sample().get_global_label()
    assert label is not None

    # no-op property: nothing is dropped when every label is real
    info_a = writer.track_file(
        act, src_path=str(src_a), file_type="t", samples=[_sample(), _sample()]
    )
    assert info_a.sample == [label, label]

    # guard property: a None label is filtered out, not serialized as null
    info_b = writer.track_file(
        act,
        src_path=str(src_b),
        file_type="t",
        samples=[_sample(), _UnlabelledSample(), _sample()],
    )
    assert info_b.sample == [label, label]
    assert None not in info_b.sample


# --------------------------------------------------------------------------
# probe 1 -- nosync serialization
# --------------------------------------------------------------------------


def test_probe1_nosync_false_is_serialized_not_dropped():
    """PROBE 1 (measured 2026-08-08). ``FileInfo(nosync=False).clean_dict()``
    returns ``{... 'nosync': False}`` -- ``False`` is **serialized**, not
    dropped by the cleaner.

    The plan's framing does not survive that measurement. It assumed the fork
    emits no ``nosync`` key at all because it omits the constructor kwarg; but
    ``FileInfo.nosync`` has a field default of ``False``, so the fork's records
    already carry ``nosync: false``. Corroborated in the captures: all 660
    ``files`` entries across the five GM-C golden captures already contain the
    key, every one of them ``false``.

    The artifact-visible diff from adopting core's formula is therefore not
    "the key appears"; it is confined to records where the computed value
    differs -- ``sync_data`` false on a ``.hlo``. All 110 captured actions have
    ``sync_data: true``, so on these captures the intentional-diff set for
    divergence 1 is **empty**.
    """
    omitted = FileInfo(file_type="t", file_name="x.hlo").clean_dict()
    explicit_false = FileInfo(file_type="t", file_name="x.hlo", nosync=False)
    explicit_true = FileInfo(file_type="t", file_name="x.hlo", nosync=True)

    assert "nosync" in omitted, "cleaner dropped a False nosync"
    assert omitted["nosync"] is False
    # fork-shaped construction and core-shaped False are byte-identical
    assert omitted == explicit_false.clean_dict()
    # ... and the True case is reachable and distinguishable
    assert explicit_true.clean_dict()["nosync"] is True
    assert explicit_true.clean_dict() != omitted


def test_probe1_face_computes_nosync_from_sync_data_and_extension(run):
    """Divergence 1, adopted: ``nosync = (not sync_data) and name.endswith('.hlo')``."""
    exp = run["exp"]
    writer = run["writer"]

    synced = run["act"]
    writer.write_file(
        synced,
        output_str="{}",
        file_type="t",
        filenum=0,
        file_group=HloFileGroup.helao_files,
    )
    assert synced.files[-1].nosync is False

    unsynced = _action(exp, sync_data=False)
    writer.write_file(
        unsynced,
        output_str="{}",
        file_type="t",
        filenum=1,
        file_group=HloFileGroup.helao_files,
    )
    assert unsynced.files[-1].nosync is True

    # aux (.csv) stays syncable even with sync_data off
    writer.write_file(
        unsynced,
        output_str="a,b\n",
        file_type="t",
        filenum=2,
        file_group=HloFileGroup.aux_files,
    )
    assert unsynced.files[-1].nosync is False


# --------------------------------------------------------------------------
# meta writers
# --------------------------------------------------------------------------


def test_write_act_writes_a_parsable_act_yml_and_returns_its_path(run):
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
        file_sample_label=LABEL,
    )
    out = writer.write_act(act)

    assert out == os.path.join(
        save_root, str(act.action_output_dir), f"{TS_STAMP}-act.yml"
    )
    assert os.path.isfile(out)
    text = _read(out)
    assert text.startswith("file_type: action\n")
    assert text.endswith("\n")
    doc = yaml.safe_load(text)
    assert doc["file_type"] == "action"
    assert doc["action_name"] == "run_demo"
    assert doc["action_uuid"] == str(ACT_UUID)
    assert [f["file_name"] for f in doc["files"]] == ["demo-0.0.0.0__0.hlo"]
    assert doc["files"][0]["sample"] == [LABEL]
    assert doc["files"][0]["nosync"] is False


def test_write_act_leaves_no_temp_file_behind(run):
    """Divergence 5: the write goes through a temp file + ``os.replace``."""
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    out = writer.write_act(act)
    leftovers = [n for n in os.listdir(os.path.dirname(out)) if n.endswith(".tmp")]
    assert leftovers == []


def test_meta_writes_swap_a_complete_temp_file_into_place(run, monkeypatch):
    """Divergence 5, asserted at the mechanism rather than at its leftovers.

    The fork opened the destination ``w+`` and wrote through it, so a reader or
    a crash could observe a truncated meta file. Every meta write must instead
    land in a sibling temp file and arrive by a single ``os.replace``.
    """
    act, writer = run["act"], run["writer"]
    calls = []
    real_replace = os.replace

    def spy(src, dst, *a, **kw):
        with open(src, encoding="utf-8") as f:
            calls.append((src, dst, f.read()))
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", spy)
    out = writer.write_act(act)

    assert len(calls) == 1
    src, dst, staged = calls[0]
    assert dst == out
    assert os.path.dirname(src) == os.path.dirname(out)
    assert os.path.basename(src).startswith(".") and src.endswith(".tmp")
    # the temp file was already complete at the moment of the swap
    assert staged.startswith("file_type: action\n")
    assert staged == _read(out)


def test_the_face_works_when_called_from_inside_a_running_loop(run):
    """Half the converters are ``async def`` driven by ``asyncio.run`` in a pool
    worker, so the face is called from inside a running loop as a matter of
    course.

    An earlier version raised here, reasoning that a sync facade over async
    primitives deadlocks. It does -- but only if the coroutine is driven on the
    CALLING loop; a private loop on another thread does not re-enter it. The
    refusal broke every async converter at its first write, which is how it was
    found: the sync converter family captured cleanly while the async one died
    with "produced no sequence".

    Asserts the artifact, not merely the absence of an exception -- a face that
    returned quietly without writing would satisfy a no-raise test.
    """
    import asyncio

    act, writer, save_root = run["act"], run["writer"], run["save_root"]

    async def drive():
        return writer.write_act(act)

    written = asyncio.run(drive())
    assert written is not None
    assert os.path.isfile(written)
    assert os.path.basename(written).endswith("-act.yml")
    assert yaml.safe_load(_read(written))["action_uuid"] == str(act.action_uuid)


def test_the_face_still_works_outside_a_loop(run):
    """The guard on the test above: it would pass just as well if the face had
    stopped caring about loops entirely and broken the ordinary sync path."""
    act2 = _action(run["exp"])
    written = run["writer"].write_act(act2)
    assert written is not None and os.path.isfile(written)


def test_write_act_with_save_act_false_returns_none_without_raising(run):
    """Divergence 10: the fork read an unbound ``output_file`` here and died
    with ``UnboundLocalError``. Nothing is written and ``None`` comes back."""
    exp, writer, save_root = run["exp"], run["writer"], run["save_root"]
    act = _action(exp, save_act=False)
    assert writer.write_act(act) is None
    act_dir = os.path.join(save_root, str(act.action_output_dir))
    written = os.listdir(act_dir) if os.path.isdir(act_dir) else []
    assert [n for n in written if n.endswith("-act.yml")] == []


def test_write_exp_and_write_seq_write_their_own_yml(run):
    writer, save_root = run["writer"], run["save_root"]
    exp, seq = run["exp"], run["seq"]

    exp_out = writer.write_exp(exp)
    seq_out = writer.write_seq(seq)

    assert exp_out == os.path.join(
        save_root, exp.get_experiment_dir(), f"{TS_STAMP}-exp.yml"
    )
    assert seq_out == os.path.join(
        save_root, seq.get_sequence_dir(), f"{TS_STAMP}-seq.yml"
    )
    exp_doc = yaml.safe_load(_read(exp_out))
    seq_doc = yaml.safe_load(_read(seq_out))
    assert _read(exp_out).startswith("file_type: experiment\n")
    assert _read(seq_out).startswith("file_type: sequence\n")
    assert exp_doc["experiment_name"] == "demo_sub_exp"
    assert exp_doc["experiment_uuid"] == str(EXP_UUID)
    assert seq_doc["sequence_name"] == "batch__demo"
    assert seq_doc["sequence_uuid"] == str(SEQ_UUID)


def test_meta_yml_uses_the_indented_block_sequence_style(run):
    """Divergence 6: the fork dumped with ``fast=True``, which emits
    non-indented block sequences. The face adopts core's default dumper. The
    two differ textually but parse identically, which is why the difference
    vanishes downstream."""
    act, writer = run["act"], run["writer"]
    writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
        file_sample_label=LABEL,
    )
    text = _read(writer.write_act(act))
    assert "files:\n  - action_uuid:" in text  # indented (core default)
    assert "\n- " not in text  # no non-indented block sequence anywhere

    payload = yaml.safe_load(text)
    fast_text = yml_dumps(payload, fast=True)
    assert "\n- " in fast_text  # the style the fork emitted
    assert fast_text != text
    assert yaml.safe_load(fast_text) == payload


# --------------------------------------------------------------------------
# manual handling (divergence 9)
# --------------------------------------------------------------------------


def test_manual_true_redirects_every_writer_to_the_diag_tree(run):
    """Divergence 9: the fork took ``manual=`` on exp/seq only and ``write_act``
    had no such parameter at all. The face takes it uniformly on all three."""
    writer, save_root = run["writer"], run["save_root"]
    act, exp, seq = run["act"], run["exp"], run["seq"]

    act_out = writer.write_act(act, manual=True)
    exp_out = writer.write_exp(exp, manual=True)
    seq_out = writer.write_seq(seq, manual=True)

    for out in (act_out, exp_out, seq_out):
        assert RunDir.DIAG.value in out
        assert RunDir.ACTIVE.value not in out
        assert os.path.isfile(out)


def test_manual_false_is_the_converters_case_and_keeps_the_active_tree(run):
    writer = run["writer"]
    out = writer.write_act(run["act"], manual=False)
    assert RunDir.ACTIVE.value in out
    assert RunDir.DIAG.value not in out


def test_an_actions_own_manual_flag_also_redirects(run):
    """Core keys the redirect off ``model.manual_action``; the face honours
    both that and the explicit parameter."""
    writer = run["writer"]
    act = _action(run["exp"], manual_action=True)
    out = writer.write_act(act, manual=False)
    assert RunDir.DIAG.value in out


# --------------------------------------------------------------------------
# default_save_root
# --------------------------------------------------------------------------


def test_default_save_root_derives_from_the_config_root():
    root = os.path.join("demo_root", "INST_hlo")
    assert default_save_root({"root": root}) == os.path.join(
        root, RunDir.FINISHED.value
    )


def test_default_save_root_uses_the_fallback_when_the_config_has_no_root():
    assert default_save_root({}, fallback_root="fb") == os.path.join(
        "fb", RunDir.FINISHED.value
    )
    assert default_save_root(None, fallback_root="fb") == os.path.join(
        "fb", RunDir.FINISHED.value
    )


def test_default_save_root_refuses_to_invent_a_root():
    """No station data-root literal is carried in this repository; a caller
    with neither a config root nor a fallback gets an error, not a guess."""
    with pytest.raises(ValueError, match="root"):
        default_save_root({})


# --------------------------------------------------------------------------
# divergence 11 -- no sys.path surgery
# --------------------------------------------------------------------------


def test_module_does_not_mutate_sys_path():
    """Divergence 11: the fork appended a hardcoded repo path to ``sys.path``
    at import time. The launcher/graft owns ``PYTHONPATH``."""
    import helao.hexagon.adapters.native.posthoc_writer as mod

    assert mod.__file__ is not None
    source = _read(mod.__file__)
    assert "sys.path" not in source
