"""Reflex motion controls for a server stating scale as **counts per mm**.

The Reflex twin of ``servers/visualizer/motion_control_inverse_scale.py``, and
answering to the same ``control_vis: motion_control_inverse_scale`` key --
different subpackage, one name, exactly as the ``*_vis`` panels pair across the
two stacks. A station gains the Reflex panel by adding a ``reflex:`` server and
changing nothing else.

The config shape it serves::

    params:
      axes:
        z: {serial_no: ..., pos_scale: 1228800.0, vel_scale: ..., ...}

**The inversion is in the name on purpose.** ``pos_scale`` is *counts per
millimetre*, the reciprocal of the ``count_to_mm`` the other two schemas
declare, and both are plain positive floats -- so an inversion dropped or
wrongly added yields a perfectly ordinary-looking number that is wrong by the
square of the scale, on a control that drives real hardware. Naming the module
for the reciprocal means nobody opens this file without meeting that fact.
:func:`~helao.core.servers.motion_control.mm_per_count` is the one place the
inversion is performed; do not read ``pos_scale`` anywhere else.

The keying is *not* what discriminates here -- ``axes`` is name-keyed, which it
shares with ``motion_control_name_scale`` -- which is why this module breaks the
trio's keying-based naming and is named for the inversion instead.

**Same vendor as** ``motion_control_name_scale`` -- both are Thorlabs Kinesis --
**but a different config schema, and the schema is what this name
distinguishes.** The vendor cannot discriminate between the two; the shape of
the config can.

All this module contributes is *which* schema the axes are declared in. The
rendering and the endpoint calls are in ``helao.core.servers.reflex.control``
and ``helao.core.servers.motion_control``, shared with the Bokeh half.
"""

__all__ = ["DO_GROUPS", "AXIS_SOURCE", "TITLE"]

#: No digital outputs on a motion server; the shared panel builder still asks.
DO_GROUPS = ()

#: The config schema this server's axes are declared in.
AXIS_SOURCE = "inverse_scale"

#: Heading for this server's block of controls.
TITLE = "Motion controls"
