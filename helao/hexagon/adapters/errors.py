"""Shared adapter-layer errors (importable by adapters AND app)."""

__all__ = ["HexagonDeferred", "UnwiredPortError"]


class UnwiredPortError(RuntimeError):
    """A consumed port/handle has no adapter wired — refuse to proceed."""


class HexagonDeferred(NotImplementedError):
    """A member whose legacy bridge is deliberately deferred to a later
    slice (documented at the raise site) — loud, never silent."""
