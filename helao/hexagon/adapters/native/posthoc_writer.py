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
* A repeat write to a filename **raises** (:class:`RepeatWriteError`). The fork
  appended the new payload with no ``%%`` separator, which makes a reader parse
  two payloads as one body.
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
    """Raised when a write targets a filename that already exists.

    The forked writer this face replaces appended ``"\\n" + payload`` to an
    existing file without emitting a ``%%`` separator first, so a reader saw the
    two payloads as a single body -- corruption that surfaces only much later,
    as unexplained values. The captured converter runs never exercised that path
    (see ``test_posthoc_writer.test_probe4_*`` for the measurement), so the face
    refuses the write instead of reproducing the grammar.
    """


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

        Returns:
            The written path, or ``None`` when ``action.save_data`` is false.

        Raises:
            RepeatWriteError: The target filename already exists.
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

        _, _, _, output_file = resolved
        if os.path.exists(output_file):
            raise RepeatWriteError(
                f"refusing to write {filename} twice: {output_file} already "
                "exists. The forked writer appended the second payload with no "
                "'%%' separator, which corrupts the file for any reader."
            )

        return active.data_file_writer.write_file_nowait(
            output_str=output_str,
            file_type=file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

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
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy(path, new_path)

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
