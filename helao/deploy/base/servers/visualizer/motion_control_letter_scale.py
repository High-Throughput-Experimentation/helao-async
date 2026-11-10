"""Motion controls for a server whose axes map to controller *letters*.

Declared as ``control_vis: motion_control_letter_scale``. The config shape it
serves::

    params:
      axis_id:      {x: C, y: B, z: A, Rz: D}   # axis name -> controller letter
      count_to_mm:  {C: 1.5628e-04, ...}        # keyed by that LETTER

Every key of ``axis_id`` becomes one axis row; the behaviour is entirely in
:class:`~helao.ui.bokeh.motion_control_vis.MotionPanel`.

Deliberately named for the *shape of the config* rather than for a driver,
matching ``digital_out_control``. Here the discriminator is how the scale is
declared and keyed, because that is exactly what ``discover_axes`` and
``mm_per_count`` branch on -- nothing else about the schema reaches this
feature. This one is separated from ``motion_control_name_scale`` by its
keying: ``count_to_mm`` is looked up by the controller letter, not by the axis
name.

``count_to_mm`` here is millimetres per count, the same orientation as
``motion_control_name_scale`` and the *reciprocal* of
``motion_control_inverse_scale``'s ``pos_scale``.
"""

__all__ = ["C_vis"]

from helao.ui.bokeh.motion_control_vis import MotionPanel


class C_vis(MotionPanel):
    """Move controls for every ``axis_id`` entry on the target server."""

    AXIS_SOURCE = "letter_scale"
    TITLE = "Motion controls"
