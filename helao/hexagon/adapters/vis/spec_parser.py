"""The hexagon's spec-parser face (P7h).

:class:`SpecParserGateway` satisfies
:class:`~helao.hexagon.ports.spec_parser.SpecParserPort` by **delegating to
the shared module** ``helao/core/servers/operator/spec_parser.py``.

Delegation matters more here than anywhere else in P7h. The module does not
merely read files -- it ``exec_module``s one named by a config key, i.e. it
runs a deployment's own code inside the operator process. Its five functions
are wrapped in ``try``/``except`` that returns ``None``/``[]``/an error string
for *every* failure, so the Specs tab goes quiet instead of the page going
down. A reimplementation that got one of those five branches wrong would
convert "this station configures no parser" into a traceback on the operator
page, which is the outcome the whole design avoids. So: no logic here, only
forwarding.

Named ``SpecParserGateway`` rather than ``SpecParser`` on purpose -- the
deployment's own class *is* ``SpecParser``, it is the thing
:meth:`load_parser` returns, and two different objects under one name in a
module that handles both would be a genuine hazard.

Stateless. The module-level parser cache stays in the module: it is keyed by
path and its whole point is to be shared across sessions, so hanging it off an
instance would re-run a deployment's import side effects per operator tab.

Under ``adapters/vis/`` because ``adapters/native/`` may not import
``helao.core.servers.*`` (test_boundaries.py:131-143).
"""

from helao.core.servers.operator import spec_parser as legacy

__all__ = ["SpecParserGateway"]


class SpecParserGateway:
    """:class:`SpecParserPort` over the shared ``spec_parser`` module."""

    def load_parser(self, parser_path) -> object:
        """Delegate to :func:`spec_parser.load_parser`. ``None`` on any failure."""
        return legacy.load_parser(parser_path)

    def clear_parser_cache(self) -> None:
        """Delegate to :func:`spec_parser.clear_parser_cache`."""
        legacy.clear_parser_cache()

    def spec_files(self, parser, folder) -> list:
        """Delegate to :func:`spec_parser.spec_files`."""
        return legacy.spec_files(parser, folder)

    def spec_fields(self, parser, spec_file: str, backend) -> list:
        """Delegate to :func:`spec_parser.spec_fields`."""
        return legacy.spec_fields(parser, spec_file, backend)

    def build_spec_sequence(
        self, parser, spec_file: str, backend, params: dict, kwargs: dict
    ) -> tuple:
        """Delegate to :func:`spec_parser.build_spec_sequence`.

        Returns ``(sequence, error)`` unchanged -- collapsing the pair to just
        the sequence would discard the only thing an operator can act on when
        their own spec file fails to parse.
        """
        return legacy.build_spec_sequence(parser, spec_file, backend, params, kwargs)
