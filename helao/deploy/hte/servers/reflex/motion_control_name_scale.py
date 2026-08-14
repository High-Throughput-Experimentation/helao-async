"""Reflex motion controls for a server whose axes map to *serial numbers*.

The Reflex twin of ``servers/visualizer/motion_control_name_scale.py``, and
answering to the same ``control_vis: motion_control_name_scale`` key --
different subpackage, one name, exactly as the ``*_vis`` panels pair across the
two stacks. A station gains the Reflex panel by adding a ``reflex:`` server and
changing nothing else.

The config shape it serves::

    params:
      axis_id:      {x: "45470574", ...}   # axis name -> device serial number
      count_to_mm:  {x: 3.4e-05, ...}      # keyed by the AXIS NAME

**Same vendor as** ``motion_control_inverse_scale`` -- both are Thorlabs
Kinesis stages -- **but a different config schema, and the schema is what this
name distinguishes.** Naming either module for the vendor would name them both
the same thing, so the convention ``digital_out_control`` sets (named for the
shape of the config, not for a driver) is not merely preferred here, it is the
only one that separates them. This one keys ``count_to_mm`` by axis name, where
``motion_control_letter_scale`` keys it by controller letter; that keying is
their only real difference. Its ``count_to_mm`` is millimetres per count -- the
*reciprocal* of ``motion_control_inverse_scale``'s ``pos_scale``, despite the
shared vendor.

**This module ships in hte with no hte consumer.** No station config in this
deployment declares it; it is reached only through the cross-deployment
fallback, by which a deployment with no panel module of its own resolves the
key against hte. It lives here because hte is the canonical home for all six
motion panels, so the trio stays readable side by side.

All this module contributes is *which* schema the axes are declared in. The
rendering and the endpoint calls are in ``helao.core.servers.reflex.control``
and ``helao.ui.shared.motion_control``, shared with the Bokeh half.
"""

__all__ = ["DO_GROUPS", "AXIS_SOURCE", "TITLE"]

#: No digital outputs on a motion server; the shared panel builder still asks.
DO_GROUPS = ()

#: The config schema this server's axes are declared in.
AXIS_SOURCE = "name_scale"

#: Heading for this server's block of controls.
TITLE = "Motion controls"
