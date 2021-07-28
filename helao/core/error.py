from enum import Enum

class error_codes(str, Enum):
    none = "none"
    start_timeout = "start_timeout"
    continue_timeout = "continue_timeout"
    done_timeout = "done_timeout"
    in_progress = "already_in_progress"
    not_available = "not_available"
    ssh_error = "ssh_error"
