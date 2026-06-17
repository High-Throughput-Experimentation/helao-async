"""MicroOrch equivalent of the OER active-learning simulation (demo0).

This script reproduces, without the full orchestrator service, the action and
experiment series that the ``OERSIM_activelearn`` sequence
(``helao/deploy/test/sequences/OERSIM_seq.py``) drives through the
``OERSIM_sub_*`` experiments (``helao/deploy/test/experiments/OERSIM_exp.py``)
against the ``CPSIM`` (chronopotentiometry) and ``GPSIM`` (Gaussian-process)
simulator action servers.

What it does
------------
1. Loads a plate on ``CPSIM`` and seeds ``GPSIM`` priors (mirrors
   ``OERSIM_sub_load_plate``).
2. Repeatedly runs ``OERSIM_sub_measure_CP`` -- get loaded plate, pick the next
   composition, run a simulated CP, refit the model -- as a Python loop.

The orchestrator-driven version self-requeues via ``GPSIM/check_condition``
calling ``insert_experiment`` back on the Orch. MicroOrch hosts no
``insert_experiment`` endpoint and keeps no experiment queue, so the
active-learning loop is expressed directly in Python here (the script *is* the
orchestrator replacement). The default stop rule mirrors ``"max_iters"``.

Cross-action parameter hand-off (``to_global_params`` /
``from_global_act_params``) works exactly as under the orchestrator:
``MicroOrch.run_experiment`` captures outputs into ``orch.global_params`` and
re-injects them into later actions, and those globals persist across loop
iterations on the ``MicroOrch`` instance.

Prerequisites
-------------
- The ``CPSIM`` and ``GPSIM`` action servers must already be running and must
  use the SAME ``root`` as this script (MicroOrch reads finished artifacts off
  the shared filesystem). The simplest way is to launch the ``demo0`` group::

      ./helao.sh demo0          # starts ORCH (unused here), CPSIM:8002, GPSIM:8003

  MicroOrch talks directly to CPSIM/GPSIM over RPC; the demo0 ORCH and Bokeh
  pages are simply unused.
- ``root`` defaults to the demo configs' ``C:/INST_hlo``; override with the
  ``HELAO_ROOT`` env var to match your servers' configured root.

Run::

    conda run -n helao python -m helao.deploy.test.runners.oersim_runner
"""

from __future__ import annotations

import os
import asyncio
from typing import List

from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.deploy.test.experiments.OERSIM_exp import OERSIM_sub_measure_CP


# --- wiring (matches demo0.yml CPSIM/GPSIM host:port) ----------------------
ROOT = os.environ.get("HELAO_ROOT", "C:/INST_hlo")
WORLD_CFG = {
    "root": ROOT,
    "servers": {
        "CPSIM": {"host": "127.0.0.1", "port": 8002},
        "GPSIM": {"host": "127.0.0.1", "port": 8003},
    },
}

PLATE_ID = 2750
INIT_RANDOM_POINTS = 5
ITERATIONS = 8  # active-learning steps to run (orchestrator default: max_iters)


def oersim_load_plate(experiment: Experiment, init_random_points: int = 5):
    """Switch CPSIM to a plate and seed GPSIM priors for it.

    Mirrors ``OERSIM_exp.OERSIM_sub_load_plate`` but returns its planned
    actions so ``MicroOrch.run_experiment`` can dispatch them (the library
    version builds the same plan without returning it).
    """
    apm = ActionPlanMaker()
    apm.add("CPSIM", "change_plate", {"plate_id": PLATE_ID})
    apm.add("CPSIM", "get_loaded_plate", {}, to_global_params=["_loaded_plate_id"])
    apm.add(
        "GPSIM",
        "initialize_plate",
        {"num_random_points": init_random_points, "reinitialize": False},
        from_global_act_params={"_loaded_plate_id": "plate_id"},
    )
    return apm.planned_actions


async def main() -> None:
    """Run load-plate then the active-learning measurement loop via MicroOrch."""
    async with MicroOrch(
        server_key="micro_oersim",
        host="127.0.0.1",
        port=9100,
        world_cfg=WORLD_CFG,
    ) as orch:
        # 1) initialize the plate / GP priors
        loaded = await orch.run_experiment(
            oersim_load_plate, init_random_points=INIT_RANDOM_POINTS
        )
        print(f"loaded plate -> experiment {loaded.experiment_uuid}")
        print(f"  global_params now: {sorted(orch.global_params)}")

        # 2) active-learning loop (replaces the orchestrator self-requeue)
        results: List = []
        for step in range(ITERATIONS):
            exp = await orch.run_experiment(
                OERSIM_sub_measure_CP, init_random_points=INIT_RANDOM_POINTS
            )
            results.append(exp)
            feature = orch.global_params.get("_feature")
            print(f"step {step + 1}/{ITERATIONS}: exp {exp.experiment_uuid} "
                  f"feature={feature}")

        # 3) archive every produced artifact relative to RUNS_FINISHED
        zip_path = os.path.join(ROOT, "oersim_microorch_runs.zip")
        orch.zip_runs(zip_path)
        print(f"\nran {len(results)} measurement experiments")
        print(f"tracked {len(orch.runs)} artifacts; archived -> {zip_path}")


if __name__ == "__main__":
    asyncio.run(main())
