"""Native record-metadata writer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``MetaFileWriter`` collaborator
(``helao/core/servers/base_meta_writer.py``): the atomic
temp-file-then-``os.replace`` write, the three ``write_act``/``write_exp``/
``write_seq`` writers (``file_type`` first key, pretty JSON or an in-flight
YAML rewrite, trailing newline, manual runs resolved to the ``DIAG`` tree), and the file-connection-key
helpers. Method bodies were byte-identical to the legacy engine
(source-parity-pinned by ``test_native_meta_writer.py``) when B7b deleted it;
black left them unchanged.

Holds only the ``base`` back-reference and reads ``helaodirs`` etc. through
it at call time (cache-nothing rule). ``ActionHost`` constructs it as its
``meta_writer`` (``NativeArtifactStoreAdapter.meta_writer_for``).
"""

# The three latent Optional-narrowing diagnostics below (join()/strftime() on
# a nominally-Optional experiment/sequence/action timestamp or output dir)
# are pre-existing in the legacy body this module re-bodies verbatim
# (confirmed: `pyright helao/core/servers/base_meta_writer.py` reports the
# same 5 errors on the unmodified legacy file). The bodies were pinned
# byte-identical to legacy until B7b deleted that pin; the diagnostics stay
# suppressed at file scope rather than fixed in the bodies.
# pyright: reportCallIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false

import os
from typing import Optional
from uuid import UUID

import aiofiles

from helao.core.models.hlostatus import HloStatus
from helao.core.models.run_dir import redirect_manual_dir
from helao.helpers import helao_logging as logging
from helao.helpers.artifact_hash import log_artifact_hashes
from helao.helpers.file_utils import replace_when_free, staging_path
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.meta_io import dumps_meta, resolve_meta_path
from helao.hexagon.domain.naming import (
    DATA_SUFFIX,
    HEADER_SUFFIX,
    data_sibling,
    new_file_conn_key,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeMetaFileWriter", "TERMINAL_STATUSES"]

TERMINAL_STATUSES = frozenset(
    {
        HloStatus.finished,
        HloStatus.errored,
        HloStatus.aborted,
        HloStatus.skipped,
        HloStatus.estopped,
        HloStatus.retired,
    }
)


def _terminal(statuses) -> bool:
    return any(s in TERMINAL_STATUSES for s in (statuses or []))


def _event(reason):
    return "artifact_rewritten" if reason else "artifact_final"


def _action_files(output_path: str, action) -> list:
    """Every file in ``action.files`` plus the ``.meta.json`` header of a data file."""
    paths = []
    for f in action.files or []:
        if not f.file_name:
            continue
        p = os.path.join(output_path, f.file_name)
        paths.append(p)
        if p.endswith(DATA_SUFFIX):
            header = data_sibling(p, HEADER_SUFFIX)
            if os.path.exists(header):
                paths.append(header)
    return paths


class NativeMetaFileWriter:
    """Native drop-in for ``base.meta_writer`` (legacy surface, native body).

    Holds only the ``base`` back-reference (never cached path/dir state),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, base):
        self.base = base

    async def _write_meta_atomic(self, output_file: str, output_str: str):
        """Atomically write ``output_str`` to ``output_file``.

        Meta writers (``write_act``/``write_exp``/``write_seq``) can be driven
        concurrently for the same file -- e.g. a driver polling loop and the
        action loop both reaching ``finish()``, or a manual action's ``myinit``
        racing its ``finish_manual_action``. A plain ``"w+"`` truncate-then-write
        from two coroutines interleaves at the same offset and yields a torn
        meta file (e.g. a partially copied ``samples_in`` block), and a reader
        (syncer/move_dir) or a crash mid-write can also observe a truncated
        file. Writing to a unique temp file in the same directory and
        ``os.replace()``-ing it in makes the swap atomic: readers only ever see
        a complete file and the last writer wins cleanly.
        """
        if not output_str.endswith("\n"):
            output_str += "\n"
        output_path = os.path.dirname(output_file)
        os.makedirs(output_path, exist_ok=True)
        tmp_file = staging_path(output_file)
        async with aiofiles.open(tmp_file, mode="w", encoding="utf-8") as f:
            await f.write(output_str)
        await replace_when_free(tmp_file, output_file)

    async def write_act(self, action: Action, reason: Optional[str] = None):
        """Write ``<output_dir>/<timestamp>-act.json`` (or the existing ``-act.yml`` it rewrites in place) if ``save_act``.

        Args:
            action: ``Action`` whose metadata should be persisted.
            reason: Marks a post-finalize rewrite (logged as ``artifact_rewritten``).
        """
        if action.save_act:
            act_dict = action.get_act().clean_dict()
            save_root = str(self.base.helaodirs.save_root)
            if action.manual_action:
                save_root = redirect_manual_dir(save_root)
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(
                output_path,
                f"{action.action_timestamp.strftime('%y%m%d.%H%M%S%f')}-act.json",
            )

            LOGGER.info(f"writing to act meta file: {output_path}")

            output_dict = {"file_type": "action"}
            output_dict.update(act_dict)
            target = resolve_meta_path(output_file)
            await self.base._write_meta_atomic(
                str(target), dumps_meta(output_dict, target)
            )
            if _terminal(action.action_status):
                await log_artifact_hashes(
                    [target],
                    kind="act",
                    owner_uuid=action.action_uuid,
                    event=_event(reason),
                    reason=reason,
                )
                await log_artifact_hashes(
                    _action_files(output_path, action),
                    kind="data",
                    owner_uuid=action.action_uuid,
                    event=_event(reason),
                    reason=reason,
                )
        else:
            LOGGER.info(
                f"writing meta file for action '{action.action_name}' is disabled."
            )

    async def write_exp(self, experiment: Experiment, reason: Optional[str] = None):
        """Write ``<experiment_dir>/<timestamp>-exp.json`` (or the existing ``-exp.yml`` it rewrites in place).

        Args:
            experiment: ``Experiment`` whose metadata should be persisted.
        """
        exp_dict = experiment.get_exp().clean_dict()
        save_root = str(self.base.helaodirs.save_root)
        if experiment.manual_action:
            save_root = redirect_manual_dir(save_root)
        output_path = os.path.join(save_root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%y%m%d.%H%M%S%f')}-exp.json",
        )

        LOGGER.info(f"writing to exp meta file: {output_file}")
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        target = resolve_meta_path(output_file)
        await self.base._write_meta_atomic(str(target), dumps_meta(output_dict, target))
        if _terminal(experiment.experiment_status):
            await log_artifact_hashes(
                [target],
                kind="exp",
                owner_uuid=experiment.experiment_uuid,
                event=_event(reason),
                reason=reason,
            )

    async def write_seq(self, sequence: Sequence, reason: Optional[str] = None):
        """Write ``<sequence_dir>/<timestamp>-seq.json`` (or the existing ``-seq.yml`` it rewrites in place).

        Args:
            sequence: ``Sequence`` whose metadata should be persisted.
        """
        seq_dict = sequence.get_seq().clean_dict()
        sequence_dir = sequence.get_sequence_dir()
        save_root = str(self.base.helaodirs.save_root)
        if sequence.manual_action:
            save_root = redirect_manual_dir(save_root)
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%y%m%d.%H%M%S%f')}-seq.json",
        )

        LOGGER.info(f"writing to seq meta file: {output_file}")
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        target = resolve_meta_path(output_file)
        await self.base._write_meta_atomic(str(target), dumps_meta(output_dict, target))
        if _terminal(sequence.sequence_status):
            await log_artifact_hashes(
                [target],
                kind="seq",
                owner_uuid=sequence.sequence_uuid,
                event=_event(reason),
                reason=reason,
            )

    def new_file_conn_key(self, key: str) -> UUID:
        """Return a UUID derived from the MD5 hash of ``key``.

        Args:
            key: Arbitrary string used to seed the hash.
        """
        return new_file_conn_key(key)

    def dflt_file_conn_key(self) -> UUID:
        """Return the default file-connection key (``md5(str(None))``)."""
        return self.base.new_file_conn_key(str(None))
