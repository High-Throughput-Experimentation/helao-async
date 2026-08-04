"""Reflex control panel for an NI-DAQmx server's digital outputs.

The Reflex twin of ``servers/visualizer/nidaqmx_control.py``, answering to the
same ``control_vis: nidaqmx_control`` key. Unlike the single-block servers, this
one spreads its outputs across one config group per function, so the group list
is the whole contribution — and it is imported from the action server rather
than copied, so a group added there cannot go missing from the panel.

**This server cannot read its outputs back.** A line is driven by a one-shot
``nidaqmx.Task`` that is opened, written and closed, and NI-DAQmx offers no
readback for one held that way, so the server reports what it last wrote. A line
untouched since startup opens as unknown — which is the truth, and which the
panel shows rather than assuming off.
"""

__all__ = ["DO_GROUPS", "TITLE"]

from helao.deploy.hte.servers.action.nidaqmx_server import DO_GROUPS as SERVER_DO_GROUPS

#: The nine blocks this server keeps its digital outputs in.
DO_GROUPS = SERVER_DO_GROUPS

#: Heading for this server's block of controls.
TITLE = "Digital output controls"
