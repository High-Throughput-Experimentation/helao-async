"""``gclib_api`` server param -> Galil command channel (wrapper 1.0 or 2.x).

Both wrappers install as ``import gclib``, so one env holds one of them; the
configured value must match the installed wrapper (the channel's ``open``
says so if it does not). Absent -> "1", today's behaviour.
"""

from helao.deploy.hte.servers.galil_motion.galil_command_channel import (
    GclibCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel2 import (
    Gclib2CommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilCommandChannel,
)

__all__ = ["CHANNELS", "DEFAULT_GCLIB_API", "make_channel"]

CHANNELS = {"1": GclibCommandChannel, "2": Gclib2CommandChannel}
DEFAULT_GCLIB_API = "1"


def make_channel(config: dict) -> GalilCommandChannel:
    raw = config.get("gclib_api", DEFAULT_GCLIB_API)
    name = str(raw) if type(raw) is int else raw
    if not isinstance(name, str) or name not in CHANNELS:
        raise ValueError(
            f"unknown gclib_api {raw!r}; expected one of "
            + ", ".join(repr(k) for k in CHANNELS)
        )
    return CHANNELS[name]()
