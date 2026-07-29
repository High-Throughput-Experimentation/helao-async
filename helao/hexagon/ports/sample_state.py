"""SampleState port (spec §4.3.11): the Archive boundary.

The contract itself is declared in
`helao.hexagon.domain.sample_state.SampleStateProtocol`, because the domain
(`pal_reconciliation.PalReconciler`) is written against it and is what fixes its
shape. This module is the port-layer name adapters and composition bind to;
`ports/` may import `domain/`, whereas the reverse is a rejected inversion. It
is an alias, not a subclass, so `isinstance` checks against either name behave
identically and there is no second definition to drift.

The boundary is SAMPLE-server-behind-RPC -- exactly what PAL already consumes
via sample_shim.SampleArchiveShim (fail-loud RPC client, call-time address
resolution, typed rehydration). Signatures mirror the shim's public methods
verbatim (cross-checked against
helao/deploy/hte/drivers/robot/sample_shim.py, dropping only the shim's
`*args, **kwargs` catch-alls) so the P1b adapter is the shim itself. Archive
is NEVER ported as a driver. The shim's public surface has no methods beyond
those in the protocol (no custom_unloadall/custom_load exist on it).
"""

from helao.hexagon.domain.sample_state import SampleStateProtocol

__all__ = ["SampleStatePort"]

#: Port-layer name for the domain-declared sample-state contract.
SampleStatePort = SampleStateProtocol
