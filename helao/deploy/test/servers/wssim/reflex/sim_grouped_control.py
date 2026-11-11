"""Reflex control panel for a simulated server with several ``dev_*`` output groups.

A test-deployment stand-in for a server that spreads its digital outputs across
one config group per function, so the framework's grouped-control rendering has a
panel that does not depend on any instrument deployment. Answers to
``control_vis: sim_grouped_control``. The group list is the whole contribution;
rendering and endpoint calls are in ``helao.ui.reflex.control``.
"""

__all__ = ["DO_GROUPS", "TITLE"]

#: The config blocks this server keeps its digital outputs in, one per function.
DO_GROUPS = ("dev_pump", "dev_gasvalve")

#: Heading for this server's block of controls.
TITLE = "Digital output controls"
