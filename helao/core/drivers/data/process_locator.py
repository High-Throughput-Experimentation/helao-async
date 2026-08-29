"""Locate a experiment's ``-prc.yml`` artifacts, in either of the two
FILESYSTEM places they have lived.

A process's only on-disk artifact used to be written to ``root/PROCESSES``,
mirroring the record's relative path but sitting outside the ``RUNS_*`` tree
that gets zipped. It is now written beside its ``-exp.yml``. Records synced
before that change keep their artifact in the mirror, and nothing migrates
them, so every reader needs the same two-location rule -- which is why it
lives here and not copied into each one.

Both locations this module knows about are paths on disk. A fully-synced
record's colocated prc is no longer one of them: ``zip_dir`` deletes the
source directory on success, so the prc exists only as bytes inside the
sequence zip. This module does not read zip members and never will --
that is an accepted scope limit, not an oversight. A caller that needs a
fully-synced record's prc must go through a zip-aware reader instead (see
``helao.ui.shared.data_browser.sources.DerivedSourceIndex`` for one).

The write side does not use this. It needs only the colocated set, and
``HelaoYml.process_ymls`` supplies that without an import, which the byte-pinned
region of ``sync_driver.py`` requires.
"""

import os
from pathlib import Path


def process_uuid_of(path: "str | os.PathLike[str]") -> str:
    """The process uuid a ``-prc.yml`` filename carries.

    Args:
        path: Path to a ``-prc.yml``.

    Returns:
        The uuid segment, or ``""`` when the name does not match the format.
    """
    name = Path(path).name
    parts = name[: -len("-prc.yml")].split("__") if name.endswith("-prc.yml") else []
    return parts[1] if len(parts) >= 3 else ""


def _experiment_dir(experiment: "str | os.PathLike[str]") -> Path:
    p = Path(experiment)
    return p.parent if p.is_file() or p.name.endswith(".yml") else p


def find_process_ymls(
    experiment: "str | os.PathLike[str]",
    process_root: "str | os.PathLike[str] | None" = None,
) -> list[Path]:
    """Every ``-prc.yml`` belonging to one experiment, from both locations.

    Args:
        experiment: The experiment's ``-exp.yml`` path, or its directory.
        process_root: Root of the legacy ``PROCESSES`` mirror. When ``None``,
            only the colocated artifacts are returned.

    Returns:
        Colocated artifacts first, then any mirror artifact whose process uuid
        is not already present. Sorted by filename within each source, so the
        result is stable across filesystems.
    """
    exp_dir = _experiment_dir(experiment)
    found = sorted(
        (x for x in exp_dir.glob("*-prc.yml") if x.is_file()), key=lambda x: x.name
    )
    if process_root is None:
        return found

    seen = {process_uuid_of(x) for x in found}
    mirror = _mirror_dir(exp_dir, Path(process_root))
    if mirror is None or not mirror.is_dir():
        return found

    for x in sorted(
        (y for y in mirror.glob("*-prc.yml") if y.is_file()), key=lambda y: y.name
    ):
        uuid = process_uuid_of(x)
        if uuid and uuid in seen:
            continue  # the colocated copy wins
        seen.add(uuid)
        found.append(x)
    return found


def _mirror_dir(exp_dir: Path, process_root: Path) -> "Path | None":
    """The ``PROCESSES`` directory mirroring ``exp_dir``.

    The mirror reproduces the record's path below the ``RUNS_*`` segment, so
    that segment is where the two trees are rejoined. Returns ``None`` when
    ``exp_dir`` is not inside a ``RUNS_*`` tree, which is the only case where no
    correspondence exists.
    """
    parts = exp_dir.parts
    runs = [i for i, p in enumerate(parts) if p.startswith("RUNS_")]
    if not runs:
        return None
    return process_root.joinpath(*parts[runs[0] + 1 :])
