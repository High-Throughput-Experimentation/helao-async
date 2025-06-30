import time
from types import MethodType
from typing import Optional
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

class Executor:
    """
    Executor class for managing and executing asynchronous tasks with customizable setup, execution, polling, and cleanup methods.

    Attributes:
        active: The active task or action to be executed.
        poll_rate (float): The rate at which polling occurs, in seconds.
        oneoff (bool): Indicates if the task is a one-time execution.
        exec_id (str): Unique identifier for the executor instance.
        concurrent (bool): Indicates if multiple executors can run concurrently.
        start_time (float): The start time of the execution.
        duration (float): The duration of the action, default is -1 (indefinite).

    Methods:
        __init__(self, active, poll_rate=0.2, oneoff=True, exec_id=None, concurrent=True, **kwargs):
            Initializes the Executor instance with the given parameters.

        async _pre_exec(self):
            Performs setup methods before execution. Returns error state.

        set_pre_exec(self, pre_exec_func):
            Overrides the generic setup method with a custom function.

        async _exec(self):
            Performs the main execution of the task. Returns data and error state.

        set_exec(self, exec_func):
            Overrides the generic execute method with a custom function.

        async _poll(self):
            Performs one polling iteration. Returns data, error state, and status.

        set_poll(self, poll_func):
            Overrides the generic polling method with a custom function.

        async _post_exec(self):
            Performs cleanup methods after execution. Returns error state.

        set_post_exec(self, post_exec_func):
            Overrides the generic cleanup method with a custom function.

        async _manual_stop(self):
            Performs manual stop of the device. Returns error state.

        set_manual_stop(self, manual_stop_func):
            Overrides the generic manual stop method with a custom function.
    """

    def __init__(
        self,
        active,
        poll_rate: float = 0.2,
        oneoff: bool = True,
        exec_id: Optional[str] = None,
        concurrent: bool = True,
        **kwargs
    ):
        """
        Initializes the Executor.

        Args:
            active: The active action to be executed.
            poll_rate (float, optional): The rate at which to poll for updates. Defaults to 0.2.
            oneoff (bool, optional): Whether the executor is a one-off execution. Defaults to True.
            exec_id (str, optional): The unique identifier for the executor. If None, it will be generated. Defaults to None.
            concurrent (bool, optional): Whether multiple executors can run concurrently. Defaults to True.
            **kwargs: Additional keyword arguments.

        Attributes:
            active: The active action to be executed.
            oneoff (bool): Whether the executor is a one-off execution.
            poll_rate (float): The rate at which to poll for updates.
            exec_id (str): The unique identifier for the executor.
            start_time (float): The start time of the execution.
            duration (float): The duration of the action.
            concurrent (bool): Whether multiple executors can run concurrently.
        """
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
        """
        Asynchronous method to run setup procedures for the executor.

        This method prints a message indicating that the generic executor is running 
        setup methods and initializes the setup error code to `ErrorCodes.none`.

        Returns:
            dict: A dictionary containing the setup error code with the key "error".
        """
        LOGGER.info("generic Executor running setup methods.")
        return {"error": ErrorCodes.none}

    def set_pre_exec(self, pre_exec_func):
        """
        Sets the pre-execution function.

        This method assigns a function to be executed before the main execution.
        
        Args:
            pre_exec_func (function): A function to be executed before the main execution.
        """
        self._pre_exec = MethodType(pre_exec_func, self)

    async def _exec(self):
        """
        Asynchronous method to execute a task.

        Returns:
            dict: A dictionary containing the keys "data" and "error". 
                  "data" is an empty dictionary, and "error" is set to ErrorCodes.none.
        """
        return {"data": {}, "error": ErrorCodes.none}

    def set_exec(self, exec_func):
        """
        Sets the execution function for the instance.

        Args:
            exec_func (function): The function to be set as the execution method.
        """
        self._exec = MethodType(exec_func, self)

    async def _poll(self):
        """
        Asynchronously polls for a status update.

        Returns:
            dict: A dictionary containing the following keys:
                - "data" (dict): An empty dictionary.
                - "error" (ErrorCodes): The error code, set to ErrorCodes.none.
                - "status" (HloStatus): The status, set to HloStatus.finished.
        """
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    def set_poll(self, poll_func):
        """
        Sets the polling function for the executor.

        Args:
            poll_func (function): A function to be used for polling. This function
                                  should accept no arguments and will be bound to
                                  the instance of the executor.
        """
        self._poll = MethodType(poll_func, self)

    async def _post_exec(self):
        """
        Asynchronous method to perform post-execution cleanup.

        This method sets the cleanup error code to `ErrorCodes.none` and returns
        a dictionary containing an empty data dictionary and the cleanup error code.

        Returns:
            dict: A dictionary with keys "data" (an empty dictionary) and "error" 
                  (the cleanup error code set to `ErrorCodes.none`).
        """
        self.cleanup_err = ErrorCodes.none
        return {"data": {}, "error": self.cleanup_err}

    def set_post_exec(self, post_exec_func):
        """
        Sets the post-execution function.

        This method assigns a given function to be executed after the main execution.
        
        Args:
            post_exec_func (function): A function to be set as the post-execution function.
        """
        self._post_exec = MethodType(post_exec_func, self)

    async def _manual_stop(self):
        """
        Asynchronously stops the current operation manually.

        This method sets the stop error code to `ErrorCodes.none` and returns a dictionary
        containing the error code.

        Returns:
            dict: A dictionary with the key "error" and the value set to `self.stop_err`.
        """
        self.stop_err = ErrorCodes.none
        return {"error": self.stop_err}

    def set_manual_stop(self, manual_stop_func):
        """
        Sets a manual stop function for the executor.

        Args:
            manual_stop_func (function): A function that will be used to manually stop the executor. 
                                         This function should take no arguments.
        """
        self._manual_stop = MethodType(manual_stop_func, self)
