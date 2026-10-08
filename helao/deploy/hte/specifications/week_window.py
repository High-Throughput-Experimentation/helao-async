"""Shared week-windowed sequence specification parser.

Implements a :class:`BaseParser` that the orchestrator uses to surface
recent sequence runs for re-running with overridden parameters. Two layouts
are listed: the single ``RUNS`` tree (``%Y/%m%d/<seqdir>/``, unzipped) and the
legacy ``RUNS_SYNCED`` tree (``%y.%U/**/*.zip``).
"""

import glob
import inspect
import os
from datetime import datetime, timedelta

from helao.helpers import helao_logging as logging
from helao.helpers.helao_data import HelaoData
from helao.helpers.sequence_constructor import constructor
from helao.helpers.specification_parser import BaseParser

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class WeekWindowSpecParser(BaseParser):
    """Lister/parser for sequences collected over the last ``WEEKS`` weeks."""

    WEEKS: int = 2

    def __init__(self):
        """Declare the parameter-name to type map exposed to the operator UI."""
        self.PARAM_TYPES = {
            "plate_id": int,
            "plate_sample_no": int,
            "plate_sample_no_list": list,
        }

    def lister(self, folderpath: str) -> list:
        """Return up to 50 recent non-manual sequences from ``folderpath``.

        Lists sequence directories under ``folderpath/%Y/%m%d/`` for each day
        of the last ``WEEKS`` weeks (the ``RUNS`` tree), then sequence zips
        under ``folderpath/%y.%U/**`` (the legacy ``RUNS_SYNCED`` tree), and
        excludes ``__manual_orch_seq__`` paths.

        Args:
            folderpath: A ``RUNS`` root or a legacy ``RUNS_SYNCED`` root.

        Returns:
            List of up to 50 sequence directory or zip paths, newest-first.
        """
        now = datetime.now()
        specfiles = []
        for i in range(self.WEEKS * 7):
            day = (now - timedelta(days=i)).strftime("%Y/%m%d")
            seqymls = glob.glob(os.path.join(folderpath, day, "*", "*-seq.yml"))
            specfiles += sorted({os.path.dirname(p) for p in seqymls}, reverse=True)
        for i in range(self.WEEKS):
            # %U (Sunday-start) is what get_sequence_dir wrote; %W was a week off.
            yearweek = (now - timedelta(weeks=i)).strftime("%y.%U")
            specfiles += sorted(
                glob.glob(
                    os.path.join(folderpath, yearweek, "**", "*.zip"),
                    recursive=True,
                ),
                reverse=True,
            )
        # filter manual experiments
        specfiles = [x for x in specfiles if "__manual_orch_seq__" not in x]
        latest_50 = specfiles[:50]
        return latest_50

    def list_params(self, specfile: str, orch) -> dict:
        """Return the argument-name to annotation map for the spec's sequence.

        Args:
            specfile: Path to the sequence zip file.
            orch: Orchestrator whose ``sequence_lib`` is used to look
                up the sequence function.

        Returns:
            Mapping of argument name to annotation (or
            ``"unspecified"``), or ``{}`` if the sequence is missing.
        """
        zdat = HelaoData(specfile)
        zyml = zdat.yml
        seqname = zyml["sequence_name"]
        if seqname not in orch.sequence_lib:
            LOGGER.warning(
                f"sequence '{seqname}' not found in current sequence library"
            )
            return {}
        seqfunc = orch.sequence_lib[seqname]
        argspec = inspect.getfullargspec(seqfunc)
        tmpargs = list(argspec.args)
        tmptypes = [argspec.annotations.get(k, "unspecified") for k in list(tmpargs)]
        return {k: v for k, v in zip(tmpargs, tmptypes)}

    def parser(self, specfile: str, orch, params: dict = {}, **kwargs):
        """Build a new sequence from a spec zip, optionally overriding params.

        Args:
            specfile: Path to the sequence zip file.
            orch: Orchestrator providing sequence lib/codehash/codepath.
            params: Optional overrides merged on top of the saved
                sequence params.
            **kwargs: Ignored extra arguments.

        Returns:
            A freshly constructed sequence ready for enqueueing.
        """
        zdat = HelaoData(specfile)
        zyml = zdat.yml
        loaded_params = zyml["sequence_params"]
        loaded_params.update(params)
        seqname = zyml["sequence_name"]
        seqfunc = orch.sequence_lib[seqname]
        newseq = constructor(seqfunc, loaded_params)
        newseq.sequence_codehash = orch.sequence_codehash_lib[seqname]
        newseq.sequence_codepath = orch.sequence_codepath_lib[seqname]
        newseq.sequence_funcname = orch.sequence_codehash_lib[seqname].__name__
        newseq.sequence_label = "synced-seq-params"
        return newseq
