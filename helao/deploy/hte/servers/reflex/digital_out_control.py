"""Reflex control panel for any server with a single ``dev_do`` config block.

The Reflex twin of ``servers/visualizer/digital_out_control.py``, and answering
to the same ``control_vis: digital_out_control`` key — different subpackage, one
name, exactly as the ``*_vis`` panels pair across the two stacks. A station
gains the Reflex panel by adding a ``reflex:`` server and changing nothing else.

All this module contributes is *which* config blocks hold the outputs. The
rendering and the endpoint calls are in ``helao.core.servers.reflex.control``
and ``helao.ui.shared.io_control``, shared with the Bokeh half.
"""

__all__ = ["DO_GROUPS", "TITLE"]

#: The one block this server keeps its digital outputs in.
DO_GROUPS = ("dev_do",)

#: Heading for this server's block of controls.
TITLE = "Digital output controls"
