"""EstopPolicy (spec §4.2.5): ONE policy replacing two hardcoded cascades.

Today: (a) the orch's estop_loop sequence (orch_estop.EstopController), and
(b) a private deployment's driver-resident emergency-stop cascade -- raw HTTP
fired at hardcoded server keys, duplicated with drift in a Bokeh visualizer.
This module resolves both once: a pure policy mapping (declarative stop
topology + trigger event) -> ordered command list. Commands execute through
the Transport/OrchControl outbound port -- never raw httpx in a driver, never
hardcoded keys in code.

Q7 topology representation (see the P1a plan for rationale): per-server role
tags in the existing config idiom -- orchestrators derived from
``group: orchestrator``; ``estop_roles: [recorder|stop_private]`` tags on the
server entries that need them. CASCADE ORDER IS POLICY, NOT CONFIG.

Parity constraint (spec §4.2.5): estopped artifact shape unchanged --
``[finished, estopped]`` status lists (mark_estopped), no fabricated
placeholder artifacts (post-bd8b83ab), estop-promote deferral stays inside
FinishActiveEstopped's executor.
"""

from dataclasses import dataclass
from typing import Union

from helao.hexagon.domain.models import HloStatus
from helao.hexagon.domain.orchestration import EstopFanout, FinishActiveEstopped

__all__ = [
    "DriverFaultEdge",
    "EstopOrch",
    "EstopPolicy",
    "EstopTopology",
    "OrchEstopRequest",
    "StatusEstopIngested",
    "StopOrch",
    "StopPrivate",
    "StopRecorders",
    "UiEstopButton",
    "UiGracefulStopButton",
    "UiOrchEstopButton",
    "derive_estop_topology",
    "mark_estopped",
]

_VALID_ROLES = frozenset({"recorder", "stop_private"})


@dataclass(frozen=True)
class EstopTopology:
    """Declarative stop topology derived from a config's ``servers:`` block."""

    orch_keys: tuple[str, ...]
    recorder_keys: tuple[str, ...]
    stop_private_keys: tuple[str, ...]
    all_server_keys: tuple[str, ...]  # fanout targets (non-bokeh servers)


def derive_estop_topology(servers_cfg: dict) -> EstopTopology:
    """Build the topology from ``config['servers']``.

    Orchestrators come from ``group: orchestrator`` (no tag needed);
    recorder / stop_private roles come from the per-server ``estop_roles``
    list. Unknown role strings raise ValueError (loud preflight, not silent
    drift -- the failure mode that let a private deployment's two cascades
    diverge).
    """
    orch_keys: list[str] = []
    recorder_keys: list[str] = []
    stop_private_keys: list[str] = []
    all_server_keys: list[str] = []
    for key, cfg in servers_cfg.items():
        if "bokeh" in cfg:
            continue  # visualizer/operator bokeh apps take no estop calls
        all_server_keys.append(key)
        if cfg.get("group") == "orchestrator":
            orch_keys.append(key)
        roles = cfg.get("estop_roles", [])
        unknown = set(roles) - _VALID_ROLES
        if unknown:
            raise ValueError(
                f"server {key!r}: unknown estop_roles {sorted(unknown)}; "
                f"valid: {sorted(_VALID_ROLES)}"
            )
        if "recorder" in roles:
            recorder_keys.append(key)
        if "stop_private" in roles:
            stop_private_keys.append(key)
    return EstopTopology(
        orch_keys=tuple(orch_keys),
        recorder_keys=tuple(recorder_keys),
        stop_private_keys=tuple(stop_private_keys),
        all_server_keys=tuple(all_server_keys),
    )


# --- triggers (adapters feed these: OPC-UA fault monitor rising edge, the
#     visualizer buttons, status ingestion, POST /estop_orch) ---


@dataclass(frozen=True)
class DriverFaultEdge:
    source: str


@dataclass(frozen=True)
class UiEstopButton:
    """The station panel's full-cascade button ("stop everything").

    Yields the same commands as :class:`DriverFaultEdge`. The two smaller
    buttons below are deliberately NOT folded into this one -- see
    :meth:`EstopPolicy.commands_for`.
    """

    source: str


@dataclass(frozen=True)
class UiGracefulStopButton:
    """The station panel's "safe stop" button: orchestrators only, via /stop.

    Lets the running action finish. Emits no recorder or private stops.
    """

    source: str


@dataclass(frozen=True)
class UiOrchEstopButton:
    """The station panel's emergency-stop button: orchestrators only, via
    /estop_orch.

    Distinct from :class:`UiGracefulStopButton` in the *route* it hits, not the
    key set -- which is exactly why it cannot share a trigger with it.
    """

    source: str


@dataclass(frozen=True)
class StatusEstopIngested:
    reason: str


@dataclass(frozen=True)
class OrchEstopRequest:
    reason: str


Trigger = Union[
    DriverFaultEdge,
    UiEstopButton,
    UiGracefulStopButton,
    UiOrchEstopButton,
    StatusEstopIngested,
    OrchEstopRequest,
]


# --- commands (executed via the Transport port, P1b) ---


@dataclass(frozen=True)
class StopOrch:
    """POST /stop on an orchestrator key."""

    key: str


@dataclass(frozen=True)
class StopRecorders:
    """POST /stop_record on every recorder key."""

    keys: tuple[str, ...]


@dataclass(frozen=True)
class StopPrivate:
    """POST /stop_private on every tagged key."""

    keys: tuple[str, ...]


@dataclass(frozen=True)
class EstopOrch:
    """POST /estop_orch on an orchestrator key.

    Not the same as :class:`StopOrch` (which is /stop, a graceful stop that lets
    the running action finish) and not the same as :class:`EstopFanout` (which is
    what the receiving orchestrator then does to its own group).
    """

    key: str


Command = Union[
    StopOrch,
    StopRecorders,
    StopPrivate,
    EstopOrch,
    EstopFanout,
    FinishActiveEstopped,
]


class EstopPolicy:
    """Pure: trigger in -> ordered command tuple out. No I/O, no state."""

    def __init__(self, topology: EstopTopology):
        self.topology = topology

    def commands_for(self, trigger: Trigger) -> tuple[Command, ...]:
        # The two SMALLER station-panel buttons, handled first because they are
        # narrower cases of "a UI asked for a stop". Each hits orchestrators
        # ONLY, and they differ from each other in the route, not the key set:
        # graceful stop is /stop (the running action finishes), emergency stop
        # is /estop_orch. Folding either into UiEstopButton below would change
        # what a safety button does on the wire -- escalating a graceful stop
        # into a full cascade, or downgrading an emergency stop onto /stop --
        # and no artifact diff would show it.
        if isinstance(trigger, UiGracefulStopButton):
            return tuple(StopOrch(key=k) for k in self.topology.orch_keys)
        if isinstance(trigger, UiOrchEstopButton):
            return tuple(EstopOrch(key=k) for k in self.topology.orch_keys)
        if isinstance(trigger, (DriverFaultEdge, UiEstopButton)):
            # the (previously hardcoded) station-side cascade: orchestrators
            # first, then recorders, then stop_private targets -- fixed order,
            # not reorderable by config (see module docstring).
            cmds: list[Command] = [StopOrch(key=k) for k in self.topology.orch_keys]
            if self.topology.recorder_keys:
                cmds.append(StopRecorders(keys=self.topology.recorder_keys))
            if self.topology.stop_private_keys:
                cmds.append(StopPrivate(keys=self.topology.stop_private_keys))
            return tuple(cmds)
        # orch-side estop (API or status-ingested): fan out then finalize.
        # State flip / run-id clear / stop message stay with the reducer's
        # own transition -- this policy owns only the wire cascade tail.
        assert isinstance(trigger, (StatusEstopIngested, OrchEstopRequest))
        return (EstopFanout(switch=False), FinishActiveEstopped())


def mark_estopped(status_list: list[HloStatus]) -> list[HloStatus]:
    """The estopped terminal-status shape (orch_estop._mark_estopped):
    active is swapped in place for finished, estopped appended once -- the
    result always ends ``[..., finished, estopped]``, never bare
    ``[estopped]`` (spec §4.2.5 parity constraint).

    Drift vs. the live ``_mark_estopped`` closure (orch_estop.py:161), noted
    per the implementer instructions: the legacy closure only ever swaps
    active->finished -- it never appends a bare ``finished`` when active was
    already absent, so calling it on a status list that never went active
    (e.g. ``[]``) would leave a bare ``[estopped]``. That input never occurs
    in practice (``experiment_status``/``sequence_status`` always gain
    ``active`` before an estop can race them), but this pure helper is
    intentionally stricter: it always guarantees ``finished`` precedes
    ``estopped``, per the "never bare estopped" invariant this task's brief
    states explicitly as a parity constraint.
    """
    out = list(status_list)
    if HloStatus.active in out:
        out[out.index(HloStatus.active)] = HloStatus.finished
    elif HloStatus.finished not in out:
        out.append(HloStatus.finished)
    if HloStatus.estopped not in out:
        out.append(HloStatus.estopped)
    return out
