"""MicroOrch equivalent of ``SIM_websocket_data`` (test.yml).

Reproduces the action series of
``helao/deploy/test/experiments/simulatews_exp.py::SIM_websocket_data`` --
``wait, acquire_data, wait, acquire_data`` -- against the ``SIM`` websocket
simulator action server, without the full orchestrator.

The ``wait`` actions in the original are hosted by the orchestrator itself
(``ORCH/wait``); MicroOrch hosts no action endpoints, so each wait becomes an
``asyncio.sleep`` in this script. The ``acquire_data`` actions dispatch to the
``SIM`` server exactly as before.

Prerequisites
-------------
- The ``SIM`` (``ws_simulator``) action server must be running and share this
  script's ``root``. Launch the ``test`` group::

      ./helao.sh test           # starts ORCH (unused here) + SIM:8002 + LIVE vis

  MicroOrch dispatches directly to SIM; the ORCH and live-visualizer are unused.
- ``root`` defaults to ``C:/INST_hlo``; override with ``HELAO_ROOT``.

Run::

    conda run -n helao python -m helao.deploy.test.runners.simulatews_runner
"""

from __future__ import annotations

import os
import asyncio

from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Action
from helao.core.models.machine import MachineModel


ROOT = os.environ.get("HELAO_ROOT", "C:/INST_hlo")
WORLD_CFG = {
    "root": ROOT,
    "servers": {
        "SIM": {"host": "127.0.0.1", "port": 8002},  # matches test.yml SIM
    },
}

WAIT_TIME = 3.0
DATA_DURATION = 5.0


def _acquire_action(duration: float) -> Action:
    """Build a standalone ``SIM/acquire_data`` action."""
    return Action(
        action_name="acquire_data",
        action_server=MachineModel(server_name="SIM"),
        action_params={"duration": duration},
    )


async def main() -> None:
    """wait -> acquire -> wait -> acquire, dispatching acquires to SIM."""
    async with MicroOrch(
        server_key="micro_ws",
        host="127.0.0.1",
        port=9110,
        world_cfg=WORLD_CFG,
    ) as orch:
        acquisitions = []
        for i in range(2):
            # orchestrator "wait" -> plain Python sleep (no ORCH to dispatch to)
            print(f"wait {WAIT_TIME}s ...")
            await asyncio.sleep(WAIT_TIME)

            act = await orch.run_action(_acquire_action(DATA_DURATION))
            acquisitions.append(act)
            print(f"acquire {i + 1}/2: action {act.action_uuid} -> {act.yml_path}")

        zip_path = os.path.join(ROOT, "simulatews_microorch_runs.zip")
        orch.zip_runs(zip_path)
        print(f"\nran {len(acquisitions)} acquisitions; "
              f"tracked {len(orch.runs)} artifacts; archived -> {zip_path}")


if __name__ == "__main__":
    asyncio.run(main())
