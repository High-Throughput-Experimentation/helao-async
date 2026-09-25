"""Deprecated parameter-name aliases kept alive for live station configs."""

__all__ = ["resolve_sequence_path"]

from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)

_WARNED = set()


def resolve_sequence_path(params: dict) -> Optional[str]:
    """The finished sequence's location, under either parameter name.

    A synced sequence is no longer zipped (spec D9), so ``sequence_zip_path``
    names something that is usually a directory. The honest name is
    ``sequence_path``; the old one stays accepted so live configs
    (``auto_analyze_sequences``) and the ``*_postseq`` sequences keep working
    with no edit. ``LocalLoader`` already accepts a directory, a zip, or a yml,
    so callers need no other change.

    Args:
        params: An action's ``action_params`` mapping.

    Returns:
        The sequence path under either name, or None if neither is set.

    Note:
        Warned once per process rather than per call: these fire on every
        synced sequence and would otherwise bury the log.
    """
    if params.get("sequence_path"):
        return params["sequence_path"]
    legacy = params.get("sequence_zip_path")
    if legacy:
        if "sequence_zip_path" not in _WARNED:
            _WARNED.add("sequence_zip_path")
            LOGGER.warning(
                "sequence_zip_path is deprecated; use sequence_path. A synced "
                "sequence is a directory, not a zip."
            )
        return legacy
    return None
