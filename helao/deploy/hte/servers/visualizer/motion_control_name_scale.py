"""Motion controls for a server whose axes map to *serial numbers*.

Declared as ``control_vis: motion_control_name_scale``. The config shape it
serves::

    params:
      axis_id:      {x: "45470574", ...}   # axis name -> device serial number
      count_to_mm:  {x: 3.4e-05, ...}      # keyed by the AXIS NAME

Every key of ``axis_id`` becomes one axis row; the behaviour is entirely in
:class:`~helao.core.servers.motion_control_vis.MotionPanel`.

**Same vendor as** ``motion_control_inverse_scale`` -- both are Thorlabs
Kinesis stages -- **but a different config schema, and the schema is what this
name distinguishes.** Naming either module for the vendor would name them both
the same thing, so the convention ``digital_out_control`` sets (named for the
shape of the config, not for a driver) is not merely preferred here, it is the
only one that separates them. This one keys ``count_to_mm`` by axis name, where
``motion_control_letter_scale`` keys it by controller letter; that keying is
their only real difference.

``count_to_mm`` here is millimetres per count -- the *reciprocal* of
``motion_control_inverse_scale``'s ``pos_scale``, despite the shared vendor.

**This module ships in hte with no hte consumer.** No station config in this
deployment declares it; it is reached only through the cross-deployment
fallback, by which a deployment with no panel module of its own resolves the
key against hte. It lives here because hte is the canonical home for all six
motion panels, so the trio stays readable side by side.
"""

__all__ = ["C_vis"]

from helao.core.servers.motion_control_vis import MotionPanel


class C_vis(MotionPanel):
    """Move controls for every ``axis_id`` entry on the target server."""

    AXIS_SOURCE = "name_scale"
    TITLE = "Motion controls"
