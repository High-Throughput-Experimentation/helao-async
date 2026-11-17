"""MicroOrch equivalent of ``SIM_websocket_data`` (test.yml).

Reproduces the action series of
``helao/deploy/test/experiments/simulatews_exp.py::SIM_websocket_data`` --
``wait, acquire_data, wait, acquire_data`` -- without the full orchestrator.

Both servers are treated as plain action servers. The ``wait`` action is hosted
by ``ORCH`` itself (``OrchHost`` subclasses ``ActionHost``, so the orchestrator
exposes ``/ORCH/wait`` as an RPC action endpoint just like any driver), and
``acquire_data`` is hosted by the ``SIM`` websocket simulator. MicroOrch
dispatches to both directly.

Prerequisites
-------------
- ``ORCH`` and ``SIM`` must be running and share the launcher config's ``root``.
  Launch the ``test`` group (its Bokeh/operator pages are unused)::

      ./helao.sh test           # ORCH:8001 + SIM:8002 + LIVE vis

Run::

    python -m helao.core.runners.launch test helao.deploy.test.runners.simulatews_runner
"""

from __future__ import annotations

import os
from typing import Optional

from helao.core.models.machine import MachineModel
from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Action

REQUIRES = {"ORCH": ["wait"], "SIM": ["acquire_data"]}


def _act(server: str, name: str, params: Optional[dict] = None) -> Action:
    """Build a one-off action targeting ``server`` (host/port resolved from cfg)."""
    return Action(
        action_name=name,
        action_server=MachineModel(server_name=server),
        action_params=params or {},
    )


async def run(
    orch: MicroOrch, wait_time: float = 3.0, data_duration: float = 5.0
) -> None:
    """wait -> acquire -> wait -> acquire, all dispatched over RPC.

    Launch the ``test`` group first (ORCH and SIM).

    Args:
        wait_time: seconds for each ORCH/wait.
        data_duration: seconds of SIM/acquire_data per acquisition.
    """
    acquisitions = []
    for i in range(2):
        await orch.run_action(_act("ORCH", "wait", {"waittime": wait_time}))
        act = await orch.run_action(
            _act("SIM", "acquire_data", {"duration": data_duration})
        )
        acquisitions.append(act)
        print(f"acquire {i + 1}/2: action {act.action_uuid} -> {act.yml_path}")

    zip_path = os.path.join(orch.world_cfg["root"], "simulatews_microorch_runs.zip")
    orch.zip_runs(zip_path)
    print(
        f"\nran {len(acquisitions)} acquisitions; "
        f"tracked {len(orch.runs)} artifacts; archived -> {zip_path}"
    )
