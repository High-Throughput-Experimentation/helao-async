"""Saved-parameter store port (P7h; Q8 -- fs read+write).

Mirrors ``helao/ui/shared/operator/param_store.py``, whose whole substance
is one file: ``<root>/STATES/previous_params.json`` (written at ``:125``, read
at ``:57``, located at ``:38``). It is a **cross-UI, cross-session artifact** --
a station's operator may save it from Bokeh and load it back in Reflex -- which
is why it is one module under both UIs and one port here rather than a helper
inside either.

Two clauses carried from the module, because a second implementation would
lose them silently:

* **A read never writes.** A missing store yields the empty shape; it is not
  created. Opening the operator must not put a file into an instrument's data
  tree.
* **A write never raises, and says whether it happened.** Saving runs as part
  of enqueueing an experiment, so a half-written file from a station that lost
  power mid-write must cost the operator a remembered value, not the enqueue.
  :meth:`write_params` returns ``bool`` for exactly that reason -- it is a
  report, not a status code, and discarding it discards the only signal.

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82), which is no
constraint here: every value crossing this seam is a builtin. The concrete
face is ``adapters/vis/param_store.py`` -- not ``adapters/native/``, which may
not import ``helao.core.servers.*`` (test_boundaries.py:131-143), and the
shared module lives exactly there.
"""

from typing import Optional, Protocol, runtime_checkable

__all__ = ["PARAM_KINDS", "ParamStorePort"]

#: The two kinds of saved parameters, matching the store's top-level keys.
#: Mirrored from ``param_store.PARAM_KINDS`` and pinned equal to it, so a third
#: kind cannot appear on one side only.
PARAM_KINDS = ("seq", "exp")


@runtime_checkable
class ParamStorePort(Protocol):
    """Structural mirror of the ``param_store`` module's public functions."""

    def params_path(self, root: str) -> str:
        """Path of the store under ``root``."""
        ...

    def read_params(self, root: str, kind: str, name: str) -> dict:
        """Parameters last saved for ``name``, or ``{}``.

        ``{}`` covers every failure -- an unknown ``kind``, no store, an
        unreadable store, no entry for ``name``. The caller cannot tell them
        apart and does not need to: all four mean "nothing to reload".
        """
        ...

    def read_last_meta(self, root: str) -> dict:
        """The label/campaign block last saved, or ``{}``."""
        ...

    def write_params(
        self,
        root: str,
        kind: str,
        name: str,
        params: dict,
        meta: Optional[dict] = None,
    ) -> bool:
        """Save the parameters used for ``name``; report whether it happened.

        ``meta`` omitted leaves the previous block in place, so saving a
        sequence's parameters does not wipe the campaign the operator set
        earlier. An empty ``root`` (a UI-only server) writes nothing and
        returns ``False`` -- not an error, just nowhere to put it.
        """
        ...

    def form_values(self, params) -> dict:
        """Render saved parameters as the strings a form's inputs hold."""
        ...
