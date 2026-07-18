"""Native meta-yml writer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``MetaFileWriter`` collaborator
(``helao/core/servers/base_meta_writer.py``): the atomic
temp-file-then-``os.replace`` write, the three ``write_act``/``write_exp``/
``write_seq`` writers (``file_type`` first key, trailing newline,
RUNS_ACTIVE->RUNS_DIAG swap for manual), and the file-connection-key
helpers. Method bodies are byte-identical to legacy (source-parity-pinned by
``test_native_meta_writer.py``); only this docstring, the class name, and
``__all__`` differ.

Holds only the ``base`` back-reference and reads ``helaodirs`` etc. through
it at call time (cache-nothing rule). Installed per-Base by
``helao.hexagon.app.active_graft.graft_active_write_path`` as a drop-in for
``base.meta_writer`` -- the ``Base`` delegators (``base.py:666-716``) resolve
``self.meta_writer`` at call time, so the swap reroutes ``write_act``/
``write_exp``/``write_seq``/``_write_meta_atomic``/``new_file_conn_key``/
``dflt_file_conn_key`` in one assignment.
"""

# The three latent Optional-narrowing diagnostics below (join()/strftime() on
# a nominally-Optional experiment/sequence/action timestamp or output dir)
# are pre-existing in the legacy body this module re-bodies verbatim
# (confirmed: `pyright helao/core/servers/base_meta_writer.py` reports the
# same 5 errors on the unmodified legacy file). Source-parity pins the method
# bodies byte-identical to legacy, so they cannot be touched here; suppressed
# at file scope instead of inline to avoid perturbing `inspect.getsource`.
# pyright: reportCallIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false

import hashlib
import os
from uuid import UUID, uuid1

import aiofiles

from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.yml_tools import yml_dumps
from helao.core.models.run_dir import RunDir

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeMetaFileWriter"]


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
        tmp_file = os.path.join(
            output_path,
            f".{os.path.basename(output_file)}.{uuid1().hex}.tmp",
        )
        async with aiofiles.open(tmp_file, mode="w") as f:
            await f.write(output_str)
        os.replace(tmp_file, output_file)

    async def write_act(self, action: Action):
        """Write the action's metadata to ``<output_dir>/<timestamp>-act.yml`` if ``save_act``.

        Args:
            action: ``Action`` whose metadata should be persisted.
        """
        if action.save_act:
            act_dict = action.get_act().clean_dict()
            save_root = str(self.base.helaodirs.save_root)
            if action.manual_action:
                save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(
                output_path,
                f"{action.action_timestamp.strftime('%y%m%d.%H%M%S%f')}-act.yml",
            )

            LOGGER.info(f"writing to act meta file: {output_path}")

            output_dict = {"file_type": "action"}
            output_dict.update(act_dict)
            await self.base._write_meta_atomic(output_file, yml_dumps(output_dict))
        else:
            LOGGER.info(
                f"writing meta file for action '{action.action_name}' is disabled."
            )

    async def write_exp(self, experiment: Experiment):
        """Write the experiment's metadata to ``<experiment_dir>/<timestamp>-exp.yml``.

        Args:
            experiment: ``Experiment`` whose metadata should be persisted.
        """
        exp_dict = experiment.get_exp().clean_dict()
        save_root = str(self.base.helaodirs.save_root)
        if experiment.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        output_path = os.path.join(save_root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%y%m%d.%H%M%S%f')}-exp.yml",
        )

        LOGGER.info(f"writing to exp meta file: {output_file}")
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        await self.base._write_meta_atomic(output_file, yml_dumps(output_dict))

    async def write_seq(self, sequence: Sequence):
        """Write the sequence's metadata to ``<sequence_dir>/<timestamp>-seq.yml``.

        Args:
            sequence: ``Sequence`` whose metadata should be persisted.
        """
        seq_dict = sequence.get_seq().clean_dict()
        sequence_dir = sequence.get_sequence_dir()
        save_root = str(self.base.helaodirs.save_root)
        if sequence.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%y%m%d.%H%M%S%f')}-seq.yml",
        )

        LOGGER.info(f"writing to seq meta file: {output_file}")
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        await self.base._write_meta_atomic(output_file, yml_dumps(output_dict))

    def new_file_conn_key(self, key: str) -> UUID:
        """Return a UUID derived from the MD5 hash of ``key``.

        Args:
            key: Arbitrary string used to seed the hash.
        """
        # return shortuuid.decode(key)
        # Instansiate new md5_hash
        md5_hash = hashlib.md5()
        # Pass the_string to the md5_hash as bytes
        md5_hash.update(key.encode("utf-8"))
        # Generate the hex md5 hash of all the read bytes
        the_md5_hex_str = md5_hash.hexdigest()
        # Return a String repersenation of the uuid of the md5 hash
        return UUID(the_md5_hex_str)

    def dflt_file_conn_key(self) -> UUID:
        """Return the default file-connection key (``md5(str(None))``)."""
        return self.base.new_file_conn_key(str(None))
