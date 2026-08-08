"""Row 15, the negative artifact row: a control drives hardware, writes nothing.

Every other artifact row asserts that something *appears*. This one asserts
that nothing does -- and a negative is the one shape of assertion that passes
for the wrong reason. An unlaunched group leaves the run tree unchanged. A
404 leaves the run tree unchanged. A typo in a route name leaves the run tree
unchanged. Each of those is a *broken* check reporting success, and none of
them is visible in the diff, because the diff is empty in exactly the way the
passing case is empty.

So the check here is two-part and the order is the point:

1. **Success precondition.** Every control call must be *observed to have
   worked*: error code ``none``, and -- for the four routes that can be
   observed at all -- a readback that reflects what was commanded. A digital
   output must read back the state it was set to; an axis must read back the
   coordinate it was moved to. Only then does the negative mean anything.
2. **Then** the member-set diff over the run root, before against after.

:func:`run_negative` refuses to report a pass if part 1 did not hold, and its
:class:`NegativeResult` carries both halves so a caller cannot look at the
tree verdict without the preconditions beside it.

**The baseline should not be empty.** Two empty snapshots differ by nothing,
which is true but says nothing about whether a write would have been noticed.
:func:`run_negative` therefore reports ``baseline_members`` and a caller that
cares (the smoke driver does) plants a run tree first, so the assertion is
that a *real* member set survived the toggles unchanged. The mutation
self-test in ``harness/tests/test_control_negative.py`` closes the other half:
it drops a file into the tree between the snapshots and requires this module
to report it.

What makes the negative *true* rather than merely observed: all five routes
are bare-path ``tags=["private"]`` endpoints, never ``/{server_key}/...``.
That prefix is the action namespace, so the calls enter neither the action
lifecycle (which writes ``-act.yml`` and hlo files) nor the queueing
middleware. Nothing in the path they take has a file handle.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness.treepass import (
    PARITY_TOPS,
    TreeSnapshot,
    diff_member_sets,
    explode_zips,
    seed_mapper,
)
from harness.treepass import snapshot as tree_snapshot
from harness.uuidmap import UuidMapper

__all__ = [
    "ControlTarget",
    "NegativeResult",
    "Probe",
    "drive_control_surface",
    "run_negative",
    "snapshot_root",
]

#: Counts to move by, per move probe. Large enough that the post-move readback
#: cannot coincide with the pre-move one through rounding, small enough to be
#: a legal move on any axis a simulator models.
MOVE_COUNTS = 1000


@dataclass
class ControlTarget:
    """One action server the control surface addresses.

    Attributes:
        server_key: Config key, as the dispatcher logs it.
        host: Its host.
        port: Its HTTP port.
        do_name: A digital output on it that can be **read back**, or ``None``
            when it has none. A write-only line cannot satisfy the success
            precondition -- it is honest about being unknown, which is exactly
            what makes it useless as proof that a toggle landed.
        axis: An axis on it, or ``None`` when it has none.
    """

    server_key: str
    host: str
    port: int
    do_name: Optional[str] = None
    axis: Optional[str] = None


@dataclass
class Probe:
    """One control call and whether it was *observed* to have taken effect."""

    route: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"{'OK  ' if self.ok else 'FAIL'} {self.route}: {self.detail}"


@dataclass
class NegativeResult:
    """The two halves of the row-15 verdict, never separable.

    Attributes:
        probes: One per control call attempted, in call order.
        tree_diffs: :func:`~harness.treepass.diff_member_sets` output over the
            run root, before against after.
        baseline_members: How many normalized members the *before* snapshot
            held. Reported because a zero here means the tree comparison,
            though true, compared nothing.
    """

    probes: list[Probe] = field(default_factory=list)
    tree_diffs: list[dict] = field(default_factory=list)
    baseline_members: int = 0

    @property
    def preconditions_met(self) -> bool:
        """Whether every control call was observed to have worked."""
        return bool(self.probes) and all(p.ok for p in self.probes)

    @property
    def tree_unchanged(self) -> bool:
        return not self.tree_diffs

    @property
    def ok(self) -> bool:
        """The row-15 verdict. **Both** halves, deliberately.

        An unchanged tree alone is not a pass: it is what a dead server also
        produces.
        """
        return self.preconditions_met and self.tree_unchanged

    def report(self) -> str:
        lines = [str(p) for p in self.probes]
        lines.append(f"baseline members: {self.baseline_members}")
        if self.tree_diffs:
            lines.append(f"TREE CHANGED ({len(self.tree_diffs)} member diffs):")
            lines.extend(
                f"  {d['file']}: golden={d['golden']} candidate={d['candidate']}"
                for d in self.tree_diffs
            )
        else:
            lines.append("tree unchanged")
        if not self.probes:
            lines.append(
                "NO CONTROL CALLS MADE -- an unchanged tree here means nothing"
            )
        lines.append(f"ROW-15 RESULT: {'PASS' if self.ok else 'FAIL'}")
        return "\n".join(lines)


def snapshot_root(root: Path, workdir: Optional[Path] = None) -> TreeSnapshot:
    """Normalized member-set snapshot of one live run root.

    Only the parity tops are copied, not the whole root. Two reasons, both
    measured rather than tidiness: ``LOGS/`` and ``STATES/`` are *expected* to
    change during the run -- every control call logs a line -- so copying them
    would put guaranteed churn inside a snapshot whose whole job is to be
    identical twice; and a rotating log file is being written while the copy
    walks it, which is how a whole-root ``copytree`` turns into a flaky
    ``FileNotFoundError`` rather than a verdict. The parity tops are also
    exactly what :func:`~harness.treepass.snapshot` reads, so nothing is lost.

    Zips are exploded in the staged copy, so a sequence that has already been
    synced is compared by its **members** rather than by an opaque archive
    whose bytes move with its timestamps.

    Args:
        root: The config's ``root``.
        workdir: Where to stage the copies. A temporary directory is used when
            omitted; pass one when the caller needs the staged tree to outlive
            the call.

    Returns:
        TreeSnapshot: Empty when the root does not exist yet -- which is a
        legitimate baseline for a group that has run nothing, and is why
        :class:`NegativeResult` reports the member count separately.
    """
    root = Path(root)
    if not root.is_dir():
        return TreeSnapshot(root=root)
    staged_parent = Path(workdir) if workdir else Path(tempfile.mkdtemp())
    staged_parent.mkdir(parents=True, exist_ok=True)
    slim = staged_parent / "root"
    slim.mkdir()
    for top in PARITY_TOPS:
        src = root / top
        if src.is_dir():
            shutil.copytree(src, slim / top)
    exploded = explode_zips(slim, staged_parent / "work")
    mapper = UuidMapper()
    seed_mapper(exploded, mapper)
    return tree_snapshot(exploded, mapper)


async def drive_control_surface(
    surface, targets: list[ControlTarget], none_code=None
) -> list[Probe]:
    """Exercise every control route on every target; report what was observed.

    Args:
        surface: A :class:`~helao.hexagon.ports.control_surface.ControlSurfacePort`.
        targets: The servers to drive. A target contributes IO probes when it
            names a ``do_name`` and motion probes when it names an ``axis``.
        none_code: The error code meaning success. Defaults to
            ``ErrorCodes.none``; injectable so this module stays testable
            against a fake surface with no HELAO import in the way.

    Returns:
        list[Probe]: One per call, in call order. A probe is ``ok`` only when
        the call **and its readback** agreed -- an error code of ``none`` on a
        toggle whose readback did not move is a failure here, because that is
        indistinguishable from a server that accepted the call and did nothing.
    """
    if none_code is None:
        from helao.core.error import ErrorCodes

        none_code = ErrorCodes.none

    probes: list[Probe] = []
    for target in targets:
        where = target.server_key
        if target.do_name:
            states = await surface.read_digital_outs(where, target.host, target.port)
            probes.append(
                Probe(
                    f"get_digital_outs[{where}]",
                    target.do_name in states,
                    f"read {len(states)} line(s); '{target.do_name}' "
                    f"{'present' if target.do_name in states else 'ABSENT'}",
                )
            )
            # Toggle away from whatever it is now, so the readback proves a
            # change rather than agreeing with a state that was already set.
            wanted = not bool(states.get(target.do_name))
            reported = await surface.set_digital_out(
                where, target.host, target.port, target.do_name, wanted
            )
            probes.append(
                Probe(
                    f"set_digital_out[{where}]",
                    reported.get(target.do_name) is wanted,
                    f"set '{target.do_name}' to {wanted}; server reported "
                    f"{reported.get(target.do_name)!r}",
                )
            )
            # And again through the read route: the write's own reply could be
            # an echo. This one comes from the device's own state.
            confirmed = await surface.read_digital_outs(where, target.host, target.port)
            probes.append(
                Probe(
                    f"set_digital_out[{where}] persisted",
                    confirmed.get(target.do_name) is wanted,
                    f"re-read '{target.do_name}' -> "
                    f"{confirmed.get(target.do_name)!r}",
                )
            )

        if target.axis:
            before = await surface.read_axis_positions(where, target.host, target.port)
            start = (before.get(target.axis) or {}).get("counts")
            probes.append(
                Probe(
                    f"get_axis_positions[{where}]",
                    start is not None,
                    f"read {len(before)} axis/axes; '{target.axis}' counts={start!r}",
                )
            )
            code, payload = await surface.move_axis(
                where,
                target.host,
                target.port,
                target.axis,
                float(MOVE_COUNTS),
                "counts",
                mode="relative",
            )
            probes.append(
                Probe(
                    f"move_axis[{where}]",
                    code == none_code,
                    f"code={code!r} payload={payload!r}",
                )
            )
            after = await surface.read_axis_positions(where, target.host, target.port)
            landed = (after.get(target.axis) or {}).get("counts")
            probes.append(
                Probe(
                    f"move_axis[{where}] moved",
                    start is not None
                    and landed is not None
                    and landed - start == MOVE_COUNTS,
                    f"counts {start!r} -> {landed!r} (expected +{MOVE_COUNTS})",
                )
            )
            code, payload = await surface.stop_motion(where, target.host, target.port)
            stopped = (payload or {}).get("stopped") or []
            probes.append(
                Probe(
                    f"stop_motion[{where}]",
                    code == none_code and target.axis in stopped,
                    f"code={code!r} stopped={stopped!r}",
                )
            )
    return probes


async def run_negative(
    root: Path,
    targets: list[ControlTarget],
    surface=None,
    workdir: Optional[Path] = None,
    none_code=None,
) -> NegativeResult:
    """Snapshot, drive every control route, snapshot again, diff.

    Args:
        root: The launched group's config ``root``.
        targets: The servers to drive.
        surface: The control surface to drive them through. Defaults to the
            hexagon's :class:`~helao.hexagon.adapters.vis.control_surface.ControlSurface`,
            which delegates to the same shared wrappers both UI stacks use --
            so this exercises the panels' actual path, not a parallel client.
        workdir: Staging directory for the exploded copies (two are made).
        none_code: Success code; see :func:`drive_control_surface`.

    Returns:
        NegativeResult: Carrying both halves of the verdict.
    """
    if surface is None:
        from helao.hexagon.adapters.vis.control_surface import ControlSurface

        surface = ControlSurface()

    root = Path(root)
    stage = Path(workdir) if workdir else Path(tempfile.mkdtemp())
    before = snapshot_root(root, stage / "before")
    probes = await drive_control_surface(surface, targets, none_code=none_code)
    try:
        after = snapshot_root(root, stage / "after")
    except ValueError as exc:
        # A normalized-name collision, which is what a stray file whose name
        # differs from an existing one only in its timestamp produces --
        # ``normalize_name`` collapses both to the same ``TS`` token and
        # ``snapshot`` refuses to guess which is which. Letting that propagate
        # would abort the run with a traceback instead of a verdict, and a
        # traceback is not a diff: the interesting fact is that the after-tree
        # is no longer the before-tree, which is precisely a row-15 failure.
        return NegativeResult(
            probes=probes,
            tree_diffs=[
                {
                    "file": str(exc),
                    "key": "<tree>",
                    "golden": "absent",
                    "candidate": "present",
                }
            ],
            baseline_members=len(before.files),
        )

    return NegativeResult(
        probes=probes,
        tree_diffs=diff_member_sets(before, after),
        baseline_members=len(before.files),
    )
