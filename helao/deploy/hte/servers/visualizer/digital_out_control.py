"""Control panel for any action server with a single ``dev_do`` config block.

Declared as ``control_vis: digital_out_control``. Every key in that server's
``dev_do`` block becomes one toggle; the behaviour is entirely in
:class:`~helao.core.servers.io_control_vis.DigitalOutPanel`.

Deliberately named for the *shape of the config* rather than for a driver, and
so it serves the Galil IO server here and the Advantech IO server in its own
deployment without a second near-identical module. A server whose outputs are
spread across several groups needs its own panel naming them — see
``nidaqmx_control``.

Both servers this currently serves read their outputs back from hardware, so the
panel shows real state when it opens, including a line a running sequence set.
"""

__all__ = ["C_vis"]

from helao.core.servers.io_control_vis import DigitalOutPanel


class C_vis(DigitalOutPanel):
    """Toggles for every ``dev_do`` entry on the target server."""

    DO_GROUPS = ("dev_do",)
    TITLE = "Digital output controls"
