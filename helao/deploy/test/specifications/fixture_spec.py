"""A minimal ``SpecParser`` so Q10's *declaring* branch runs on Linux.

The operator's Specs tab is opt-in: a station either configures a
``seqspec_parser_path`` or it does not, and ``spec_parser.load_parser``
degrades every failure to "nothing configured" because a deployment's parser is
code this repo never sees. That degrade path makes two very different states
look identical at the instrument -- *no parser configured* and *the configured
parser is broken* both render the same note.

A **gate** does not have that ambiguity, because it holds the config. So the
lane asserts the branch the config selects: omit the key and the note must be
present; declare it and the tab must list specs and carry no note. Running the
declaring branch needs a parser, and every real one belongs to a deployment
with hardware behind it (``hte``'s four all read zipped sequence runs from a
station's synced tree). This is the smallest thing that satisfies the contract
so both branches run with no hardware:

* ``lister(folder)``     -- the ``.json`` files in the folder
* ``PARAM_TYPES``        -- every parameter this parser understands
* ``list_params(...)``   -- the ones a given file uses
* ``parser(...)``        -- build a ``Sequence``

Deliberately **not** a stub that returns canned values: ``lister`` really
globs, ``list_params`` really reads the file, and ``parser`` really builds a
sequence through the same ``constructor`` the shipped parsers use. A fixture
that faked those would let the Specs tab pass the gate while the seam that
carries a real parser was broken.
"""

__all__ = ["SpecParser"]

import glob
import inspect
import json
import os

from helao.helpers.sequence_constructor import constructor
from helao.helpers.specification_parser import BaseParser


class SpecParser(BaseParser):
    """Reads a one-file JSON specification: a sequence name and its params."""

    def __init__(self):
        """Declare the parameters the operator may override."""
        # Matched to `TEST_seq.TEST_consecutive_noblocking`'s real signature,
        # so an override entered in the UI reaches a real parameter rather than
        # a made-up one. `spec_fields` prompts only for the *intersection* of
        # this map with what `list_params` reports, so a name that is not on
        # the sequence would render no field and the tab would look correct
        # while asking for nothing.
        self.PARAM_TYPES = {
            "wait_time": float,
            "cycles": int,
            "plate_sample_no_list": list,
        }

    def lister(self, folderpath: str, limit: int = 50) -> list:
        """Specification files in *folderpath*, newest name first.

        ``limit`` is part of ``BaseParser``'s signature and is honoured rather
        than dropped: ``hte``'s shipped parsers truncate too, and a fixture
        that silently ignored the parameter would be a subclass the base
        contract does not describe.
        """
        found = sorted(glob.glob(os.path.join(folderpath, "*.json")), reverse=True)
        return found[:limit]

    def _load(self, specfile: str) -> dict:
        with open(specfile, encoding="utf-8") as handle:
            return json.load(handle)

    def list_params(self, specfile: str, orch) -> dict:
        """Parameter names to annotations for the sequence this file names.

        Returns ``{}`` when the sequence is not in the running library, the
        same way the shipped parsers do -- the Specs tab then prompts for
        nothing rather than for parameters that go nowhere.
        """
        spec = self._load(specfile)
        name = spec.get("sequence_name", "")
        library = getattr(orch, "sequence_lib", {}) or {}
        if name not in library:
            return {}
        argspec = inspect.getfullargspec(library[name])
        return {
            arg: argspec.annotations.get(arg, "unspecified") for arg in argspec.args
        }

    def parser(self, specfile: str, orch, params: dict = {}, **kwargs):
        """Build the sequence this file describes, with *params* applied."""
        spec = self._load(specfile)
        name = spec["sequence_name"]
        merged = dict(spec.get("sequence_params") or {})
        merged.update(params or {})
        sequence = constructor(orch.sequence_lib[name], merged)
        sequence.sequence_label = "fixture-spec"
        return sequence
