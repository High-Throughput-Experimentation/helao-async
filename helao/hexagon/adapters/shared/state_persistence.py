"""StatePersistencePort adapter: the queues.pck FILE contract (core-01 §2).

Owns everything ``QueuePersister`` used to do to ``STATES``: the plain
``STATES/queues.pck`` and the timestamped series ``queues_<%y%m%d.%H%M%S>.pck``
(pruned to the newest few), the ``queues_unreadable_<ts>.pck`` quarantine of a
pickle that will not load, and the consumed-pck archiving rule (a successfully
restored ``queues.pck`` is renamed ``queues_imported_<ts>.pck`` so hot-reload's
unconditional ``--restore`` cannot replay it).

The port is payload-in/payload-out and holds no orch back-reference: building
the payload, the schema check and applying it to a live orchestrator stay in
``orch_persist.QueuePersister``. Paths are ``os.path`` strings, never ``Path``:
``/export_queues`` and ``/import_queues`` return them, and ``str(Path(...))``
rewrites separators on Windows."""

import os
import pickle
import re
from datetime import datetime
from typing import Optional

from helao.helpers import helao_logging as logging

__all__ = [
    "QueuePckStore",
    "TIMESTAMPED_EXPORT_RETENTION",
    "prune_timestamped_exports",
]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# How many timestamped exports to keep. The dispatch post-loop writes one every
# time the orchestrator stops with non-empty queues, so uncapped they accumulate
# indefinitely -- instruments have been found holding files over a year old.
TIMESTAMPED_EXPORT_RETENTION = 5

# Matches only the timestamped export series written by ``export_queues``
# (``queues_<YYMMDD>.<HHMMSS>.pck``). Deliberately excludes the
# ``queues_imported_<ts>.pck`` and ``queues_unreadable_<ts>.pck`` archives: those
# are forensic records of a restore and of a failed load, and pruning them would
# delete the evidence someone is most likely to want.
_TIMESTAMPED_EXPORT_RE = re.compile(r"^queues_\d{6}\.\d{6}\.pck$")


def prune_timestamped_exports(
    states_dir: str, keep: int = TIMESTAMPED_EXPORT_RETENTION
) -> list:
    """Delete all but the newest ``keep`` timestamped exports in ``states_dir``.

    Only the ``queues_<YYMMDD>.<HHMMSS>.pck`` series is considered (see
    :data:`_TIMESTAMPED_EXPORT_RE`); the plain ``queues.pck`` and the
    ``_imported_``/``_unreadable_`` archives are left alone. Newest is decided
    by the timestamp in the filename rather than mtime, so a copied or touched
    file cannot reorder the series.

    Never raises: this runs from :meth:`QueuePckStore.export_queues`, which itself
    runs during orchestrator shutdown, and failing to tidy up must not turn into a
    failure to save the queues.

    Args:
        states_dir: The ``STATES`` directory to prune.
        keep: How many of the newest exports to retain.

    Returns:
        The filenames removed, newest-last.
    """
    try:
        names = sorted(
            n for n in os.listdir(states_dir) if _TIMESTAMPED_EXPORT_RE.match(n)
        )
    except Exception:
        LOGGER.error(
            f"Could not list '{states_dir}' to prune timestamped queue "
            f"exports; leaving them in place.",
            exc_info=True,
        )
        return []
    if len(names) <= keep:
        return []
    removed = []
    for name in names[:-keep]:
        try:
            os.remove(os.path.join(states_dir, name))
            removed.append(name)
        except Exception:
            LOGGER.error(f"Could not remove '{name}'.", exc_info=True)
    if removed:
        LOGGER.info(
            f"Pruned {len(removed)} timestamped queue export(s), keeping the "
            f"newest {keep}: removed {removed[0]}..{removed[-1]}"
            if len(removed) > 1
            else f"Pruned 1 timestamped queue export, keeping the newest "
            f"{keep}: removed {removed[0]}"
        )
    return removed


class QueuePckStore:
    def __init__(self, root: str):
        self._root = root

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> str:
        """Pickle ``payload`` under ``STATES/`` and return the written path.

        When ``timestamp_pck`` is set the timestamped series is pruned to
        :data:`TIMESTAMPED_EXPORT_RETENTION` files afterwards.
        """
        if timestamp_pck:
            pck_name = f"queues_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
        else:
            pck_name = "queues.pck"
        states_dir = os.path.join(self._root, "STATES")
        save_path = os.path.join(states_dir, pck_name)
        with open(save_path, "wb") as f:
            pickle.dump(payload, f)
        if timestamp_pck:
            prune_timestamped_exports(states_dir)
        return save_path

    def load_queues(self, pck_path: Optional[str] = None) -> tuple[str, Optional[dict]]:
        """Return ``(path, payload)`` for ``pck_path`` (default ``queues.pck``).

        ``payload`` is ``None`` when the file does not exist, or when it will not
        unpickle -- in which case it is first moved aside to ``_unreadable_``.
        Loading never consumes a readable file: see :meth:`archive_consumed`.
        """
        if pck_path is None:
            save_path = os.path.join(self._root, "STATES", "queues.pck")
        else:
            save_path = pck_path.strip('"').strip("'")
        if os.path.exists(save_path):
            try:
                with open(save_path, "rb") as f:
                    queue_dict = pickle.load(f)
            except Exception:
                # A pickle written by an older release can reference classes this
                # one no longer has (e.g. a renamed model), and unpickling raises
                # AttributeError. This runs inside the orchestrator's FastAPI
                # startup_event, so an escape here fails the lifespan and the
                # server exits instead of coming up -- a stale file on disk must
                # not be able to keep the orchestrator down. Quarantine it so the
                # next startup is clean rather than repeating the same failure.
                quarantine = save_path.replace(
                    ".pck",
                    f"_unreadable_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck",
                )
                try:
                    os.rename(save_path, quarantine)
                    moved = f"moved it to '{os.path.basename(quarantine)}'"
                except Exception:
                    moved = "could not move it aside"
                LOGGER.error(
                    f"Could not unpickle '{save_path}' -- it was most likely "
                    f"written by a different code version; {moved} and starting "
                    f"with empty queues.",
                    exc_info=True,
                )
                return save_path, None
        else:
            LOGGER.info("Exported queues.pck does not exist. Cannot restore.")
            return save_path, None
        return save_path, queue_dict

    def archive_consumed(self, path: str) -> Optional[str]:
        """Rename a restored pck to ``queues_imported_<ts>.pck``; ``None`` on failure.

        Consume the default queues.pck after a successful restore so a stale file
        cannot be auto-replayed on a later restart (e.g. hot-reload of an
        idle-empty orchestrator, which passes --restore unconditionally). Archive
        rather than delete so it stays recoverable.
        """
        try:
            archived = path.replace(
                ".pck",
                f"_imported_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck",
            )
            os.replace(path, archived)
            LOGGER.info(f"Archived restored queue pck to {archived}.")
            return archived
        except OSError:
            LOGGER.warning("Could not archive restored queue pck.", exc_info=True)
            return None
