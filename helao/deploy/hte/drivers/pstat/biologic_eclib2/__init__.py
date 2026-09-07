"""BioLogic backend built on the EC-Lib 2.0 SDK (EClib2).

A second, independent backend beside ``biologic/`` (easy-biologic / EClib1).
EClib2 is not backwards compatible with EClib1 -- it drops ``blfind``,
``BL_GetData`` and the ``.ecc`` technique files, and ships its own ctypes
Python layer instead -- so this package reimplements the driver against the
new API rather than adapting the old one.

Nothing here imports the vendor SDK at module scope: it is loaded from a
configured path by :mod:`vendor`, and :mod:`sim` stands in for it off-station.
"""
