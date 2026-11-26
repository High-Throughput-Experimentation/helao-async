"""MicroOrch equivalent of the TEST scheduling library (TEST_seq / TEST_exp).

The TEST library's actions all target the ``ORCH`` server (``wait``,
``add_global_param``, ``conditional_stop``). Because ``OrchHost`` subclasses
``ActionHost``, the running orchestrator exposes those as ordinary RPC action
endpoints, so MicroOrch treats ``ORCH`` exactly like any other action server
and dispatches to it directly.

This script reproduces:

* ``TEST_seq.TEST_consecutive_noblocking`` -> for each (sample, cycle), a
  ``TEST_sub_noblocking`` pair: a non-blocking ``ORCH/wait`` (10x base time)
  overlapping a blocking ``ORCH/wait``.
* ``TEST_exp.TEST_sub_conditional_stop`` -> ``ORCH/add_global_param`` then
  ``ORCH/conditional_stop``.

to_global / from_global (script-managed)
----------------------------------------
The same hand-off the orchestrator does via ``Orch.global_params`` is done
explicitly here through the script-level :data:`GLOBALS` dict:

* **to_global**: read the object returned by ``run_action`` /
  ``dispatch_action``, pull a value out of its ``action_params``, store it in
  :data:`GLOBALS`.
* **from_global**: copy a value from :data:`GLOBALS` into the next action's
  params before dispatch.

Flow control note
-----------------
``ORCH/conditional_stop`` halts the *orchestrator's own* loop -- but MicroOrch
replaces that loop, so the "skip the rest of the sequence" effect is realised
here by the script reading the same condition out of :data:`GLOBALS` and
breaking. (Dispatching it still exercises the real endpoint; on an idle ORCH it
simply marks that server stopped.)

Prerequisites
-------------
- ``ORCH`` must be running and share the launcher config's ``root``. Launch the
  ``test`` group (SIM/visualizers are unused here)::

      ./helao.sh test           # ORCH:8001

Scenarios (``scenario`` parameter): ``noblocking``, ``conditional`` or ``both``.

Run::

    python -m helao.core.runners.launch test helao.deploy.test.runners.test_runner
"""

from __future__ import annotations

import os
from typing import Any, Optional

from helao.core.models.machine import MachineModel
from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.global_exports import resolve_global_exports
from helao.helpers.premodels import Action

REQUIRES = {"ORCH": ["wait", "add_global_param", "conditional_stop"]}

# Script-level global store: the MicroOrch-script stand-in for Orch.global_params.
GLOBALS: dict[str, Any] = {}


def _act(server: str, name: str, params: Optional[dict] = None) -> Action:
    """Build a one-off action targeting ``server``."""
    return Action(
        action_name=name,
        action_server=MachineModel(server_name=server),
        action_params=params or {},
    )


def _inject(params: dict, mapping: dict[str, str]) -> dict:
    """from_global: copy ``GLOBALS[gkey]`` into ``params[param_name]``."""
    for gkey, pname in mapping.items():
        params[pname] = GLOBALS[gkey]
    return params


async def consecutive_noblocking(
    orch: MicroOrch, wait_time: float, cycles: int, samples: tuple
) -> None:
    """Reproduce TEST_consecutive_noblocking via explicit ORCH dispatch."""
    for smp in samples:
        for cycle in range(cycles):
            # from_global: after the first cycle, dummy_param comes from the
            # prior cycle's test_wait (placeholder consumer, as in the library).
            dummy_param = GLOBALS["test_wait"] if cycle > 0 else 0.0
            print(f"sample {smp} cycle {cycle}: dummy_param={dummy_param}")

            # non-blocking wait: fire-and-forget so it overlaps the blocking one
            nb = _act("ORCH", "wait", {"waittime": wait_time * 10})
            nb.nonblocking = True
            reply = await orch.dispatch_action(nb)
            # to_global: waittime -> test_wait (read the returned action_params)
            GLOBALS["test_wait"] = reply["action_params"]["waittime"]

            # blocking wait
            await orch.run_action(_act("ORCH", "wait", {"waittime": wait_time}))


async def conditional_stop(orch: MicroOrch) -> None:
    """Reproduce TEST_sub_conditional_stop via explicit ORCH dispatch."""
    # add_global_param, then to_global: global_test -> GLOBALS
    res = await orch.run_action(
        _act(
            "ORCH",
            "add_global_param",
            {"param_name": "global_test", "param_value": True},
        )
    )
    # the server publishes via set_output: the value is in action_output
    GLOBALS.update(
        resolve_global_exports(
            ["global_test"],
            res.action_params,
            res.meta_dict.get("action_output") or {},
        )
    )

    # conditional_stop with from_global: GLOBALS[global_test] -> action param
    await orch.run_action(
        _act(
            "ORCH",
            "conditional_stop",
            _inject(
                {"stop_parameter": "global_test", "stop_value": True},
                {"global_test": "global_test"},
            ),
        )
    )

    # script-level flow control: skip the trailing waits when the stop holds
    if GLOBALS.get("global_test") is True:
        print("conditional_stop met -> skipping trailing waits")
        return
    for _ in range(5):
        await orch.run_action(_act("ORCH", "wait", {"waittime": 1}))


async def run(
    orch: MicroOrch,
    wait_time: float = 0.2,
    cycles: int = 2,
    samples=(1, 2),
    scenario: str = "both",
) -> None:
    """Run the TEST equivalents (``scenario``: noblocking, conditional or both).

    Launch the ``test`` group first (ORCH).

    Args:
        wait_time: base seconds for ORCH/wait (the non-blocking wait is 10x).
        cycles: cycles per sample in the noblocking scenario.
        samples: sample numbers to loop over (a list or tuple).
        scenario: ``noblocking``, ``conditional`` or ``both``.
    """
    if isinstance(samples, str):
        raise ValueError("samples must be a list or tuple")
    if scenario not in ("noblocking", "conditional", "both"):
        raise ValueError(f"unknown scenario {scenario!r}")
    if scenario in ("noblocking", "both"):
        print("=== TEST_consecutive_noblocking equivalent ===")
        await consecutive_noblocking(orch, wait_time, cycles, tuple(samples))
        print(f"globals after loop: {dict(GLOBALS)}")
    if scenario in ("conditional", "both"):
        print("\n=== TEST_sub_conditional_stop equivalent ===")
        await conditional_stop(orch)

    zip_path = os.path.join(orch.world_cfg["root"], "test_microorch_runs.zip")
    orch.zip_runs(zip_path)
    print(f"\ntracked {len(orch.runs)} artifacts; archived -> {zip_path}")
