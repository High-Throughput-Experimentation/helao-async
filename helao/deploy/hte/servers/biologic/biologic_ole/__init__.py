"""BioLogic potentiostat driver over the EC-Lab OLE COM interface.

An alternative to the sibling ``biologic`` package, which drives the same
instruments through easy-biologic / EClib. This one pilots the EC-Lab
application, so it reaches any instrument and any technique EC-Lab supports --
at the cost of requiring EC-Lab installed, registered as an OLE COM server
(``ECLab /regserver``) and running on the same Windows host.

See ``docs/superpowers/specs/2026-09-07-biologic-olecom-driver-design.md``.
"""
