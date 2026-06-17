"""Helper for resolving HELAO output files across RUNS_* state directories."""

import os
from pathlib import Path
from typing import Union
from zipfile import ZipFile

from .yml_tools import yml_load
from .hlo_data import read_hlo, read_hlo_stream


class FileMapper:
    """Locate and read files within a run tree across its lifecycle states.

    HELAO writes output beneath ``<root>/RUNS_<state>/...`` where ``<state>``
    cycles through ``ACTIVE``, ``FINISHED``, ``SYNCED``, ``DIAG``, and
    ``NOSYNC`` as a run progresses, plus a parallel ``PROCESSES`` tree.
    A :class:`FileMapper` is constructed from any path inside one of those
    trees and exposes ``read_*`` methods that resolve a path relative to
    the ``RUNS_*`` root and try each state directory in turn.

    Attributes:
        inputfile: Absolute path of the input file, or ``None`` if a
            directory was supplied.
        inputdir: Absolute directory containing ``inputfile`` (or the
            input directory itself).
        inputparts: ``inputdir.parts`` as a mutable list, used to splice
            in different ``RUNS_<state>`` names.
        runpos: Index in ``inputparts`` of the ``RUNS_<state>`` or
            ``PROCESSES`` segment.
        prestr: Joined parent path up to (but not including) ``runpos``.
        states: Run-state names tried by :meth:`locate`.
        relstrs: Relative paths (under the ``RUNS_*``/``PROCESSES`` root)
            of all files discovered at or below the input location.
    """

    def __init__(self, save_path: Union[str, Path]):
        """Index every file at or below ``save_path`` across all run states.

        Args:
            save_path: Any path inside a ``RUNS_<state>`` or ``PROCESSES``
                tree; may point to a file or a directory.
        """
        if isinstance(save_path, str):
            save_path = Path(save_path)
        if save_path.is_file():
            self.inputfile = save_path.absolute()
            self.inputdir = self.inputfile.parent
        else:
            self.inputfile = None
            self.inputdir = save_path.absolute()
        self.inputparts = list(self.inputdir.parts)
        self.runpos = [
            i
            for i, v in enumerate(self.inputparts)
            if v.startswith("RUNS_") or v == "PROCESSES"
        ][0]
        self.prestr = os.path.join(*self.inputparts[: self.runpos])

        # list all files at save_path level and deeper, relative to RUNS_*
        self.states = ["ACTIVE", "FINISHED", "SYNCED", "DIAG", "NOSYNC"]
        self.relstrs = []
        for state in self.states:
            stateparts = list(self.inputparts)
            stateparts[self.runpos] = f"RUNS_{state}"
            stateglob = Path(os.path.join(*stateparts)).rglob("*")
            for p in stateglob:
                if p.is_file():
                    self.relstrs.append(os.path.join(*p.parts[self.runpos + 1 :]))
        prcparts = list(self.inputparts)
        prcparts[self.runpos] = "PROCESSES"
        prcglob = Path(os.path.join(*prcparts)).rglob("*")
        for p in prcglob:
            if p.is_file():
                self.relstrs.append(os.path.join(*p.parts[self.runpos + 1 :]))

    def locate(self, p: str):
        """Resolve a run-tree-relative path against each known run state.

        If ``p`` already contains ``"PROCESSES"`` it is returned unchanged.
        Otherwise the method tries ``<prestr>/RUNS_<state>/<p>`` for each
        state in :attr:`states` and returns the first existing path. When no
        loose file is found, it falls back to the synced sequence zip:
        a fully-synced sequence directory is archived to
        ``<prestr>/RUNS_SYNCED/<seq_dir>.zip`` (members stored relative to the
        sequence dir), so ``p``'s first segment names the zip and the
        remainder names the member.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            A :class:`Path` (or ``p`` unchanged for ``PROCESSES`` inputs)
            pointing at an existing loose file; a ``(zip_path, member)`` tuple
            when the file lives inside a synced sequence zip; or ``None`` if it
            cannot be found.
        """
        if "PROCESSES" in p:
            return p
        for state in self.states:
            testp = Path(os.path.join(self.prestr, f"RUNS_{state}", p))
            if testp.exists():
                return testp
        return self._locate_in_zip(p)

    def _locate_in_zip(self, p: str):
        """Locate ``p`` inside the synced sequence zip under ``RUNS_SYNCED``.

        A fully-synced sequence directory (``.../YY.WW/MMDD/<seq_dir>``) is
        archived to ``RUNS_SYNCED/YY.WW/MMDD/<seq_dir>.zip`` with members
        stored relative to the sequence dir. ``p`` is run-state-root-relative,
        so some prefix of it names the sequence dir (hence the zip) and the
        remainder names the member. Each prefix is tried (shortest first)
        until a synced zip that contains the member is found.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            A ``(zip_path, member)`` tuple if a matching synced zip contains
            the member, otherwise ``None``.
        """
        parts = Path(p).parts
        synced_root = os.path.join(self.prestr, "RUNS_SYNCED")
        for i in range(1, len(parts)):
            zip_path = Path(os.path.join(synced_root, *parts[:i]) + ".zip")
            if not zip_path.is_file():
                continue
            member = "/".join(parts[i:])
            with ZipFile(zip_path, "r") as zf:
                if member in zf.namelist():
                    return (zip_path, member)
        return None

    def read_hlo(self, p: str, retries: int = 3):
        """Read an HLO file via :func:`read_hlo`, retrying on partial writes.

        :class:`ValueError` raised by :func:`read_hlo` (typically because
        the underlying file is still being flushed) is caught and the
        read is retried up to ``retries`` times.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.
            retries: Maximum number of retries on :class:`ValueError`.

        Returns:
            The ``(meta, data)`` tuple from :func:`read_hlo`, or ``None``
            if all retries exhaust without raising.

        Raises:
            FileNotFoundError: ``p`` could not be located in any run state.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        elif isinstance(lp, tuple):
            zip_path, member = lp
            with ZipFile(zip_path, "r") as zf:
                with zf.open(member) as f:
                    return read_hlo_stream(f)
        else:
            retry_counter = 0
            read_success = False
            while (not read_success) or (retry_counter <= retries):
                try:
                    hlo_tup = read_hlo(lp.__str__())
                    read_success = True
                    return hlo_tup
                except ValueError:  # retry read_hlo in case file not fully written
                    retry_counter += 1
            return None

    def read_yml(self, p: str) -> dict:
        """Resolve and parse a YAML file from the run tree.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            Parsed YAML contents as a plain dict.

        Raises:
            FileNotFoundError: ``p`` could not be located in any run state.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        elif isinstance(lp, tuple):
            zip_path, member = lp
            with ZipFile(zip_path, "r") as zf:
                content = zf.read(member).replace(b"\x89", b"%").decode("utf-8")
            return dict(yml_load(content))
        else:
            # print(lp)
            return dict(yml_load(Path(lp)))

    def read_lines(self, p: str) -> list:
        """Resolve and read a text file from the run tree, split on newlines.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            One string per line in the file.

        Raises:
            FileNotFoundError: ``p`` could not be located in any run state.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        elif isinstance(lp, tuple):
            zip_path, member = lp
            with ZipFile(zip_path, "r") as zf:
                return zf.read(member).decode().split("\n")
        else:
            lines = lp.read_text().split("\n")
            return lines

    def read_bytes(self, p: str) -> bytes:
        """Resolve and read a binary file from the run tree.

        Reads from a loose file when one exists, or from the synced sequence
        zip when :meth:`locate` resolves ``p`` to a ``(zip_path, member)``
        tuple.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            File contents as raw bytes.

        Raises:
            FileNotFoundError: ``p`` could not be located in any run state.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        elif isinstance(lp, tuple):
            zip_path, member = lp
            with ZipFile(zip_path, "r") as zf:
                return zf.read(member)
        else:
            return lp.read_bytes()
