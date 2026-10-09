"""Helper for resolving HELAO output files in the RUNS tree or a legacy archive."""

import os
from pathlib import Path
from typing import Union
from zipfile import ZipFile

from helao.core.models.run_dir import RunDir, is_legacy_path, is_run_root

from .hlo_data import read_hlo_bytes
from .yml_tools import yml_load


class FileMapper:
    """Locate and read files within a run tree, new layout or legacy archive.

    HELAO now writes every record once, beneath ``<root>/RUNS/...``, and never
    moves it, so a new-layout path has exactly **one** candidate and no search
    is needed. Archives written before the cut-over are never migrated
    (spec §7): they live under ``<root>/RUNS_<state>/`` with ``<state>``
    cycling through ``ACTIVE``, ``FINISHED``, ``SYNCED``, ``DIAG`` and
    ``NOSYNC``, optionally with the sequence directory zipped away, and are
    resolved by trying each state root in turn exactly as before. Both eras
    also have a parallel ``PROCESSES`` mirror.

    The legacy day directory is *not* one shape: the week level is ``%y.%U``
    throughout, but the day level is ``YYYYMMDD`` in the early era and ``MMDD``
    later, and both sit side by side in one archive. Nothing here parses it --
    the run-root segment alone distinguishes the layouts, which is why no
    heuristic on the week/day shape is needed.

    Attributes:
        inputfile: Absolute path of the input file, or ``None`` if a
            directory was supplied.
        inputdir: Absolute directory containing ``inputfile`` (or the
            input directory itself).
        inputparts: ``inputdir.parts`` as a mutable list, used to splice
            in different run-root names.
        is_legacy: Whether the input sits under a pre-cut-over run tree.
        runpos: Index in ``inputparts`` of the run-root segment. The **last**
            such segment, because a superseded record is archived as a whole
            nested legacy tree (``RUNS_SUPERSEDED/<ts>/RUNS_FINISHED/...``)
            and only the inner root anchors its contents.
        prestr: Joined parent path up to (but not including) ``runpos``.
        states: Legacy run-state names, retained for the archive read path.
        roots: Run-root directory names :meth:`locate` tries, in order. One
            entry for a new-layout path; every legacy state for an archive.
        relstrs: Relative paths (under the run root) of all files discovered
            at or below the input location. **OS-native separators**, not
            forward-slash: they are built with :func:`os.path.join` below.
            Spec §9's forward-slash rule covers paths that are *stored* --
            ymls, journal records, RPC payloads, S3 keys -- and these are
            purely in-memory, never written or transmitted. A consumer that
            splits one must therefore not assume ``"/"``; normalize, or use
            :func:`os.path.dirname` and friends, which accept both.
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
        self.is_legacy = is_legacy_path(self.inputdir)
        # The LAST run root, not the first: a superseded record is archived as
        # a whole nested legacy tree, so an outer RUNS_SUPERSEDED segment is
        # part of the prefix and only the inner root anchors the contents.
        self.runpos = [i for i, v in enumerate(self.inputparts) if is_run_root(v)][-1]
        self.prestr = os.path.join(*self.inputparts[: self.runpos])

        self.states = ["ACTIVE", "FINISHED", "SYNCED", "DIAG", "NOSYNC"]
        if self.is_legacy:
            self.roots = [f"RUNS_{state}" for state in self.states]
        else:
            # One record, one place. The input's own root is the only
            # candidate -- and it is what survives a PROCESSES_SUPERSEDED
            # path, which matches none of the names spliced in below.
            self.roots = [self.inputparts[self.runpos]]
        if "PROCESSES" not in self.roots:
            self.roots.append("PROCESSES")  # the parallel process mirror

        # list all files at save_path level and deeper, relative to the run root
        self.relstrs = []
        for root in self.roots:
            rootparts = list(self.inputparts)
            rootparts[self.runpos] = root
            for p in Path(os.path.join(*rootparts)).rglob("*"):
                if p.is_file():
                    self.relstrs.append(os.path.join(*p.parts[self.runpos + 1 :]))

    def locate(self, p: str):
        """Resolve a run-tree-relative path against each known run state.

        If ``p`` already contains ``"PROCESSES"`` it is returned unchanged.
        Otherwise the method tries ``<prestr>/<root>/<p>`` for each root in
        :attr:`roots` and returns the first existing path -- a single
        candidate for a new-layout record, every legacy state for an archive.
        For an archive, when no loose file is found it falls back to the
        synced sequence zip:
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
        # ``.hlo`` data files are recorded in metadata under their canonical
        # ``.hlo.json`` (S3/JSON) name, but the local/zip artifact is the raw
        # ``.hlo``. Try the name as given, then fall back to the physical name.
        candidates = [p]
        if p.endswith(".hlo.json"):
            candidates.append(p[: -len(".json")])
        for cand in candidates:
            for root in self.roots:
                testp = Path(os.path.join(self.prestr, root, cand))
                if testp.exists():
                    return testp
            # Only archives were ever zipped, and only they need the search.
            if self.is_legacy:
                zip_hit = self._locate_in_zip(cand)
                if zip_hit is not None:
                    return zip_hit
        return None

    def _locate_in_zip(self, p: str):
        """Locate ``p`` inside the synced sequence zip under ``RUNS_SYNCED``.

        A fully-synced sequence directory (``.../YY.WW/MMDD/<seq_dir>``) is
        archived to ``RUNS_SYNCED/YY.WW/MMDD/<seq_dir>.zip``. ``p`` is
        run-state-root-relative, so some prefix of it names the sequence dir
        (hence the zip) and the remainder names the member. Each prefix is
        tried (shortest first) until a synced zip that contains the member is
        found.

        Two archive conventions are handled, differing in how member names
        are stored:

        * ``sync_driver`` zips store members **relative to the sequence dir**
          (``<exp>/<act>/<file>``).
        * MicroOrch ``zip_runs`` zips store each member as its path **relative
          to the run-state root** — either ``<seq_dir>/<exp>/<act>/<file>`` or
          the full ``YY.WW/MMDD/<seq_dir>/...`` depending on how the run was
          rooted.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.

        Returns:
            A ``(zip_path, member)`` tuple if a matching synced zip contains
            the member, otherwise ``None``.
        """
        parts = Path(p).parts
        synced_root = os.path.join(self.prestr, RunDir.SYNCED.value)
        for i in range(1, len(parts)):
            zip_path = Path(os.path.join(synced_root, *parts[:i]) + ".zip")
            if not zip_path.is_file():
                continue
            # candidate member names, by archive convention:
            #   parts[i:]    - stored relative to the sequence dir (sync_driver)
            #   parts[i-1:]  - includes the sequence dir (MicroOrch, seq-rooted)
            #   parts[:]     - full run-relative path (MicroOrch, run-rooted)
            candidates = [
                "/".join(parts[i:]),
                "/".join(parts[i - 1 :]),
                "/".join(parts),
            ]
            with ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
            for member in candidates:
                if member and member in names:
                    return (zip_path, member)
        return None

    def read_hlo(self, p: str, retries: int = 3):
        """Resolve and read an HLO file as ``(meta, data)``, retrying partial writes.

        The file is located via :meth:`locate` (run-state dirs and synced
        sequence zips) and its bytes pulled with :meth:`read_bytes`, so loose
        files and zip members are handled uniformly; the bytes are then parsed
        by :func:`read_hlo_bytes`. :class:`ValueError` from the parser
        (typically a not-yet-flushed file) triggers up to ``retries`` re-reads.

        Args:
            p: Path relative to the ``RUNS_<state>`` root.
            retries: Maximum number of retries on :class:`ValueError`.

        Returns:
            The ``(meta, data)`` tuple, or ``None`` if every attempt raises
            :class:`ValueError`.

        Raises:
            FileNotFoundError: ``p`` could not be located in any run state.
        """
        for _ in range(retries + 1):
            try:
                return read_hlo_bytes(self.read_bytes(p))
            except ValueError:  # retry in case file not fully written
                continue
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
            lines = lp.read_text(encoding="utf-8").split("\n")
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
