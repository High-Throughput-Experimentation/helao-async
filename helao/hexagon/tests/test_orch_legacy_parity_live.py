"""Two pre-hexagon orchestrator behaviours the native hosts had lost.

Both were invisible to the route checklist and to the member-coverage
ratchet: the routes existed and the members existed, only what they *did*
had changed.

* Legacy ``Base.myinit``/``Orch.myinit`` installed an asyncio loop exception
  handler. Without one, a traceback from a fire-and-forget task goes to
  asyncio's default handler, whose ``asyncio`` logger carries no HELAO
  handler -- so it reached neither the server's rotating log nor
  email/webhook alerting.
* The six queue move/remove routes answered ``{"n_<kind>": N}``. The native
  host returned the collaborator's ``None``, i.e. JSON ``null``.
"""

import asyncio
import logging as _logging

import pytest

from helao.helpers.premodels import Sequence
from helao.helpers.time_utils import gen_uuid
from helao.hexagon.tests.live_group import build_ws_sequence, live_group, orch_call


@pytest.mark.asyncio
async def test_loop_exception_handler_is_installed_and_logs(tmp_path):
    async with live_group(str(tmp_path)) as g:
        loop = asyncio.get_running_loop()
        handler = loop.get_exception_handler()
        assert handler is not None, "no asyncio loop exception handler installed"
        assert getattr(handler, "__func__", handler).__name__ == (
            "_loop_exception_handler"
        )

        # The host IS the FastAPI app, so the handler must NOT be called
        # `exception_handler`: that name is Starlette's decorator, and
        # shadowing it would silently disable the action-route estop handler.
        from starlette.exceptions import HTTPException as StarletteHTTPException

        assert callable(g.orch.exception_handler(StarletteHTTPException))

        # A traceback from a task nobody awaits must reach HELAO's logger.
        # Captured off that logger directly, not via caplog: make_logger sets
        # `propagate = False` (helao_logging.py:583), so nothing reaches the
        # root handler caplog installs -- which is the same reason asyncio's
        # own default handler was invisible here.
        from helao.hexagon.app import action_host as _ah

        records = []

        class _Capture(_logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        # raised, not merely constructed: an exception that was never raised
        # has no __traceback__, and the traceback is the point
        try:
            raise RuntimeError("boom-probe")
        except RuntimeError as exc:
            probe = exc

        cap = _Capture(level=_logging.ERROR)
        _ah.LOGGER.addHandler(cap)
        try:
            handler(loop, {"message": "probe", "exception": probe})
        finally:
            _ah.LOGGER.removeHandler(cap)
        text = "\n".join(records)
        assert "boom-probe" in text, text
        assert "Got exception from coroutine" in text, text
        assert "Traceback" in text, "no traceback formatted"

        # asyncio also calls the handler with no exception at all
        # ("Task was destroyed but it is pending!"); legacy raised inside the
        # handler there and lost the report.
        handler(loop, {"message": "no exception key here"})


@pytest.mark.asyncio
async def test_queue_move_and_remove_routes_answer_with_counts(tmp_path):
    async with live_group(str(tmp_path)) as g:
        seq = build_ws_sequence(3)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})

        assert await orch_call(
            "move_sequence", params={"from_idx": 0, "to_idx": 0}
        ) == {"n_sequences": 1}
        # queues are unpacked only once the loop runs, so exercise the
        # experiment/action shapes against their real (empty) deques
        assert await orch_call(
            "move_experiment", params={"from_idx": 0, "to_idx": 0}
        ) == {"n_experiments": len(g.orch.experiment_dq)}
        assert await orch_call("remove_experiment", params={"idx": 0}) == {
            "n_experiments": len(g.orch.experiment_dq)
        }
        assert await orch_call("move_action", params={"from_idx": 0, "to_idx": 0}) == {
            "n_actions": len(g.orch.action_dq)
        }
        assert await orch_call("remove_action", params={"idx": 0}) == {
            "n_actions": len(g.orch.action_dq)
        }
        # removing the queued sequence must be reflected in the count
        assert await orch_call("remove_sequence", params={"idx": 0}) == {
            "n_sequences": 0
        }
        assert len(g.orch.sequence_dq) == 0
