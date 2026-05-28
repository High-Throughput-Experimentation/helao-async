"""Threaded user-script runner for LEANCAT.

Exposes shared :class:`threading.Event` flags (abort/terminate/error) and a
:class:`UserScript` thread that ``exec``-s a user-supplied Python file and
sets the appropriate event on completion or failure.
"""

import threading
from ..logger import script_log

abort_event = threading.Event()
terminate_event = threading.Event()
error_event = threading.Event()


class UserScript(threading.Thread):
    """Background thread that ``exec``-s a Python script file.

    Sets :data:`terminate_event` on successful completion or
    :data:`error_event` (logging the exception) on failure.
    """

    def __init__(self, script_path):
        """Store the path to the script that will be executed by :meth:`run`.

        Args:
            script_path: Absolute or relative path to the script file.
        """
        threading.Thread.__init__(self)
        self._script_path = script_path

    def run(self):
        """Read the script file and execute it in the current namespace."""
        script_str = open(self._script_path, "r").read()

        try:
            exec(script_str)
            script_log.info("Script finished successfully")
            terminate_event.set()
        except Exception as e:
            script_log.error(f"Script finished with an error: {e}")
            error_event.set()
