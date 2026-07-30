"""Data-file-writer collaborator extracted from ``Active`` (CARDS P6, Stage S5).

``Active``'s data-file initialization and file-I/O helpers -- the action-meta
refresh, the HLO/aux header + ``FileInfo`` builder, the streamed-file opener,
the one-shot file writers, and the auxiliary-file trackers/relocators -- are
moved here into a ``DataFileWriter`` collaborator that ``Active`` delegates to.
This is the FIRST ``Active`` decomposition and establishes the *per-Active*
collaborator pattern reused by later P6 stages (S6-S8).

Unlike the ``Base`` collaborators (``LiveBuffer``/``StatusBroadcaster``/
``MetaFileWriter``, which are held on ``Base`` and back-ref ``self.base``), an
``Active`` collaborator is per-action: it holds the ``Active`` instance as its
back-reference and reads ``self.active.<attr>`` / ``self.active.base.<attr>`` at
call time. Rationale: structurally identical to the shipped S1-S4 pattern
(collaborator-holds-back-ref, delegator-forwards-without-threading-args), and
``Active`` is already a short-lived per-action object so the extra ref is
negligible. This resolves plan open-question OQ-P6-1 in favor of
pattern-consistency + simpler delegators.

Methods relocated (bodies byte-identical to the original inline ``Active``
methods, with ``self.`` rewritten to ``self.active.``):

- ``update_act_file`` -- rewrite the action's ``-act.yml`` to current state.
- ``init_datafile`` -- build the header string + ``FileInfo`` for a new file.
- ``finish_hlo_header`` -- stamp ``epoch_ns`` on each file connection's header.
- ``log_data_set_output_file`` -- open the streamed HLO file and write header.
- ``_resolve_output_path`` -- resolve write params for a one-shot file.
- ``write_file`` / ``write_file_nowait`` -- write one complete file (async/sync).
- ``track_file`` -- record an aux file and queue it for relocation.
- ``relocate_files`` -- copy tracked aux files into the action's output dir.

State stays on ``Active`` (rule 3, same as the ``Base`` collaborators):
``file_conn_dict``, ``action``, ``action_list``, ``base``, and all file-path
state remain ``Active`` attributes, constructed exactly where they are today.
``DataFileWriter`` caches none of it -- it holds only the ``active``
back-reference and reads those attributes through it at call time. Cross-calls
between moved methods (e.g. ``write_file`` -> ``_resolve_output_path`` ->
``init_datafile``) route back through the ``Active`` delegators.

``myinit`` stays on ``Active`` (external lifecycle entry, ``base.py`` calls
``await active.myinit()`` right after construction); it drives the file-init
helpers here via the ``Active`` delegators.
"""

import os
import pathlib
from typing import Optional, Union
from uuid import UUID

import aiofiles

from helao.core.models.file import FileInfo, HloFileGroup
from helao.core.models.run_dir import RunDir
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.helpers import async_copy
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action
from helao.helpers.yml_tools import yml_dumps

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class DataFileWriter:
    """Data-file init + file-I/O methods for an ``Active``.

    Holds only the ``active`` back-reference (never cached path/conn state),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, active):
        self.active = active

    async def update_act_file(self):
        """Rewrite the action's meta YAML to reflect the current state."""
        await self.active.base.write_act(self.active.action)

    def init_datafile(
        self,
        header,
        file_type,
        json_data_keys,
        file_sample_label,
        filename,
        file_group: HloFileGroup,
        file_conn_key: Optional[str] = None,
        action: Optional[Action] = None,
    ) -> tuple:
        """Build the file header string and ``FileInfo`` record for a new data file.

        Args:
            header: Header content as a dict, list of lines, string, or ``None``.
            file_type: HELAO file-type label stored on the ``FileInfo``.
            json_data_keys: Column keys for the file's data payload.
            file_sample_label: Sample label(s) recorded on the ``FileInfo``.
            filename: Output filename; auto-generated if ``None``.
            file_group: Selects ``.hlo`` (helao group) or ``.csv`` (aux group).
            file_conn_key: File-connection key used for filename ordering.
            action: Action associated with the file (defaults to ``self.active.action``).

        Returns:
            ``(header_str, FileInfo)`` ready for use by the data writer.
        """
        filenum = 0
        if action is None:
            action = self.active.action
        if action is not None:
            if file_conn_key in action.file_conn_keys:
                filenum = action.file_conn_keys.index(file_conn_key)
        if isinstance(header, dict):
            # {} is "{}\n" if not filtered
            if header:
                header = yml_dumps(header)
            else:
                header = ""
        elif isinstance(header, list):
            if header:
                header = "\n".join(header) + "\n"
            else:
                header = ""
        elif header is None:
            header = ""

        if json_data_keys is None:
            json_data_keys = []

        # determine ending of file
        if file_group == HloFileGroup.helao_files:
            file_ext = "hlo"
        else:  # aux_files
            file_ext = "csv"

        if filename is None:  # generate filename
            filename = f"{action.action_abbr}-{action.orch_submit_order}.{action.action_order}.{action.action_retry}.{action.action_split}__{filenum}.{file_ext}"

        if file_sample_label is None:
            file_sample_label = []
        if not isinstance(file_sample_label, list):
            file_sample_label = [file_sample_label]

        file_info = FileInfo(
            file_type=file_type,
            file_name=filename,
            data_keys=json_data_keys,
            sample=file_sample_label,
            action_uuid=action.action_uuid,
            run_use=action.run_use,
            nosync=(
                True if not action.sync_data and filename.endswith(".hlo") else False
            ),
        )

        if header:
            if not header.endswith("\n"):
                header += "\n"

        return header, file_info

    def finish_hlo_header(
        self,
        file_conn_keys: Optional[list[UUID]] = None,
        realtime: Optional[int] = None,
    ):
        """Stamp ``epoch_ns`` on each file connection's HLO header if not already set.

        Args:
            file_conn_keys: Specific connection keys to update; defaults to every
                file connection across ``self.active.action_list``.
            realtime: Epoch nanoseconds to stamp; defaults to the current
                NTP-corrected time.
        """
        # needs to be a sync function
        if realtime is None:
            realtime = self.active.get_realtime_nowait()

        if file_conn_keys is None:
            # get all fileconn_keys
            file_conn_keys = []
            for action in self.active.action_list:
                for filekey in action.file_conn_keys:
                    file_conn_keys.append(filekey)

        for file_conn_key in file_conn_keys:
            if (
                self.active.file_conn_dict[file_conn_key].params.hloheader.epoch_ns
                is None
            ):
                self.active.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = (
                    realtime
                )

    async def log_data_set_output_file(self, file_conn_key: UUID):
        """Open the HLO output file for ``file_conn_key`` and write its header.

        Args:
            file_conn_key: Connection key identifying the target file slot.
        """

        LOGGER.info(f"creating file for file conn: {file_conn_key}")

        # get the action for the file_conn_key
        output_action = self.active._get_action_for_file_conn_key(
            file_conn_key=file_conn_key
        )

        if output_action is None:
            LOGGER.error("data LOGGER could not find action for file_conn_key")
            return

        # add some missing information to the hloheader
        if output_action.action_abbr is not None:
            self.active.file_conn_dict[file_conn_key].params.hloheader.action_name = (
                output_action.action_abbr
            )
        else:
            self.active.file_conn_dict[file_conn_key].params.hloheader.action_name = (
                output_action.action_name
            )

        self.active.file_conn_dict[file_conn_key].params.hloheader.column_headings = (
            self.active.file_conn_dict[file_conn_key].params.json_data_keys
        )
        # epoch_ns should have been set already
        # else we need to add it now because the header is now written
        # before data can be added to the file
        if self.active.file_conn_dict[file_conn_key].params.hloheader.epoch_ns is None:
            LOGGER.debug("realtime_ns was not set, adding it now.")
            self.active.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = (
                await self.active.get_realtime()
            )

        header, file_info = self.active.init_datafile(
            header=self.active.file_conn_dict[
                file_conn_key
            ].params.hloheader.clean_dict(),
            file_type=self.active.file_conn_dict[file_conn_key].params.file_type,
            json_data_keys=self.active.file_conn_dict[
                file_conn_key
            ].params.json_data_keys,
            file_sample_label=self.active.file_conn_dict[
                file_conn_key
            ].params.sample_global_labels,
            filename=None,  # always autogen a filename
            file_group=self.active.file_conn_dict[file_conn_key].params.file_group,
            file_conn_key=file_conn_key,
            action=output_action,
        )
        output_action.files.append(file_info)
        filename = file_info.file_name
        save_root = str(self.active.base.helaodirs.save_root)
        if self.active.action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        output_path = os.path.join(save_root, output_action.action_output_dir)
        output_file = os.path.join(output_path, filename)

        os.makedirs(output_path, exist_ok=True)

        LOGGER.info(f"writing data to: {output_file}")
        # create output file and set connection. Open with truncation ("w+")
        # rather than append: this is the one-time creation of a fresh log
        # file (filenames encode retry/split so there is no legitimate
        # same-path append), and appending to any stale bytes left by a crash
        # or re-run would push a spurious separator/header ahead of the real
        # header and corrupt the .hlo layout.
        self.active.file_conn_dict[file_conn_key].file = await aiofiles.open(
            output_file, mode="w+"
        )

        if header:
            LOGGER.debug("adding header to new file")
            if not header.endswith("\n"):
                header += "\n"
            await self.active.file_conn_dict[file_conn_key].file.write(header)

    def _resolve_output_path(
        self,
        file_type: str,
        filename: Optional[str],
        file_group: HloFileGroup,
        header: Optional[str],
        file_sample_label,
        json_data_keys,
        action: Action,
    ):
        """Resolve write parameters for a one-shot output file.

        Returns ``(header, file_info, output_path, output_file)`` when
        ``action.save_data`` is True, otherwise ``None``. Used by both
        :meth:`write_file` and :meth:`write_file_nowait`.
        """
        if not action.save_data:
            return None
        header, file_info = self.active.init_datafile(
            header=header,
            file_type=file_type,
            json_data_keys=json_data_keys,
            file_sample_label=file_sample_label,
            filename=filename,
            file_group=file_group,
        )
        save_root = str(self.active.base.helaodirs.save_root)
        if action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        output_path = os.path.join(save_root, action.action_output_dir)
        output_file = os.path.join(output_path, file_info.file_name)
        if os.name == "nt":
            output_file = str(pathlib.PureWindowsPath(output_file))
        elif os.name == "posix":
            output_file = str(
                pathlib.PurePosixPath(pathlib.PureWindowsPath(output_file))
            ).strip("\\")
        else:
            LOGGER.info("could not detect OS, path seps may be mixed")
        os.makedirs(output_path, exist_ok=True)
        return header, file_info, output_path, output_file

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[list[str] | str] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file asynchronously and return its path, or ``None`` if save is disabled."""
        if action is None:
            action = self.active.action
        result = self.active._resolve_output_path(
            file_type,
            filename,
            file_group,
            header,
            file_sample_label,
            json_data_keys,
            action,
        )
        if result is None:
            return None
        header, file_info, output_path, output_file = result
        action.files.append(file_info)
        LOGGER.info(f"writing non stream data to: {output_file}")
        async with aiofiles.open(output_file, mode="a+") as f:
            if header:
                await f.write(header)
            await f.write("%%\n")
            await f.write(output_str)
        return output_file

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[list[str] | str] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file synchronously and return its path, or ``None`` if save is disabled."""
        if action is None:
            action = self.active.action
        result = self.active._resolve_output_path(
            file_type,
            filename,
            file_group,
            header,
            file_sample_label,
            json_data_keys,
            action,
        )
        if result is None:
            return None
        header, file_info, output_path, output_file = result
        LOGGER.info(f"writing non stream data to: {output_file}")
        with open(output_file, mode="a+") as f:
            if header:
                f.write(header)
            f.write("%%\n")
            f.write(output_str)
        action.files.append(file_info)
        return output_file

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ],
        action: Optional[Action] = None,
    ) -> None:
        """Record an auxiliary file on the action and queue it for relocation if needed.

        Args:
            file_type: HELAO file-type label stored on the ``FileInfo``.
            file_path: Path to the existing file.
            samples: Samples associated with the file (used to build labels).
            action: Target action; defaults to ``self.active.action``.
        """
        if action is None:
            action = self.active.action
        save_root = str(self.active.base.helaodirs.save_root)
        if action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        if os.path.dirname(file_path) != os.path.join(
            save_root, action.action_output_dir
        ):
            action.aux_file_paths.append(file_path)

        file_info = FileInfo(
            file_type=file_type,
            file_name=os.path.basename(file_path),
            # data_keys = json_data_keys,
            sample=[
                label
                for sample in samples
                if (label := sample.get_global_label()) is not None
            ],
            action_uuid=action.action_uuid,
            run_use=action.run_use,
        )

        action.files.append(file_info)
        LOGGER.info(f"{file_info.file_name} added to files_technique / aux_files list.")

    async def relocate_files(self):
        """Copy any tracked auxiliary file paths into the action's output directory."""
        save_root = str(self.active.base.helaodirs.save_root)
        if self.active.action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        for x in self.active.action.aux_file_paths:
            new_path = os.path.join(
                save_root,
                self.active.action.action_output_dir,
                os.path.basename(x),
            )
            if x != new_path:
                await async_copy(x, new_path)
