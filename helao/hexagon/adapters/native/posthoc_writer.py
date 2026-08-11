"""Post-hoc run-artifact face (hexagon P6d).

Offline converters -- batch jobs that turn an instrument's exported files into
a HELAO run tree after the fact -- need the same artifact grammar a live action
server writes, but they have no ``Base``, no ``Active``, no orchestrator and no
finalizer. A private deployment had solved this by forking the write path into
its own module, which then drifted from the originals in eleven places.

This module is the replacement face. It composes the native write primitives
(:class:`~helao.hexagon.adapters.native.data_file.NativeDataFileWriter` and
:class:`~helao.hexagon.adapters.native.meta_writer.NativeMetaFileWriter`)
behind a synchronous, ``Active``-free API, so post-hoc callers and the live
runtime emit artifacts through the same code.

Composition: the two native collaborators reach into an ``active``/``base``
back-reference at call time (they cache nothing). :class:`_PostHocBase` and
:class:`_PostHocActive` are the minimum objects satisfying those reach-ins --
a ``save_root``-bearing ``helaodirs`` plus the handful of delegators the legacy
``Base``/``Active`` provide. Nothing else about a server is simulated.

What this face changes relative to the fork it replaces:

* ``filenum`` is a **required** parameter rather than derived from
  file-connection ordering. Post-hoc callers own the file index, and at least
  one downstream analysis locates a file by that index.
* ``file_group`` is **required**. The fork defaulted to ``helao_files`` and the
  core writer to ``aux_files``; neither default is safe to inherit, so the
  caller states which it wants.
* Data files are written **atomically, and always overwrite** -- temp file in
  the same directory plus ``os.replace``. They are never appended to. The fork
  appended the new payload with no ``%%`` separator, which makes a reader parse
  two payloads as one body; this face replaces the target instead.
* Meta ymls are written atomically (temp file + ``os.replace``) with the
  default YAML dumper, matching the core writers.
* ``track_file`` copies at call time -- post-hoc composition has no finalizer to
  relocate a queued path later -- and leaves ``aux_file_paths`` empty.
* ``write_act`` accepts ``manual=`` like the other two writers, and returns
  ``None`` instead of raising when the action has ``save_act`` disabled.

The face is synchronous because its callers are batch scripts; the async native
primitives are driven through :func:`_run_sync`. Those callers are a MIX of
shapes -- some ``make_*_processes`` are plain functions, others are ``async def``
run under ``asyncio.run`` in a pool worker -- so ``_run_sync`` handles both, and
drives the coroutine on a private loop in its own thread when one is already
running rather than re-entering the caller's.
"""

import asyncio
import os
import threading
import shutil
from typing import Any, Optional, Union
from uuid import uuid1

from helao.core.models.file import FileInfo, HloFileGroup
from helao.core.models.run_dir import RunDir
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action, Experiment, Sequence

from .data_file import NativeDataFileWriter
from .meta_writer import NativeMetaFileWriter

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["PostHocRunWriter", "RepeatWriteError", "default_save_root"]

SampleUnion = Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]


class RepeatWriteError(RuntimeError):
    """No longer raised. Retained because it is exported.

    This face used to *refuse* a write whose target already existed, to avoid
    reproducing the forked writer's habit of appending ``"\\n" + payload`` with
    no ``%%`` separator (which makes a reader parse two payloads as one body).

    Refusing turned out to be the wrong remedy. A batch conversion that dies
    partway leaves half-written artifacts under ``RUNS_FINISHED``, and on the
    next attempt every one of them made the converter raise here -- so a single
    interrupted run poisoned the source folder until someone cleaned it by
    hand. The corruption the guard existed to prevent came from *appending*;
    :func:`_atomic_write_text` eliminates it directly by replacing the target,
    which also makes a retry idempotent.

    The name stays exported: ``__all__`` advertises it, and deployments outside
    this repo are separate repositories that this one cannot grep.
    """


def _atomic_write_text(output_file: str, content: str) -> None:
    """Write ``content`` to ``output_file`` atomically, replacing any existing file.

    Same technique as :mod:`meta_writer`: a uniquely-named temp file in the
    *same directory* (so ``os.replace`` stays on one filesystem and is therefore
    atomic), then a rename over the target.

    Two properties matter here, and appending has neither. A reader or a crash
    can never observe a partly-written file -- the rename either happened or it
    did not -- and a rerun after a failed conversion replaces whatever the
    previous attempt left behind instead of growing it. The batch converters
    write each data file exactly once from a single process, so last-writer-wins
    is the whole of the concurrency story.

    Args:
        output_file: Final path to create or replace.
        content: Complete file body.
    """
    output_path = os.path.dirname(output_file)
    os.makedirs(output_path, exist_ok=True)
    tmp_file = os.path.join(
        output_path,
        f".{os.path.basename(output_file)}.{uuid1().hex}.tmp",
    )
    try:
        with open(tmp_file, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_file, output_file)
    except BaseException:
        # Never leave a stray dotfile beside the payload; the next run would
        # have no way to tell it from a real artifact.
        try:
            os.remove(tmp_file)
        except OSError:
            pass
        raise


def _atomic_copy(src_path: "str | os.PathLike[str]", dest_path: str) -> None:
    """Copy ``src_path`` onto ``dest_path`` atomically, replacing any existing file.

    ``shutil.copy`` straight onto the destination truncates it first and then
    streams, so a conversion killed partway leaves a short file that looks like
    a real artifact. Staging beside the destination and renaming means the
    destination is either the previous file or the complete new one.

    Args:
        src_path: File to copy. Accepts ``PathLike`` because
            ``action.aux_file_paths`` carries ``Path`` entries as well as
            strings.
        dest_path: Destination path, created or replaced.
    """
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)
    tmp_path = os.path.join(
        dest_dir, f".{os.path.basename(dest_path)}.{uuid1().hex}.tmp"
    )
    try:
        shutil.copyfile(src_path, tmp_path)
        os.replace(tmp_path, dest_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _run_sync(coro):
    """Drive one coroutine to completion from synchronous code.

    The converters are a MIX of shapes and the face has to serve both: some
    ``make_*_processes`` are plain functions, others are ``async def`` driven by
    ``asyncio.run`` inside a pool worker. An earlier version refused outright
    when a loop was already running, on the reasoning that calling a sync facade
    from async code deadlocks. It does -- but only if the coroutine is driven on
    the *calling* loop. Refusing instead broke every async converter at its
    first write, which is how this was found: bruker (sync) converted while
    xafs (async) raised.

    So a running loop is handled by driving the coroutine on a private loop in
    its own thread and blocking this one until it finishes. Nothing here is
    bound to the caller's loop -- the writers touch plain models and do their
    IO through the default executor -- so the work is loop-agnostic and the
    calling loop is never re-entered.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict = {}

    def _drive() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised on the calling thread below
            result["error"] = exc

    thread = threading.Thread(target=_drive, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class _PostHocHelaoDirs:
    """The single ``helaodirs`` attribute the native writers read."""

    def __init__(self, save_root: str):
        self.save_root = save_root


class _PostHocBase:
    """Minimal stand-in for ``Base``, exposing only what the writers reach for.

    The native meta writer resolves ``self.base.helaodirs.save_root`` and calls
    back through ``self.base._write_meta_atomic`` -- the same indirection the
    legacy ``Base`` delegators provide -- so both are forwarded here.
    """

    def __init__(self, save_root: str):
        self.helaodirs = _PostHocHelaoDirs(save_root)
        self.meta_writer = NativeMetaFileWriter(self)

    async def _write_meta_atomic(self, output_file: str, output_str: str):
        return await self.meta_writer._write_meta_atomic(output_file, output_str)

    async def write_act(self, action: Action):
        return await self.meta_writer.write_act(action)


class _PostHocActive:
    """Minimal stand-in for ``Active`` for a single post-hoc action.

    The native data-file writer cross-calls its own methods through the
    ``Active`` delegators (``write_file_nowait`` -> ``_resolve_output_path`` ->
    ``init_datafile``); those two delegators are all it needs here. No file
    connections exist post-hoc, so ``file_conn_dict`` stays empty and the
    streaming entry points are never reached.
    """

    def __init__(self, base: _PostHocBase, action: Action):
        self.base = base
        self.action = action
        self.action_list = [action]
        self.file_conn_dict: dict = {}
        self.data_file_writer = NativeDataFileWriter(self)

    def init_datafile(self, **kwargs):
        return self.data_file_writer.init_datafile(**kwargs)

    def _resolve_output_path(self, *args):
        return self.data_file_writer._resolve_output_path(*args)


class PostHocRunWriter:
    """Write HELAO run artifacts for an action reconstructed after the fact.

    Args:
        save_root: Root the run tree is written under, e.g.
            ``<config root>/RUNS_FINISHED``. Model-relative output directories
            (``action_output_dir`` and friends) are joined onto it.
    """

    def __init__(self, save_root: str):
        self.save_root = str(save_root)
        #: Data-file paths this writer has already written, used only to tell a
        #: converter bug (same filename twice in one run) apart from the benign
        #: case of replacing debris left by an earlier failed conversion. Both
        #: overwrite; they differ in log level. Per-instance, and the batch jobs
        #: build one writer per conversion, so it does not grow unboundedly.
        self._written: set[str] = set()

    # -- internals ---------------------------------------------------------

    def _root_for(self, model, manual: bool) -> str:
        """Return the save root, redirected to the diagnostic tree if manual."""
        if manual or getattr(model, "manual_action", False):
            return self.save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        return self.save_root

    def _active_for(self, action: Action, manual: bool = False) -> _PostHocActive:
        return _PostHocActive(_PostHocBase(self._root_for(action, manual)), action)

    @staticmethod
    def _generated_filename(
        action: Action, filenum: int, file_group: HloFileGroup
    ) -> str:
        """Build the autogenerated filename for ``filenum``.

        Owned here rather than left to the native writer, which derives the
        index from ``action.file_conn_keys`` -- an ordering a post-hoc caller
        does not have. Format is otherwise identical.
        """
        ext = "hlo" if file_group == HloFileGroup.helao_files else "csv"
        return (
            f"{action.action_abbr}-{action.orch_submit_order}"
            f".{action.action_order}.{action.action_retry}"
            f".{action.action_split}__{filenum}.{ext}"
        )

    # -- data files --------------------------------------------------------

    def write_file(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        *,
        filenum: int,
        file_group: HloFileGroup,
        header: Any = None,
        json_data_keys: Optional[list[str]] = None,
        file_sample_label: Optional[Union[list[str], str]] = None,
        sample_str: Optional[str] = None,
    ) -> Optional[str]:
        """Write one complete data file and record it on ``action``.

        The file is ``header`` (if any) + ``%%\\n`` + ``output_str``, and a
        matching ``FileInfo`` is appended to ``action.files``.

        Args:
            action: Action the file belongs to; must already be ``init_act``-ed.
            output_str: File body, typically an encoded payload.
            file_type: HELAO file-type tag recorded on the ``FileInfo``.
            filename: Explicit filename. Autogenerated from ``filenum`` when
                omitted.
            filenum: File index for the generated name. Required -- see the
                module docstring.
            file_group: Selects ``.hlo`` (helao) or ``.csv`` (aux). Required.
            header: Header content as a dict, list of lines, string or ``None``.
            json_data_keys: Column keys recorded on the ``FileInfo``.
            file_sample_label: Sample global label(s) for the file.
            sample_str: Accepted for signature parity with the core writer,
                which does not use it either.

        The write is atomic and **always replaces** the target: a leftover file
        from a conversion that died partway is overwritten, never appended to.
        See :func:`_atomic_write_text`.

        Returns:
            The written path, or ``None`` when ``action.save_data`` is false.
        """
        if filename is None:
            filename = self._generated_filename(action, filenum, file_group)

        active = self._active_for(action)
        resolved = active._resolve_output_path(
            file_type,
            filename,
            file_group,
            header,
            file_sample_label,
            json_data_keys,
            action,
        )
        if resolved is None:
            LOGGER.info(
                f"save_data is disabled for action '{action.action_name}'; "
                f"skipping {filename}"
            )
            return None

        resolved_header, file_info, _, output_file = resolved

        # Two different situations reach an existing target, and only one of
        # them is benign. A file this writer has not written during this run is
        # debris from an earlier, failed attempt -- expected on a retry, and the
        # whole reason this overwrites. A file it *has* already written means a
        # converter is emitting the same filename twice in one run and the first
        # payload is being discarded, which is a bug in the converter.
        if output_file in self._written:
            LOGGER.warning(
                f"{filename} written twice in one run for action "
                f"'{action.action_name}' ({output_file}); the earlier payload is "
                "being discarded. This is a converter bug -- each data file "
                "should be written once."
            )
        elif os.path.exists(output_file):
            LOGGER.info(
                f"replacing pre-existing {output_file} (leftover from an earlier "
                "conversion attempt)"
            )

        body = (
            f"{resolved_header}%%\n{output_str}"
            if resolved_header
            else f"%%\n{output_str}"
        )
        _atomic_write_text(output_file, body)
        self._written.add(output_file)

        # Recorded only after the bytes are in place, so a failed write cannot
        # leave a FileInfo advertising a file that is not there.
        action.files.append(file_info)
        LOGGER.info(f"wrote non stream data to: {output_file}")
        return output_file

    def track_file(
        self,
        action: Action,
        src_path: str,
        file_type: str,
        samples: list[SampleUnion],
    ) -> FileInfo:
        """Record an existing file on ``action`` and copy it in immediately.

        Unlike the live path, which queues the source for the finalizer to
        relocate at action end, this copies at call time: a post-hoc caller has
        no finalizer, so a queued path would simply never be moved.
        ``action.aux_file_paths`` is left as it was found.

        The copy is atomic and replaces any existing destination, for the same
        reason the data-file write is: a conversion killed mid-copy would
        otherwise leave a truncated artifact that the next attempt has no way to
        recognise as incomplete.

        Args:
            action: Action to attach the file to.
            src_path: Path to the existing file; only its basename is recorded.
            file_type: HELAO file-type tag recorded on the ``FileInfo``.
            samples: Samples whose global labels are recorded on the
                ``FileInfo``. Samples with no label are skipped.

        Returns:
            The ``FileInfo`` appended to ``action.files``.
        """
        active = self._active_for(action)
        queued_before = list(action.aux_file_paths)
        _run_sync(
            active.data_file_writer.track_file(
                file_type=file_type,
                file_path=src_path,
                samples=samples,
                action=action,
            )
        )
        queued = [p for p in action.aux_file_paths if p not in queued_before]
        action.aux_file_paths = queued_before

        dest_dir = os.path.join(
            self._root_for(action, False), str(action.action_output_dir)
        )
        for path in queued:
            new_path = os.path.join(dest_dir, os.path.basename(path))
            if path != new_path:
                _atomic_copy(path, new_path)

        return action.files[-1]

    # -- meta files --------------------------------------------------------

    def write_act(self, action: Action, manual: bool = False) -> Optional[str]:
        """Write the action's ``-act.yml``.

        Args:
            action: Action to persist.
            manual: Write into the diagnostic tree instead of the active one.

        Returns:
            The written path, or ``None`` when ``action.save_act`` is false.
        """
        if not action.save_act:
            LOGGER.info(
                f"writing meta file for action '{action.action_name}' is disabled."
            )
            return None
        base = _PostHocBase(self._root_for(action, manual))
        _run_sync(base.meta_writer.write_act(action))
        return self._act_path(action, manual)

    def write_exp(self, experiment: Experiment, manual: bool = False) -> str:
        """Write the experiment's ``-exp.yml`` and return its path."""
        base = _PostHocBase(self._root_for(experiment, manual))
        _run_sync(base.meta_writer.write_exp(experiment))
        return self._exp_path(experiment, manual)

    def write_seq(self, sequence: Sequence, manual: bool = False) -> str:
        """Write the sequence's ``-seq.yml`` and return its path."""
        base = _PostHocBase(self._root_for(sequence, manual))
        _run_sync(base.meta_writer.write_seq(sequence))
        return self._seq_path(sequence, manual)

    @staticmethod
    def _stamp(timestamp, init_call: str) -> str:
        """Format a model timestamp, or say which initializer was skipped.

        A model that never had its ``init_*`` called carries ``None`` here and
        has no output directory either, so the write would land somewhere
        arbitrary; naming the missing call is more useful than an
        ``AttributeError`` from inside the formatter.
        """
        if timestamp is None:
            raise ValueError(
                f"model has no timestamp; call {init_call} before writing it."
            )
        return timestamp.strftime("%y%m%d.%H%M%S%f")

    def _act_path(self, action: Action, manual: bool) -> str:
        stamp = self._stamp(action.action_timestamp, "init_act()")
        return os.path.join(
            self._root_for(action, manual),
            str(action.action_output_dir),
            f"{stamp}-act.yml",
        )

    def _exp_path(self, experiment: Experiment, manual: bool) -> str:
        stamp = self._stamp(experiment.experiment_timestamp, "init_exp()")
        return os.path.join(
            self._root_for(experiment, manual),
            experiment.get_experiment_dir(),
            f"{stamp}-exp.yml",
        )

    def _seq_path(self, sequence: Sequence, manual: bool) -> str:
        stamp = self._stamp(sequence.sequence_timestamp, "init_seq()")
        return os.path.join(
            self._root_for(sequence, manual),
            sequence.get_sequence_dir(),
            f"{stamp}-seq.yml",
        )


def default_save_root(cfg: Optional[dict], fallback_root: Optional[str] = None) -> str:
    """Resolve the default run-output root (``<root>/RUNS_FINISHED``).

    Args:
        cfg: Loaded instrument config, or ``None``. Only its ``root`` key is
            read.
        fallback_root: Root to use when ``cfg`` carries none. Callers that need
            a legacy literal pass it here; this repository ships no station
            data-root path of its own.

    Returns:
        ``<root>/RUNS_FINISHED``.

    Raises:
        ValueError: Neither a config root nor a fallback was supplied.
    """
    root = cfg.get("root") if isinstance(cfg, dict) else None
    root = root or fallback_root
    if not root:
        raise ValueError(
            "no save root: the config carries no 'root' key and no "
            "fallback_root was supplied."
        )
    return os.path.join(str(root), RunDir.FINISHED.value)
