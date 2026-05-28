"""Base parser scaffolding for turning external spec files into sequences."""

import os
import glob

# import inspect

# from .sequence_constructor import constructor
from .premodels import Sequence


class BaseParser:
    """Base class providing the parser interface for spec-driven sequences.

    Subclasses extend :meth:`lister`, :meth:`list_params`, and :meth:`parser`
    to support a specific external specification format.

    Attributes:
        PARAM_TYPES: Mapping of well-known parameter names to expected types.
    """

    def __init__(self):
        self.PARAM_TYPES = {
            "plate_id": int,
            "plate_sample_no": int,
            "plate_sample_no_list": list,
        }

    def lister(self, folderpath: str, limit: int = 50) -> list:
        """Return up to ``limit`` sorted spec file paths under ``folderpath``.

        Args:
            folderpath: Directory to scan for spec files.
            limit: Maximum number of paths to return.

        Returns:
            Sorted list of spec file paths, truncated to ``limit``.
        """
        specfiles = []
        specfiles = sorted(glob.glob(os.path.join(folderpath, "*")))
        limited = specfiles[:limit]
        return limited

    def list_params(self, specfile: str, orch) -> dict:
        """Return a ``{param_name: type}`` mapping for the given spec file.

        Args:
            specfile: Path to the spec file under consideration.
            orch: Running orchestrator providing sequence library lookups.

        Returns:
            Dict mapping parameter name to declared annotation; empty by default.
        """
        tmpargs = []
        tmptypes = []
        return {k: v for k, v in zip(tmpargs, tmptypes)}

    def parser(specfile: str, orch, params: dict = {}, **kwargs) -> Sequence:
        """Build a :class:`Sequence` from a spec file and parameter overrides.

        Args:
            specfile: Path to the spec file to parse.
            orch: Running orchestrator with sequence library access.
            params: Parameter overrides to merge into the constructed sequence.
            **kwargs: Subclass-specific extras.

        Returns:
            Newly constructed :class:`Sequence` (empty by default).
        """
        return Sequence()
