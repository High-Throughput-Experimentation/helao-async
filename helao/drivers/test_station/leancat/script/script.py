import threading
from ..logger import script_log

abort_event = threading.Event()
terminate_event = threading.Event()
error_event = threading.Event()


class UserScript(threading.Thread):
    def __init__(self, script_path):
        threading.Thread.__init__(self)
        self._script_path = script_path

    def run(self):
        script_str = open(self._script_path, "r").read()

        try:
            exec(script_str)
            script_log.info("Script finished successfully")
            terminate_event.set()
        except Exception as e:
            script_log.error(f"Script finished with an error: {e}")
            error_event.set()
