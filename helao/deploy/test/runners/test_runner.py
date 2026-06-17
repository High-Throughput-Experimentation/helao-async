"""MicroOrch equivalent of the TEST scheduling library (TEST_seq / TEST_exp).

The TEST library exercises *orchestrator-internal* behaviour only: every action
in ``TEST_exp.py`` targets the ``ORCH`` server (``wait``, ``add_global_param``,
``conditional_stop``) and ``TEST_seq.py`` chains those experiments to verify
non-blocking dispatch, global-parameter hand-off, and conditional sequence
termination.

Because those actions are hosted by the orchestrator itself -- not by an
external action server -- there is nothing for MicroOrch to dispatch over RPC.
The faithful MicroOrch equivalent therefore expresses each orchestrator
primitive in Python:

    ORCH/wait              -> asyncio.sleep
    ORCH/add_global_param  -> orch.global_params[name] = value
    ORCH/conditional_stop  -> read orch.global_params, break the loop
    to_global_params       -> write orch.global_params
    from_global_*_params   -> read orch.global_params

This module needs NO running servers. It uses a ``MicroOrch`` instance purely
as the global-parameter store (the same role ``Orch.global_params`` plays), so
the param hand-off semantics match the orchestrator version.

Run::

    conda run -n helao python -m helao.deploy.test.runners.test_runner
"""

from __future__ import annotations

import asyncio

from helao.core.runners.micro_orch import MicroOrch


# No action servers are contacted; root/servers can be empty.
WORLD_CFG: dict = {"servers": {}}


async def test_sub_noblocking(
    orch: MicroOrch, wait_time: float = 3.0, dummy_param: float = 0.0
) -> asyncio.Task:
    """Python equivalent of ``TEST_exp.TEST_sub_noblocking``.

    A non-blocking wait (10x ``wait_time``, published to the global
    ``test_wait``) overlaps a following blocking wait. ``dummy_param`` is the
    placeholder the sequence wires from the prior cycle's ``test_wait``.
    """
    # nonblocking wait -> fire-and-forget; publish its waittime to globals
    nb_wait = wait_time * 10
    nb_task = asyncio.create_task(asyncio.sleep(nb_wait))
    orch.global_params["test_wait"] = nb_wait  # to_global_params

    # blocking wait
    await asyncio.sleep(wait_time)
    return nb_task  # caller may await outstanding non-blocking waits


async def test_consecutive_noblocking(
    orch: MicroOrch,
    wait_time: float = 0.2,
    cycles: int = 2,
    plate_sample_no_list=(1, 2, 3),
) -> None:
    """Python equivalent of ``TEST_seq.TEST_consecutive_noblocking``.

    One ``test_sub_noblocking`` per (sample_no, cycle). After the first cycle of
    each sample the ``dummy_param`` is taken from the prior cycle's ``test_wait``
    global, mirroring ``from_global_exp_params={"test_wait": "dummy_param"}``.
    """
    pending = []
    for smp in plate_sample_no_list:
        for i in range(cycles):
            if i == 0:
                dummy = 0.0
            else:
                dummy = orch.global_params.get("test_wait", 0.0)  # from_global
            print(f"sample {smp} cycle {i}: dummy_param={dummy}")
            pending.append(
                await test_sub_noblocking(orch, wait_time=wait_time, dummy_param=dummy)
            )
    # drain any outstanding non-blocking waits before returning
    await asyncio.gather(*pending)


async def test_sub_conditional_stop(orch: MicroOrch) -> bool:
    """Python equivalent of ``TEST_exp.TEST_sub_conditional_stop``.

    Sets ``global_test`` then evaluates the conditional stop. Returns ``True``
    when the sequence should halt (so the trailing waits are skipped).
    """
    orch.global_params["global_test"] = True  # add_global_param
    # conditional_stop: stop when global_test == True (read from globals)
    should_stop = orch.global_params.get("global_test") is True
    if should_stop:
        print("conditional_stop met -> halting before trailing waits")
        return True
    for _ in range(5):
        await asyncio.sleep(1)  # trailing ORCH/wait actions (skipped when stopped)
    return False


async def main() -> None:
    """Run both TEST equivalents against a server-less MicroOrch global store."""
    async with MicroOrch(
        server_key="micro_test",
        host="127.0.0.1",
        port=9120,
        world_cfg=WORLD_CFG,
    ) as orch:
        print("=== TEST_consecutive_noblocking equivalent ===")
        await test_consecutive_noblocking(
            orch, wait_time=0.2, cycles=2, plate_sample_no_list=(1, 2)
        )
        print(f"final globals: {dict(orch.global_params)}")

        print("\n=== TEST_sub_conditional_stop equivalent ===")
        stopped = await test_sub_conditional_stop(orch)
        print(f"sequence stopped early: {stopped}")


if __name__ == "__main__":
    asyncio.run(main())
