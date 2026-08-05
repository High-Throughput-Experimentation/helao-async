"""Reflex motion controls for a server whose axes map to controller *letters*.

The Reflex twin of ``servers/visualizer/motion_control_letter_scale.py``, and
answering to the same ``control_vis: motion_control_letter_scale`` key --
different subpackage, one name, exactly as the ``*_vis`` panels pair across the
two stacks. A station gains the Reflex panel by adding a ``reflex:`` server and
changing nothing else.

The config shape it serves::

    params:
      axis_id:      {x: C, y: B, z: A, Rz: D}   # axis name -> controller letter
      count_to_mm:  {C: 1.5628e-04, ...}        # keyed by that LETTER

Named for the *shape of the config* rather than for a driver, matching
``digital_out_control``. The discriminator is how the scale is declared and
keyed, because that is exactly what ``discover_axes`` and ``mm_per_count``
branch on. This one is separated from ``motion_control_name_scale`` by its
keying: ``count_to_mm`` is looked up by the controller letter, not by the axis
name. Its ``count_to_mm`` is millimetres per count -- the *reciprocal* of
``motion_control_inverse_scale``'s ``pos_scale``.

All this module contributes is *which* schema the axes are declared in. The
rendering and the endpoint calls are in ``helao.core.servers.reflex.control``
and ``helao.core.servers.motion_control``, shared with the Bokeh half.
"""

__all__ = ["DO_GROUPS", "AXIS_SOURCE", "TITLE"]

#: No digital outputs on a motion server; the shared panel builder still asks.
DO_GROUPS = ()

#: The config schema this server's axes are declared in.
AXIS_SOURCE = "letter_scale"

#: Heading for this server's block of controls.
TITLE = "Motion controls"
