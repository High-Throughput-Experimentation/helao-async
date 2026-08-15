"""The hexagon's saved-parameter face (P7h).

:class:`ParamStore` satisfies
:class:`~helao.hexagon.ports.param_store.ParamStorePort` by **delegating to
the shared module** ``helao/ui/shared/operator/param_store.py``. Nothing is
reimplemented, and that is the design: the store is one file that two UIs and
two processes read and write, so a second implementation would be a second
opinion about the same bytes on disk. The tolerant-read behaviour in
particular is not re-derivable -- a half-written ``previous_params.json`` from
a station that lost power is a real outcome, and the module's answer to it
(warn, return empty, let the next write replace it) is the answer.

Stateless, and takes ``root`` per call rather than at construction. The store
is located from the config root, one instance serves whatever root a caller
holds, and a constructor-held root is only a place for a stale one to hide.

Under ``adapters/vis/`` because ``adapters/native/`` may not import
``helao.core.servers.*`` (test_boundaries.py:131-143).
"""

from typing import Optional

from helao.ui.shared.operator import param_store as legacy

__all__ = ["ParamStore"]


class ParamStore:
    """:class:`ParamStorePort` over the shared ``param_store`` module."""

    def params_path(self, root: str) -> str:
        """Delegate to :func:`param_store.params_path`."""
        return legacy.params_path(root)

    def read_params(self, root: str, kind: str, name: str) -> dict:
        """Delegate to :func:`param_store.read_params`."""
        return legacy.read_params(root, kind, name)

    def read_last_meta(self, root: str) -> dict:
        """Delegate to :func:`param_store.read_last_meta`."""
        return legacy.read_last_meta(root)

    def write_params(
        self,
        root: str,
        kind: str,
        name: str,
        params: dict,
        meta: Optional[dict] = None,
    ) -> bool:
        """Delegate to :func:`param_store.write_params`.

        The ``bool`` is passed through unchanged: it is the only signal that a
        value was not remembered, and an adapter that dropped it would make
        every failed save look successful.
        """
        return legacy.write_params(root, kind, name, params, meta)

    def form_values(self, params) -> dict:
        """Delegate to :func:`param_store.form_values`."""
        return legacy.form_values(params)
