"""The row-15 negative harness, and the two ways a negative lies.

A negative assertion has a failure mode positives do not: it passes when the
thing under test never happened. Both halves are pinned here.

* **Mutation self-test** -- something writes into the tree between the
  snapshots, and the harness must report it. Without this, "tree unchanged"
  is a claim about the harness's blindness, not about the control path.
* **Success precondition** -- a dead server, a 404, and a toggle the device
  ignored must each **fail**, not pass. Each of those leaves the tree exactly
  as unchanged as a healthy run does.

The surface is faked here on purpose: these tests are about the harness's
judgement, and a fake is the only way to script a server that answers
successfully and does nothing, which is the case a live sim cannot produce on
demand.
"""

import asyncio

from harness.control_negative import (
    MOVE_COUNTS,
    ControlTarget,
    drive_control_surface,
    run_negative,
    snapshot_root,
)
from harness.tests.synthtree import build_tree

NONE = "none"  # stands in for ErrorCodes.none; injected, never imported here
FAIL = "not_available"

TARGETS = [ControlTarget("IOSIM", "127.0.0.1", 8002, do_name="led", axis="x")]


class FakeSurface:
    """A control surface over an in-memory device, with scriptable faults.

    Attributes:
        writes: A callable invoked after every successful command, so a test
            can make the control path write into the run tree -- which is the
            thing row 15 says never happens.
    """

    def __init__(self, states=None, counts=0, fault=None, deaf=False, writes=None):
        self.states = dict(states or {"led": False})
        self.counts = counts
        self.fault = fault  # an error code to return instead of success
        self.deaf = deaf  # accepts everything, changes nothing
        self.writes = writes
        self.calls: list[str] = []

    def _wrote(self):
        if self.writes:
            self.writes()

    async def read_digital_outs(self, server_key, host, port):
        self.calls.append("get_digital_outs")
        if self.fault:
            return {}  # the wrappers discard the body on a non-none code
        return dict(self.states)

    async def set_digital_out(self, server_key, host, port, do_name, on):
        self.calls.append("set_digital_out")
        if self.fault:
            return {}
        if not self.deaf:
            self.states[do_name] = bool(on)
        self._wrote()
        return {do_name: self.states.get(do_name)}

    async def read_axis_positions(self, server_key, host, port):
        self.calls.append("get_axis_positions")
        if self.fault:
            return {}
        return {"x": {"mm": None, "counts": self.counts, "moving": False}}

    async def move_axis(
        self, server_key, host, port, axis, value, units, mode=None, speed=None
    ):
        self.calls.append("move_axis")
        if self.fault:
            return self.fault, {}
        if not self.deaf:
            self.counts += int(value)
        self._wrote()
        return NONE, {"axis": axis, "requested": value, "units": units}

    async def stop_motion(self, server_key, host, port):
        self.calls.append("stop_motion")
        if self.fault:
            return self.fault, {}
        self._wrote()
        return NONE, {"stopped": ["x"]}


# --------------------------------------------------------------------------
# the happy path, so the failures below mean something
# --------------------------------------------------------------------------


def test_a_healthy_surface_passes_both_halves(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    assert result.preconditions_met, result.report()
    assert result.tree_unchanged, result.report()
    assert result.ok
    # And the baseline was not empty -- an empty-vs-empty comparison would be
    # true and meaningless.
    assert result.baseline_members > 0
    print("test_a_healthy_surface_passes_both_halves PASS")


def test_every_control_route_is_driven(tmp_path):
    surface = FakeSurface()
    asyncio.run(drive_control_surface(surface, TARGETS, none_code=NONE))

    # All five, from one target that has both a line and an axis.
    assert set(surface.calls) == {
        "get_digital_outs",
        "set_digital_out",
        "get_axis_positions",
        "move_axis",
        "stop_motion",
    }
    print("test_every_control_route_is_driven PASS")


# --------------------------------------------------------------------------
# the mutation self-test: the diff must actually see a write
# --------------------------------------------------------------------------


def test_a_file_written_by_the_control_path_is_reported(tmp_path):
    root = tmp_path / "root"
    ids = build_tree(root)

    def write_an_artifact():
        # Exactly the shape row 15 forbids: a control call leaving an action
        # record behind, in its own action directory the way the action
        # lifecycle would create one. Written once, on the first command.
        stray_dir = ids["exp_dir"] / "1__0__IOSIM__set_digital_out"
        if stray_dir.exists():
            return
        stray_dir.mkdir()
        (stray_dir / "250716.131422123456-act.yml").write_text(
            "file_type: action\n"
            "action_uuid: 00000000-0000-0000-0000-000000000009\n"
            f"experiment_uuid: {ids['exp_uuid']}\n"
            f"sequence_uuid: {ids['seq_uuid']}\n"
            "action_name: set_digital_out\n"
            "action_timestamp: 2025-07-16 13:14:22.123456\n"
            "action_status:\n  - finished\n"
        )

    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(writes=write_an_artifact),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    # The preconditions still pass -- the device worked. It is the tree half
    # that must go red, which is the whole point of keeping them separate.
    assert result.preconditions_met
    assert not result.tree_unchanged
    assert not result.ok
    assert len(result.tree_diffs) == 1
    assert result.tree_diffs[0]["golden"] == "absent"
    assert result.tree_diffs[0]["candidate"] == "present"
    assert "set_digital_out" in result.tree_diffs[0]["file"]
    assert "TREE CHANGED" in result.report()
    print("test_a_file_written_by_the_control_path_is_reported PASS")


def test_a_stray_file_that_normalizes_onto_an_existing_one_is_a_failure(tmp_path):
    """The mutation the normalizer cannot name, reported rather than raised.

    ``normalize_name`` collapses every timestamp to one ``TS`` token, so a
    stray ``-act.yml`` written *beside* an existing one in the same action
    directory normalizes to the identical member name and ``treepass.snapshot``
    raises ``ValueError`` instead of returning a set. Measured, not
    anticipated: it is what this harness's first mutation self-test actually
    did. A traceback there would abort the run with no verdict, and "the check
    crashed" reads to a reviewer like an infrastructure problem rather than
    like the failure it is.
    """
    root = tmp_path / "root"
    ids = build_tree(root)

    def write_a_sibling():
        stray = ids["act_dir"] / "250716.131422123456-act.yml"
        if not stray.exists():
            stray.write_text("file_type: action\naction_name: set_digital_out\n")

    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(writes=write_a_sibling),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    assert not result.ok
    assert not result.tree_unchanged
    assert "collision" in result.tree_diffs[0]["file"]
    print("test_a_stray_file_that_normalizes_onto_an_existing_one_is_a_failure PASS")


def test_a_deleted_file_is_reported_too(tmp_path):
    root = tmp_path / "root"
    ids = build_tree(root)

    def delete_an_artifact():
        hlo = ids["act_dir"] / "WsSim-0.0.0.0__0.hlo"
        if hlo.exists():
            hlo.unlink()

    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(writes=delete_an_artifact),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    # "Writes nothing" is a claim about the tree, not about file creation:
    # a control that removed a record would satisfy an additions-only check.
    assert not result.ok
    assert result.tree_diffs[0]["golden"] == "present"
    assert result.tree_diffs[0]["candidate"] == "absent"
    print("test_a_deleted_file_is_reported_too PASS")


# --------------------------------------------------------------------------
# the success precondition: the three ways a negative passes for nothing
# --------------------------------------------------------------------------


def test_a_dead_server_fails_instead_of_passing(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    class DeadSurface(FakeSurface):
        async def read_digital_outs(self, *a, **k):
            raise ConnectionRefusedError("nothing is listening")

    # The real wrappers swallow the connection error and return ``{}``; this
    # fake raises instead, so the assertion below covers both -- what must
    # never happen is a *pass*, and the harness may reach that either by
    # reporting failed probes or by letting the exception out.
    try:
        result = asyncio.run(
            run_negative(
                root,
                TARGETS,
                surface=DeadSurface(),
                workdir=tmp_path / "stage",
                none_code=NONE,
            )
        )
    except ConnectionRefusedError:
        print("test_a_dead_server_fails_instead_of_passing PASS (raised)")
        return

    assert not result.ok
    print("test_a_dead_server_fails_instead_of_passing PASS")


def test_a_404_fails_instead_of_passing(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    # What a server without these endpoints actually produces: the wrapper
    # discards the {"detail": "Not Found"} body and returns empty.
    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(fault=FAIL),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    assert not result.preconditions_met
    # The tree really is unchanged -- and that is exactly why the tree half
    # alone would have reported a pass here.
    assert result.tree_unchanged
    assert not result.ok
    assert "NO CONTROL CALLS MADE" not in result.report()
    failed = [p for p in result.probes if not p.ok]
    assert len(failed) == len(result.probes)
    print("test_a_404_fails_instead_of_passing PASS")


def test_a_toggle_that_did_nothing_fails(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    # The subtlest case: every call returns success, and the device ignores
    # all of them. An error-code-only precondition passes this.
    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(deaf=True),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    assert not result.ok
    assert result.tree_unchanged
    failed = {p.route for p in result.probes if not p.ok}
    assert "set_digital_out[IOSIM]" in failed
    assert "move_axis[IOSIM] moved" in failed
    print("test_a_toggle_that_did_nothing_fails PASS")


def test_no_calls_at_all_is_not_a_pass(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    result = asyncio.run(
        run_negative(
            root,
            [],  # nothing configured to drive
            surface=FakeSurface(),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    # An empty target list is the harness equivalent of an unlaunched group.
    assert result.tree_unchanged
    assert not result.ok
    assert "NO CONTROL CALLS MADE" in result.report()
    print("test_no_calls_at_all_is_not_a_pass PASS")


# --------------------------------------------------------------------------
# what the probes assert
# --------------------------------------------------------------------------


def test_the_toggle_is_away_from_the_current_state():
    # A toggle that set a line to the value it already held would report a
    # matching readback while proving nothing about the write.
    surface = FakeSurface(states={"led": True})
    probes = asyncio.run(drive_control_surface(surface, TARGETS, none_code=NONE))

    assert surface.states["led"] is False
    assert all(p.ok for p in probes), [str(p) for p in probes]
    print("test_the_toggle_is_away_from_the_current_state PASS")


def test_the_write_reply_is_confirmed_by_an_independent_read():
    class EchoSurface(FakeSurface):
        """Reports what it was asked for and stores nothing."""

        async def set_digital_out(self, server_key, host, port, do_name, on):
            return {do_name: on}

    probes = asyncio.run(drive_control_surface(EchoSurface(), TARGETS, none_code=NONE))
    by_route = {p.route: p for p in probes}

    # The write's own reply agrees...
    assert by_route["set_digital_out[IOSIM]"].ok
    # ...and the independent re-read is what catches it.
    assert not by_route["set_digital_out[IOSIM] persisted"].ok
    print("test_the_write_reply_is_confirmed_by_an_independent_read PASS")


def test_the_move_probe_checks_the_displacement_not_just_the_code():
    class HalfMoveSurface(FakeSurface):
        async def move_axis(self, *a, **k):
            self.counts += 1  # accepted, and went nowhere near far enough
            return NONE, {}

    probes = asyncio.run(
        drive_control_surface(HalfMoveSurface(), TARGETS, none_code=NONE)
    )
    by_route = {p.route: p for p in probes}

    assert by_route["move_axis[IOSIM]"].ok  # the code said yes
    assert not by_route["move_axis[IOSIM] moved"].ok  # the encoder disagreed
    assert f"+{MOVE_COUNTS}" in by_route["move_axis[IOSIM] moved"].detail
    print("test_the_move_probe_checks_the_displacement_not_just_the_code PASS")


def test_a_target_with_no_line_or_axis_contributes_no_probes():
    surface = FakeSurface()
    probes = asyncio.run(
        drive_control_surface(
            surface, [ControlTarget("EMPTY", "127.0.0.1", 8009)], none_code=NONE
        )
    )

    assert probes == []
    assert surface.calls == []
    print("test_a_target_with_no_line_or_axis_contributes_no_probes PASS")


# --------------------------------------------------------------------------
# snapshotting
# --------------------------------------------------------------------------


def test_a_missing_root_snapshots_empty_rather_than_raising(tmp_path):
    snap = snapshot_root(tmp_path / "never-created", tmp_path / "stage")
    assert snap.files == {}
    print("test_a_missing_root_snapshots_empty_rather_than_raising PASS")


def test_log_and_state_churn_is_not_a_tree_change(tmp_path):
    root = tmp_path / "root"
    build_tree(root)

    def churn_the_logs():
        logs = root / "LOGS"
        logs.mkdir(exist_ok=True)
        (logs / "IOSIM.log").write_text("a control call was logged\n")
        states = root / "STATES"
        states.mkdir(exist_ok=True)
        (states / "pids_controlneg_.pck").write_bytes(b"\x00")

    result = asyncio.run(
        run_negative(
            root,
            TARGETS,
            surface=FakeSurface(writes=churn_the_logs),
            workdir=tmp_path / "stage",
            none_code=NONE,
        )
    )

    # Logging a toggle is not writing a run artifact. If LOGS counted, every
    # healthy run of this check would fail, and the check would be deleted.
    assert result.ok, result.report()
    print("test_log_and_state_churn_is_not_a_tree_change PASS")
