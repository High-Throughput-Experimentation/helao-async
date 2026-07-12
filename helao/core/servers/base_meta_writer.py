"""Meta-file-writer collaborator extracted from ``Base`` (CARDS P6, Stage S3).

``Base``'s action/experiment/sequence meta-yml output -- the atomic-write
helper and the three ``write_act``/``write_exp``/``write_seq`` writers, plus
the file-connection-key helpers they (and other ``Base``/``Active`` code)
depend on -- is moved here into a ``MetaFileWriter`` collaborator that
``Base`` delegates to. This follows the ``LiveBuffer`` (S1) /
``StatusBroadcaster`` (S2) pattern exactly.

Methods relocated (bodies byte-identical to the original inline ``Base``
methods, with ``self.`` rewritten to ``self.base.``):

- ``_write_meta_atomic`` -- atomic temp-file-then-``os.replace`` write used by
  all three meta writers below.
- ``write_act`` / ``write_exp`` / ``write_seq`` -- persist
  ``Action``/``Experiment``/``Sequence`` metadata to a timestamped
  ``-act.yml``/``-exp.yml``/``-seq.yml`` file under the run's output dir.
- ``new_file_conn_key`` -- MD5-derived UUID for a given key string.
- ``dflt_file_conn_key`` -- the default file-connection key
  (``new_file_conn_key(str(None))``); this is the heaviest reach-in surface
  (34 call sites), so the ``Base`` delegator forwards to it exactly.

State stays on ``Base`` (rule 3, same as ``LiveBuffer``/``StatusBroadcaster``):
``helaodirs`` and all other file-path state remain attributes of ``Base``,
constructed exactly where they are today in ``Base.__init__``.
``MetaFileWriter`` caches none of it -- it holds only the ``base``
back-reference and reads those attributes through it at call time.

Note: ``Active`` has its own, distinct ``write_file``/``write_file_nowait``
data-file writers -- those stay on ``Active`` (a later P6 stage) and are
untouched by this module.
"""

import hashlib
import os
from uuid import UUID, uuid1

import aiofiles

from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.yml_tools import yml_dumps
from helao.core.models.run_dir import RunDir

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class MetaFileWriter:
    """Action/experiment/sequence meta-yml writer methods for a ``Base``.

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
