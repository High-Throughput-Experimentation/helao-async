"""Motion controls for a server whose scale is stated as **counts per mm**.

Declared as ``control_vis: motion_control_inverse_scale``. The config shape it
serves::

    params:
      axes:
        z: {serial_no: ..., pos_scale: 1228800.0, vel_scale: ..., ...}

Every key of ``axes`` becomes one axis row; the behaviour is entirely in
:class:`~helao.core.servers.motion_control_vis.MotionPanel`.

**The inversion is in the name on purpose.** ``pos_scale`` is *counts per
millimetre*, the reciprocal of the ``count_to_mm`` the other two schemas
declare, and both are plain positive floats -- so an inversion dropped or
wrongly added yields a perfectly ordinary-looking number that is wrong by the
square of the scale, on a control that drives real hardware. Naming the module
for the reciprocal means nobody opens this file without meeting that fact.
:func:`~helao.ui.shared.motion_control.mm_per_count` is the one place the
inversion is performed; do not read ``pos_scale`` anywhere else.

The keying is *not* what discriminates here -- ``axes`` is name-keyed, which it
shares with ``motion_control_name_scale`` -- which is why this module breaks the
trio's keying-based naming and is named for the inversion instead.

**Same vendor as** ``motion_control_name_scale`` -- both are Thorlabs Kinesis --
**but a different config schema, and the schema is what this name
distinguishes.** The vendor cannot discriminate between the two; the shape of
the config can.
"""

__all__ = ["C_vis"]

from helao.core.servers.motion_control_vis import MotionPanel


class C_vis(MotionPanel):
    """Move controls for every ``axes`` entry on the target server."""

    AXIS_SOURCE = "inverse_scale"
    TITLE = "Motion controls"
