"""MicroOrch equivalent of ``SIM_websocket_data`` (test.yml).

Reproduces the action series of
``helao/deploy/test/experiments/simulatews_exp.py::SIM_websocket_data`` --
``wait, acquire_data, wait, acquire_data`` -- without the full orchestrator.

Both servers are treated as plain action servers. The ``wait`` action is hosted
by ``ORCH`` itself (``OrchAPI`` inherits ``BaseAPI``, so the orchestrator
exposes ``/ORCH/wait`` as an RPC action endpoint just like any driver), and
``acquire_data`` is hosted by the ``SIM`` websocket simulator. MicroOrch
dispatches to both directly.

Prerequisites
-------------
- ``ORCH`` and ``SIM`` must be running and share this script's ``root``. Launch
  the ``test`` group (its Bokeh/operator pages are unused)::

      ./helao.sh test           # ORCH:8001 + SIM:8002 + LIVE vis

- ``root`` defaults to ``C:/INST_hlo``; override with ``HELAO_ROOT``.

Run::

    conda run -n helao python -m helao.deploy.test.runners.simulatews_runner
"""

from __future__ import annotations

import os
import asyncio
from typing import Optional

from helao.framework.runners.micro_orch import MicroOrch
from helao.framework.models.action import ActionModel as Action
from helao.framework.models.machine import MachineModel


ROOT = os.environ.get("HELAO_ROOT", "C:/INST_hlo")
WORLD_CFG = {
    "root": ROOT,
    "servers": {
        "ORCH": {"host": "127.0.0.1", "port": 8001},  # hosts the wait action
        "SIM": {"host": "127.0.0.1", "port": 8002},  # hosts acquire_data
    },
}

WAIT_TIME = 3.0
DATA_DURATION = 5.0


def _act(server: str, name: str, params: Optional[dict] = None) -> Action:
    """Build a one-off action targeting ``server`` (host/port resolved from cfg)."""
    return Action(
        action_name=name,
        action_server=MachineModel(server_name=server),
        action_params=params or {},
    )


async def main() -> None:
    """wait -> acquire -> wait -> acquire, all dispatched over RPC."""
    async with MicroOrch(
        server_key="micro_ws",
        host="127.0.0.1",
        port=9110,
        world_cfg=WORLD_CFG,
    ) as orch:
        acquisitions = []
        for i in range(2):
            await orch.run_action(_act("ORCH", "wait", {"waittime": WAIT_TIME}))
            act = await orch.run_action(
                _act("SIM", "acquire_data", {"duration": DATA_DURATION})
            )
            acquisitions.append(act)
            print(f"acquire {i + 1}/2: action {act.action_uuid} -> {act.yml_path}")

        zip_path = os.path.join(ROOT, "simulatews_microorch_runs.zip")
        orch.zip_runs(zip_path)
        print(f"\nran {len(acquisitions)} acquisitions; "
              f"tracked {len(orch.runs)} artifacts; archived -> {zip_path}")


if __name__ == "__main__":
    asyncio.run(main())
