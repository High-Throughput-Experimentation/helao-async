"""Built-in post-finish hook: today's ``auto_analyze_sequences`` dispatch.

Non-blocking (spec §6.1). ``args`` = the per-record analysis block:
``server_key`` and ``endpoint`` are required; ``params`` (or the alias
``analysis_params``) are forwarded; ``host``/``port`` are used as the target
server entry when both are present (that is what an ``auto_analyze_sequences``
block carries, and it keeps the dispatch payload identical to today), else the
entry comes from the syncer's world config (settled decision A4). The payload
names a directory -- ``sequence_path`` or ``experiment_path`` by level (D9).
"""

from helao.core.hooks import FinishHook, HookConfigError, PostfinishContext
from helao.core.models.machine import MachineModel
from helao.helpers import dispatcher
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class Hook(FinishHook):
    blocking = False
    phase = "postfinish"
    levels = ("experiment", "sequence")

    async def run(self, ctx: PostfinishContext) -> None:
        args = dict(ctx.args or {})
        for key in ("server_key", "endpoint"):
            if key not in args:
                raise HookConfigError(f"dispatch_analysis args need {key!r}: {args}")
        level = ctx.yml.type
        name = ctx.yml.meta.get(f"{level}_name", "NA")
        server_key = args["server_key"]
        if "host" in args and "port" in args:
            target_cfg = args
        else:
            servers = (getattr(ctx.syncer, "world_config", None) or {}).get(
                "servers", {}
            )
            if server_key not in servers:
                raise HookConfigError(
                    f"dispatch_analysis: no host/port in args and no server "
                    f"{server_key!r} in the world config"
                )
            target_cfg = servers[server_key]
        params = args.get("params", args.get("analysis_params", {}))
        LOGGER.info(f"dispatching auto-analysis {args['endpoint']} for {name}")
        await dispatcher.async_action_dispatcher(
            world_config_dict={"servers": {server_key: target_cfg}},
            A=Action(
                action_name=args["endpoint"],
                action_server=MachineModel(server_name=server_key),
                action_params={
                    f"{level}_path": str(ctx.yml.target.parent),
                    "params": params,
                },
            ),
        )
