"""Spec-parser port (P7h; Q8 -- fs *and* arbitrary code execution).

Mirrors ``helao/ui/shared/operator/spec_parser.py``. This is the heaviest
boundary of the four P7h ports and the only one that is not merely I/O:
``load_parser`` runs ``spec.loader.exec_module`` on a file named by a config
key (``spec_parser.py:67``). It is a **plugin loader**. The parser is a
deployment's own code, in a repo this one never sees, and it is executed inside
the operator process.

That is why the port's contract is a *degrade* contract rather than a result
contract:

* **Nothing here raises through the seam.** Unset path, missing file, a module
  that throws while importing, a module with no ``SpecParser``, a
  ``SpecParser`` whose constructor fails -- all five are ``None`` from
  :meth:`load_parser`. A broken parser must disable the Specs tab, not take
  down the operator page.
* **:meth:`build_spec_sequence` is the one exception, and it reports rather
  than raises.** It returns ``(sequence, error)``, exactly one of which is
  meaningful, because the spec file is the operator's own input and "it did
  nothing" is unactionable at a station.
* **Absence and brokenness are indistinguishable from inside.** Every failure
  above logs and yields the same empty value, so no caller can tell "no parser
  configured" from "the configured parser is broken". This is deliberate at
  runtime -- an instrument has no way to know which was meant -- and it is
  precisely why Q10 puts the gate-side answer in P7j, where a *config* is held
  and can distinguish the two.

The parser object itself is opaque (``object``): its type is deployment code,
and its contract -- ``.lister``, ``.PARAM_TYPES``, ``.list_params``,
``.parser`` -- is exercised only inside the shared module, never here. Ports
may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82), so the
``Sequence`` that :meth:`build_spec_sequence` produces stays inside the
returned ``tuple`` unnamed.

The concrete face is ``adapters/vis/spec_parser.py`` -- under ``adapters/vis/``
because ``adapters/native/`` may not import ``helao.core.servers.*``
(test_boundaries.py:131-143).
"""

from typing import Protocol, runtime_checkable

__all__ = ["SpecParserPort"]


@runtime_checkable
class SpecParserPort(Protocol):
    """Structural mirror of the ``spec_parser`` module's public functions."""

    def load_parser(self, parser_path) -> object:
        """Load a deployment's ``SpecParser``, or ``None`` for any failure.

        Executes ``parser_path``. The returned object is opaque here: only the
        shared module calls into it.
        """
        ...

    def clear_parser_cache(self) -> None:
        """Drop the loaded-module cache.

        The cache exists because loading a parser *runs* it: without it, every
        operator tab would re-run a deployment's import side effects. Clearing
        is for tests that write a new parser to the same path.
        """
        ...

    def spec_files(self, parser, folder) -> list:
        """Specification files ``parser`` finds in ``folder``; ``[]`` on any
        failure, including no parser and no such folder."""
        ...

    def spec_fields(self, parser, spec_file: str, backend) -> list:
        """Describe the parameters one specification file needs.

        Only the intersection of the parser's declared ``PARAM_TYPES`` and the
        ones ``list_params`` says this file uses -- prompting for the rest
        would demand values the spec has no use for. Fields carry no default.
        """
        ...

    def build_spec_sequence(
        self, parser, spec_file: str, backend, params: dict, kwargs: dict
    ) -> tuple:
        """Parse a specification file into ``(sequence, error)``.

        Exactly one element is meaningful. Unlike every other method here, a
        parser failure is *reported* with its message rather than swallowed.
        """
        ...
