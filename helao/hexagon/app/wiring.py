"""Fail-loud port wiring (spec §4.5, F2b countermeasure).

Composition RAISES at startup on any port a composition consumes but has no
adapter for — there is no silent default and no fake fallback (fakes are
opt-in via helao.hexagon.adapters.fakes and self-announce with WARNING
banners). ``require()`` names the composition's consumed set; ports without a
P1b1 consumer are simply not in the required set yet (they gain consumers in
P1b2/P2 and join the set then).
"""

from dataclasses import dataclass, fields
from typing import Optional

from helao.hexagon.adapters.errors import HexagonDeferred, UnwiredPortError
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.auxiliary import HealthPort, StatePersistencePort
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.config import ConfigPort
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.ports.hardware import HardwarePort
from helao.hexagon.ports.logging import LoggingPort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.ports.transport import TransportPort
from helao.hexagon.ports.ui_host import UiHostPort

__all__ = [
    "ACTION_REQUIRED",
    "HexagonDeferred",
    "ORCH_REQUIRED",
    "PortWiring",
    "UnwiredPortError",
    "VIS_REQUIRED",
]


# Ports each P1b1 composition genuinely consumes (fail-loud is meaningful,
# not vacuous). Extended as adapters gain runtime consumers in P1b2/P2.
ORCH_REQUIRED = (
    "config",
    "logging",
    "clock",
    "transport",
    "state_persistence",
    "status",
    "health",  # P2a: HexHealthMonitor + driver-health gate consume it
)
ACTION_REQUIRED = (
    "config",
    "logging",
    "clock",
    "transport",
    "status",
    # P2b-1: the native write runtime carries all Active write traffic —
    # a missing adapter must abort startup, never fall through to legacy
    "artifact_store",
    "data_sink",
)
# P7e: a Bokeh UI-hosting composition (makeVisApp). Deliberately SHORT — the
# set names what this composition genuinely consumes, so the gate stays
# meaningful rather than vacuous: `config`/`logging` are read while the
# composition is built, and `ui_host` (P7d) is the port that makes it a UI
# host at all. The write-path ports are pointedly NOT here: a read-only UI
# process has no business owning an artifact store, and requiring one would
# make the gate assert something untrue about the process.
VIS_REQUIRED = (
    "config",
    "logging",
    "ui_host",
)


@dataclass
class PortWiring:
    """One Optional slot per P1a port Protocol. ``None`` == unwired."""

    config: Optional[ConfigPort] = None
    logging: Optional[LoggingPort] = None
    clock: Optional[ClockPort] = None
    transport: Optional[TransportPort] = None
    state_persistence: Optional[StatePersistencePort] = None
    artifact_store: Optional[ArtifactStorePort] = None
    data_sink: Optional[DataSinkPort] = None
    sync: Optional[SyncPort] = None
    status: Optional[StatusPort] = None
    hardware: Optional[HardwarePort] = None
    sample_state: Optional[SampleStatePort] = None
    health: Optional[HealthPort] = None
    # P7d: required only when a composition declares an aligner or is a UI
    # host (a Bokeh vis/aligner or Reflex process) — never a blanket
    # ACTION_REQUIRED/ORCH_REQUIRED member, enforced instead at the sites
    # that actually need one via PortWiring.require("ui_host").
    ui_host: Optional[UiHostPort] = None

    def require(self, *names: str) -> None:
        known = {f.name for f in fields(self)}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise UnwiredPortError(f"unknown port name(s): {sorted(unknown)}")
        missing = [n for n in names if getattr(self, n) is None]
        if missing:
            raise UnwiredPortError(
                "composition has unwired port(s): "
                f"{sorted(missing)} — wire a real adapter (fakes are opt-in "
                "and never a default; spec §10.2)"
            )
