import time
from types import MethodType
from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus


class Executor:
    """Generic template for action executor (steps 5-6 of action_loop_task).

    Hooks
    1. Device setup calls (optional)
        a. Suspend live polling task (optional)
    2. Execute action start, return {"data": ..., "error": ...}
    3. Polling (optional)
        a. Standard return dict has {"data": ..., "status": ..., "error": ...}
        b. Error handling
        c. Check for external stop if looping.
    4. Resume live polling task (optional)
        a. Cleanup calls (optional)
    """

    def __init__(
        self,
        active,
        poll_rate: float = 0.2,
        oneoff: bool = True,
        exec_id: str = None,
        concurrent: bool = True,
        **kwargs
    ):
        self.active = active
        self.oneoff = oneoff
        self.poll_rate = poll_rate
        if exec_id is None:
            self.exec_id = f"{active.action.action_name} {active.action.action_uuid}"
        else:
            self.exec_id = exec_id
        self.active.action.exec_id = self.exec_id
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        # whether or not we can run multiple executors concurrently, regardless of executor type
        self.concurrent = concurrent

    async def _pre_exec(self):
        "Setup methods, return error state."
        self.active.base.print_message("generic Executor running setup methods.")
        self.setup_err = ErrorCodes.none
        return {"error": self.setup_err}

    def set_pre_exec(self, pre_exec_func):
        "Override the generic setup method."
        self._pre_exec = MethodType(pre_exec_func, self)

    async def _exec(self):
        "Perform device read/write."
        return {"data": {}, "error": ErrorCodes.none}

    def set_exec(self, exec_func):
        "Override the generic execute method."
        self._exec = MethodType(exec_func, self)

    async def _poll(self):
        "Perform one polling iteration."
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    def set_poll(self, poll_func):
        "Override the generic execute method."
        self._poll = MethodType(poll_func, self)

    async def _post_exec(self):
        "Cleanup methods, return error state."
        self.cleanup_err = ErrorCodes.none
        return {"data": {}, "error": self.cleanup_err}

    def set_post_exec(self, post_exec_func):
        "Override the generic cleanup method."
        self._post_exec = MethodType(post_exec_func, self)

    async def _manual_stop(self):
        "Perform device manual stop, return error state."
        self.stop_err = ErrorCodes.none
        return {"error": self.stop_err}

    def set_manual_stop(self, manual_stop_func):
        "Override the generic manual stop method."
        self._manual_stop = MethodType(manual_stop_func, self)
