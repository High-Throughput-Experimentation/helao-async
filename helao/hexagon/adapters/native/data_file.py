"""Native data-file writer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``DataFileWriter`` collaborator
(``helao/core/servers/active_data_file.py``): action-meta refresh, data/aux
header + ``FileInfo`` builder, the streamed-file opener (``w+``
truncate-on-create; a ``helao_files`` header goes to ``X.meta.json``), the
one-shot writers (``helao_files``: header file overwritten + rows appended to
``X.jsonl``; ``aux_files``: ``a+``, header + ``%%\\n`` + payload), FileInfo
appended at write, ``save_data`` gate, the
nt/posix ``_resolve_output_path`` quirk (incl. ``.strip("\\\\")`` -- byte-copied,
not "fixed"), and the aux-file trackers/relocators. Method bodies were
byte-identical to the legacy engine (source-parity-pinned by
``test_native_data_file.py``) when B7b deleted it; black left them
unchanged.

Per-Active collaborator: holds only the ``active`` back-reference and reads
``file_conn_dict``/``action``/``action_list``/``base`` at call time
(cache-nothing rule). ``ActionSession`` constructs it as its
``data_file_writer`` (``NativeArtifactStoreAdapter.collaborators_for``).
"""

# The Optional-narrowing / join-overload diagnostics below (action attrs
# accessed through a nominally-Optional `action`, `os.path.join` on an
# Optional `Path`, a `str` appended to a `list[Path]`) are pre-existing in
# the legacy body this module re-bodies verbatim (confirmed: `pyright
# helao/core/servers/active_data_file.py` reports the same rule-types on the
# unmodified legacy file). The bodies were pinned byte-identical to legacy
# until B7b deleted that pin; the diagnostics stay suppressed at file scope
# rather than fixed in the bodies.
# pyright: reportOptionalMemberAccess=false, reportCallIssue=false, reportArgumentType=false

import os
import pathlib
from typing import Optional, Union
from uuid import UUID

import aiofiles

from helao.core.models.file import FileInfo, HloFileGroup
from helao.core.models.run_dir import redirect_manual_dir
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.helpers import helao_logging as logging
from helao.helpers.file_utils import _relative_file_name
from helao.helpers.premodels import Action
from helao.helpers.meta_io import write_meta
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import HEADER_SUFFIX, data_sibling, is_nosync_file
from helao.hexagon.ports.action_session import ActionSessionPort

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _header_dict(text: str) -> dict:
    """A str data header as a dict: the YAML mapping it spells, else ``{"text": ...}``.

    Pre-JSON callers handed a ``yml_dumps`` string; reading it back keeps the
    S3 ``meta`` they produced unchanged.
    """
    if not text.strip():
        return {}
    try:
        parsed = yml_load(text, fast=True)
    except Exception:
        parsed = None
    return dict(parsed) if isinstance(parsed, dict) else {"text": text}


def _rows(output_str: str) -> str:
    """A one-shot body as ``.jsonl`` rows: newline-terminated, empty stays empty."""
    return (
        output_str if not output_str or output_str.endswith("\n") else output_str + "\n"
    )


__all__ = ["NativeDataFileWriter"]


class NativeDataFileWriter:
    """Native drop-in for ``active.data_file_writer`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached path/conn state),
    per the call-time state resolution rule -- see module docstring.

    The back-reference is declared at class level rather than annotated on the
    ``__init__`` parameter: until B7b deleted the engine, ``__init__`` was
    byte-pinned against its legacy twin, and an annotation in the signature
    would have changed ``inspect.getsource(__init__)`` and broken the pin. A
    class-level annotation gives static checking without touching the method
    source.
    """

    active: ActionSessionPort

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
            file_group: Selects ``.jsonl`` (helao group) or ``.csv`` (aux group).
            file_conn_key: File-connection key used for filename ordering.
            action: Action associated with the file (defaults to ``self.active.action``).

        Returns:
            ``(header, FileInfo)``: a dict for ``helao_files`` (empty means no
            header file), header text for ``aux_files``.
        """
        filenum = 0
        if action is None:
            action = self.active.action
        if action is not None:
            if file_conn_key in action.file_conn_keys:
                filenum = action.file_conn_keys.index(file_conn_key)
        if file_group == HloFileGroup.helao_files:
            # A data header is always a dict, written as X.meta.json (spec §1).
            if isinstance(header, list):
                header = {"text": "\n".join(header)} if header else {}
            elif isinstance(header, str):
                header = _header_dict(header)
            elif header is None:
                header = {}
        elif isinstance(header, dict):
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
            file_ext = "jsonl"
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
            nosync=is_nosync_file(filename, action.sync_data),
        )

        if isinstance(header, str) and header and not header.endswith("\n"):
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
            save_root = redirect_manual_dir(save_root)
        output_path = os.path.join(save_root, output_action.action_output_dir)
        output_file = os.path.join(output_path, filename)

        os.makedirs(output_path, exist_ok=True)
        if isinstance(header, dict):
            # helao_files: the header is its own file, X.meta.json, written
            # atomically before the rows file exists. No header, no file.
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            header = ""

        LOGGER.info(f"writing data to: {output_file}")
        # create output file and set connection. Open with truncation ("w+")
        # rather than append: this is the one-time creation of a fresh log
        # file (filenames encode retry/split so there is no legitimate
        # same-path append), and appending to any stale bytes left by a crash
        # or re-run would push stale bytes ahead of the first row.
        self.active.file_conn_dict[file_conn_key].file = await aiofiles.open(
            output_file, mode="w+", encoding="utf-8"
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
        header,
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
            save_root = redirect_manual_dir(save_root)
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
        # The file's own directory, not just the record root: a record-relative
        # file_name may name a subdirectory, and opening into one that does
        # not exist fails with FileNotFoundError.
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        return header, file_info, output_path, output_file

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header=None,
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
        if isinstance(header, dict):
            # helao_files: header overwritten atomically, rows appended (spec §2).
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            async with aiofiles.open(output_file, mode="a+", encoding="utf-8") as f:
                await f.write(_rows(output_str))
            return output_file
        async with aiofiles.open(output_file, mode="a+", encoding="utf-8") as f:
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
        header=None,
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
        if isinstance(header, dict):
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            with open(output_file, mode="a+", encoding="utf-8") as f:
                f.write(_rows(output_str))
        else:
            with open(output_file, mode="a+", encoding="utf-8") as f:
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
        """Record an auxiliary file on the action.

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
            save_root = redirect_manual_dir(save_root)
        record_dir = os.path.join(save_root, action.action_output_dir)

        file_info = FileInfo(
            file_type=file_type,
            file_name=_relative_file_name(file_path, record_dir),
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
