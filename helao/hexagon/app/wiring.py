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

from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.config import ConfigPort
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.ports.hardware import HardwarePort
from helao.hexagon.ports.logging import LoggingPort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.ports.transport import TransportPort
from helao.hexagon.ports.auxiliary import StatePersistencePort

__all__ = [
    "ACTION_REQUIRED",
    "HexagonDeferred",
    "ORCH_REQUIRED",
    "PortWiring",
    "UnwiredPortError",
]


class UnwiredPortError(RuntimeError):
    """A consumed port has no adapter wired — composition must not start."""


class HexagonDeferred(NotImplementedError):
    """A port member whose legacy bridge is deliberately deferred to a later
    slice (documented at the raise site) — loud, never silent."""


# Ports each P1b1 composition genuinely consumes (fail-loud is meaningful,
# not vacuous). Extended as adapters gain runtime consumers in P1b2/P2.
ORCH_REQUIRED = ("config", "logging", "clock", "transport", "state_persistence")
ACTION_REQUIRED = ("config", "logging", "clock", "transport")


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
