"""Shared adapter-layer errors (importable by adapters AND app)."""

__all__ = ["UnwiredPortError"]


class UnwiredPortError(RuntimeError):
    """A consumed port/handle has no adapter wired — refuse to proceed."""
