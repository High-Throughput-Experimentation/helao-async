"""Post-finish chain runner (spec §6.2). State lives in the ``.prg`` sidecar.

Per record, per ``sync_yml`` pass, for each matching hook in config order:
``done`` -> skip; non-blocking ``failed`` -> skip (clearing the hook's entry
from ``hooks:`` *and* setting ``synced: false`` re-arms it -- a ``.prg``
already carrying ``synced: true`` is gated out of ``sync_yml`` before the
chain is ever reached, so clearing the entry alone is not enough); otherwise
run it. Success -> ``done``; blocking failure -> ``failed`` and
stop (the record stays unsynced and the next pass re-runs this hook);
non-blocking failure -> ``failed`` + alert, continue. The chain reports synced
when every blocking hook in it is ``done``.

``hooks: {}`` and ``synced: false`` are written before the first hook so that
``_prg_is_complete`` (helao.helpers.run_state) judges this record by
``synced`` and never by the legacy ``s3``/``api`` pair the s3_upload hook
sets mid-chain (settled decision A5).
"""

__all__ = ["run_postfinish_chain"]

from datetime import datetime

from helao.core.hooks import PostfinishContext
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def run_postfinish_chain(syncer, prog, opts: dict) -> bool:
    """Run the record's post-finish chain; return whether it is now synced."""
    level = prog.yml.type
    name = prog.yml.meta.get(f"{level}_name", "NA")
    hook_set = syncer.postfinish[level]
    chain = hook_set.select(name)

    states = prog.dict.get("hooks") or {}
    prog.dict["hooks"] = states
    if "synced" not in prog.dict:
        prog.dict["synced"] = False
    prog.write_dict()

    for hook_name, hook, args in chain:
        entry = states.get(hook_name) or {}
        if entry.get("state") == "done":
            continue
        if entry.get("state") == "failed" and not hook.blocking:
            continue
        LOGGER.info(f"Running post-finish hook {hook_name!r} for {level} {name}")
        ctx = PostfinishContext(
            yml=prog.yml, prg=prog, syncer=syncer, args=args, opts=opts
        )
        try:
            await hook.run(ctx)
        except Exception as exc:
            states[hook_name] = {
                "state": "failed",
                "ts": _ts(),
                "error": f"{type(exc).__name__}: {exc}",
            }
            prog.write_dict()
            if hook.blocking:
                LOGGER.error(
                    f"blocking post-finish hook {hook_name!r} failed for {level} "
                    f"{name} ({prog.yml.target.name}); chain stopped, record stays "
                    "unsynced for the next pass",
                    exc_info=True,
                )
                prog.dict["synced"] = False
                prog.write_dict()
                return False
            LOGGER.error(
                f"non-blocking post-finish hook {hook_name!r} failed for {level} {name}",
                exc_info=True,
            )
            LOGGER.alert(  # type: ignore[attr-defined]
                f"non-blocking post-finish hook {hook_name!r} failed for {level} "
                f"{name} ({prog.yml.target.name}): {type(exc).__name__}: {exc}; "
                "clear its entry from the .prg's hooks: and set synced: false "
                "to re-arm it"
            )
            continue
        states[hook_name] = {"state": "done", "ts": _ts()}
        prog.write_dict()

    synced = all(
        states.get(hook_name, {}).get("state") == "done"
        for hook_name, hook, _ in chain
        if hook.blocking
    )
    prog.dict["synced"] = synced
    prog.write_dict()
    return synced
