"""MicroOrch equivalent of the OER active-learning simulation (demo0).

This script reproduces, without the full orchestrator service, the action
series that the ``OERSIM_activelearn`` sequence
(``helao/deploy/test/sequences/OERSIM_seq.py``) drives through the
``OERSIM_sub_*`` experiments (``helao/deploy/test/experiments/OERSIM_exp.py``)
against the ``CPSIM`` (chronopotentiometry) and ``GPSIM`` (Gaussian-process)
simulator action servers.

to_global / from_global in a standalone script
----------------------------------------------
Under the orchestrator, actions declare ``to_global_params`` /
``from_global_act_params`` and the Orch shuttles values through
``Orch.global_params``. In a self-contained MicroOrch script you do the same
thing explicitly, which is the whole point of MicroOrch -- no Orch needed:

* **to_global**: read the object returned by :meth:`MicroOrch.run_action`,
  pull the value out of its ``action_params``, and store it in a plain dict in
  this script (:data:`GLOBALS`).
* **from_global**: copy the value from :data:`GLOBALS` into the next action's
  params before dispatching it.

The :func:`_capture` and :func:`_inject` helpers below implement exactly that,
mirroring the ``to_global_params`` / ``from_global_act_params`` declarations in
``OERSIM_exp.py``. The simulator servers stamp their outputs onto the action's
``action_params`` (e.g. ``get_loaded_plate`` -> ``_loaded_plate_id``,
``acquire_point`` -> ``_feature``), so the returned ``HelaoAction.action_params``
is the source of every captured value.

The orchestrator version self-requeues via ``GPSIM/check_condition`` calling
``insert_experiment`` on the Orch. MicroOrch has no queue, so the
active-learning loop is a plain Python loop here (default stop rule mirrors
``"max_iters"``).

Prerequisites
-------------
- ``CPSIM`` and ``GPSIM`` must be running and share this script's ``root``.
  Launch the ``demo0`` group (its ORCH/Bokeh are unused -- MicroOrch talks
  straight to the action servers)::

      ./helao.sh demo0          # CPSIM:8002, GPSIM:8003

- ``root`` defaults to the demo configs' ``C:/INST_hlo``; override with
  ``HELAO_ROOT`` to match your servers' configured root.

Run::

    conda run -n helao python -m helao.deploy.test.runners.oersim_runner
"""

from __future__ import annotations

import os
import asyncio
from typing import Any, Dict, Optional

from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Action
from helao.core.models.machine import MachineModel

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
ITERATIONS = 8  # active-learning steps (orchestrator default stop: max_iters)

# Script-level global store -- the MicroOrch-script stand-in for
# Orch.global_params. to_global writes here; from_global reads from here.
GLOBALS: Dict[str, Any] = {}


def _act(server: str, name: str, params: Optional[dict] = None) -> Action:
    """Build a one-off action targeting ``server`` (host/port resolved from cfg)."""
    return Action(
        action_name=name,
        action_server=MachineModel(server_name=server),
        action_params=params or {},
    )


def _inject(params: dict, mapping: Dict[str, str]) -> dict:
    """from_global: copy ``GLOBALS[gkey]`` into ``params[param_name]``.

    ``mapping`` is ``{global_key: action_param_name}`` -- the same shape as an
    action's ``from_global_act_params``.
    """
    for gkey, pname in mapping.items():
        params[pname] = GLOBALS[gkey]
    return params


async def _capture(
    orch: MicroOrch, action: Action, to_global: Optional[Dict[str, str]] = None
):
    """run_action, then to_global: copy named ``action_params`` into ``GLOBALS``.

    ``to_global`` is ``{action_param_key: global_key}``. With a 1:1 name it
    matches an action's ``to_global_params`` list entry.
    """
    result = await orch.run_action(action)
    for src_key, gkey in (to_global or {}).items():
        GLOBALS[gkey] = result.action_params[src_key]
    return result


async def main() -> None:
    """Load-plate then the active-learning loop, all via explicit run_action."""
    async with MicroOrch(
        server_key="micro_oersim",
        host="127.0.0.1",
        port=9100,
        world_cfg=WORLD_CFG,
    ) as orch:
        # --- load plate (mirrors OERSIM_sub_load_plate) --------------------
        await orch.run_action(_act("CPSIM", "change_plate", {"plate_id": PLATE_ID}))
        # to_global: get_loaded_plate -> _loaded_plate_id
        await _capture(
            orch,
            _act("CPSIM", "get_loaded_plate"),
            to_global={"_loaded_plate_id": "_loaded_plate_id"},
        )
        # from_global: _loaded_plate_id -> initialize_plate.plate_id
        await orch.run_action(
            _act(
                "GPSIM",
                "initialize_plate",
                _inject(
                    {"num_random_points": INIT_RANDOM_POINTS, "reinitialize": False},
                    {"_loaded_plate_id": "plate_id"},
                ),
            )
        )
        print(f"loaded plate {GLOBALS.get('_loaded_plate_id')}")

        # --- active-learning loop (mirrors OERSIM_sub_measure_CP) -----------
        for step in range(ITERATIONS):
            # to_global: get_loaded_plate -> _loaded_plate_id
            await _capture(
                orch,
                _act("CPSIM", "get_loaded_plate"),
                to_global={"_loaded_plate_id": "_loaded_plate_id"},
            )
            # from_global plate_id; to_global: acquire_point -> _feature
            await _capture(
                orch,
                _act(
                    "GPSIM",
                    "acquire_point",
                    _inject({}, {"_loaded_plate_id": "plate_id"}),
                ),
                to_global={"_feature": "_feature"},
            )
            # from_global: _feature -> measure_cp.comp_vec
            await orch.run_action(
                _act("CPSIM", "measure_cp", _inject({}, {"_feature": "comp_vec"}))
            )
            # from_global: _loaded_plate_id -> update_model.plate_id
            await orch.run_action(
                _act(
                    "GPSIM",
                    "update_model",
                    _inject({}, {"_loaded_plate_id": "plate_id"}),
                )
            )
            print(f"step {step + 1}/{ITERATIONS}: feature={GLOBALS.get('_feature')}")

        # --- archive every produced artifact relative to RUNS_FINISHED -----
        zip_path = os.path.join(ROOT, "oersim_microorch_runs.zip")
        orch.zip_runs(zip_path)
        print(f"\ntracked {len(orch.runs)} artifacts; archived -> {zip_path}")


if __name__ == "__main__":
    asyncio.run(main())
