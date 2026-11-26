"""Write-once plan sidecars (spec §3.3), shared by MetaWriter and MicroOrch."""

__all__ = ["write_plan_once"]

from pathlib import Path

from helao.helpers.artifact_hash import log_artifact_hashes
from helao.helpers.meta_io import dumps_meta


async def write_plan_once(
    target, payload: dict, write_atomic, *, kind: str, owner_uuid
) -> bool:
    """Write ``payload`` to ``target`` unless a plan is already there.

    A plan records initial intent, so a ``--restore`` re-dispatch must not
    replace it. ``write_atomic(path, text)`` is the caller's staged-rename
    writer, which keeps the ``staging_path`` rule. Returns whether it wrote.
    """
    target = Path(target)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    await write_atomic(str(target), dumps_meta(payload, target))
    await log_artifact_hashes([target], kind=kind, owner_uuid=owner_uuid)
    return True
