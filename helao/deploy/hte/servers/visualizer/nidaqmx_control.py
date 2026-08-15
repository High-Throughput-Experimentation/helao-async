"""Control panel for an NI-DAQmx server's digital outputs.

Declared as ``control_vis: nidaqmx_control`` on a ``nidaqmx_server``. Unlike the
Galil and Advantech servers, this one has no single ``dev_do`` block — its
outputs are spread across one config group per function — so the groups are
listed here and rendered as separate sections. The list is
:data:`~helao.deploy.hte.servers.action.nidaqmx_server.DO_GROUPS` itself rather
than a copy, so a group added to the server cannot be missing from the panel.

**This server cannot read its outputs back.** A DO line is driven by a one-shot
``nidaqmx.Task`` that is opened, written and closed, and NI-DAQmx offers no
readback for one held that way, so the server reports what it last wrote. A line
untouched since the server started opens as unknown — which is the truth, and
which the panel shows rather than assuming off.
"""

__all__ = ["C_vis"]

from helao.ui.bokeh.io_control_vis import DigitalOutPanel
from helao.deploy.hte.servers.action.nidaqmx_server import DO_GROUPS as SERVER_DO_GROUPS


class C_vis(DigitalOutPanel):
    """Toggles for every configured digital output on an NI-DAQmx server."""

    # Aliased on import rather than written as ``DO_GROUPS = DO_GROUPS``: that
    # does resolve (a class body's RHS falls back to module scope), but it reads
    # like a mistake.
    DO_GROUPS = SERVER_DO_GROUPS
    TITLE = "Digital output controls"
