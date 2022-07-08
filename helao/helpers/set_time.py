__all__ = ["set_time"]

from datetime import datetime


def set_time(offset: float = 0):
    dtime = datetime.now()
    if offset is not None:
        dtime = datetime.fromtimestamp(dtime.timestamp() + offset)
    return dtime
