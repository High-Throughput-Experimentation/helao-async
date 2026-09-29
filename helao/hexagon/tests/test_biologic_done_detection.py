"""Done-detection, the start race, and the bounded tail drain."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.data import MAX_DRAINS_PER_CALL, RunTracker


class V:
    def __init__(self, state):
        self.State = state
        self.TimeBase = 1e-3


class I:
    def __init__(self, rows=1, index=0, skipped=0):
        self.NbRows = rows
        self.TechniqueIndex = index
        self.IRQskipped = skipped


RUN = vendor.PROG_STATE.RUN
STOP = vendor.PROG_STATE.STOP
PAUSE = vendor.PROG_STATE.PAUSE
SYNC = vendor.PROG_STATE.SYNC


def test_stop_before_any_run_reads_as_starting_not_done():
    """The whole point: StartChannel returns before the firmware is running,
    so the first poll can legitimately see STOP."""
    t = RunTracker()
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.seen_run is False


def test_run_then_sustained_stop_reads_as_done():
    t = RunTracker(stop_polls_to_finish=3)
    assert t.observe(V(RUN), I()) == "measuring"
    assert t.observe(V(STOP), I()) == "measuring"
    assert t.observe(V(STOP), I()) == "measuring"
    assert t.observe(V(STOP), I()) == "done"


def test_a_stop_between_linked_techniques_is_not_the_end_of_the_run():
    """Station failure, 2026-09-18, `run_CAOCV`: a linked experiment is one
    protocol per technique and the channel passes through STOP between them
    (`end protocol 0, ID = 101` to `start protocol 1, ID=100`, ~2 ms in the
    firmware log). One STOP sample there ended the action a second into a
    10 s OCV, which then ran to completion with nobody reading it."""
    t = RunTracker(stop_polls_to_finish=3)
    t.observe(V(RUN), I(index=0))
    assert t.observe(V(STOP), I(index=0)) == "measuring"  # the gap
    assert t.observe(V(RUN), I(index=1)) == "measuring"  # OCV running
    assert t.observe(V(RUN), I(index=1)) == "measuring"
    # ...and the real end, once STOP persists
    assert t.observe(V(STOP), I(index=1)) == "measuring"
    assert t.observe(V(STOP), I(index=1)) == "measuring"
    assert t.observe(V(STOP), I(index=1)) == "done"


def test_a_stop_run_of_less_than_the_bound_leaves_the_tracker_undone():
    """The counter resets on any busy sample, so a channel that flickers
    never accumulates its way to done."""
    t = RunTracker(stop_polls_to_finish=3)
    t.observe(V(RUN), I())
    for _ in range(10):
        assert t.observe(V(STOP), I()) == "measuring"
        assert t.observe(V(RUN), I()) == "measuring"


def test_pause_is_busy_not_done():
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(PAUSE), I()) == "measuring"


def test_sync_is_busy_not_done():
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(SYNC), I()) == "measuring"


def test_an_unknown_state_is_treated_as_busy():
    """A firmware that adds a state must not read as a finished action."""
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(99), I()) == "measuring"


def test_rows_arriving_count_as_having_run():
    """A short technique can complete between two polls; the rows are proof it
    ran even though RUN was never observed. It still has to hold STOP -- the
    rows could equally be the first technique of a linked plan."""
    t = RunTracker(stop_polls_to_finish=2)
    assert t.observe(V(STOP), I(rows=4)) == "measuring"
    assert t.seen_run is True
    assert t.observe(V(STOP), I(rows=0)) == "done"


def test_done_is_sticky():
    t = RunTracker(stop_polls_to_finish=1)
    t.observe(V(RUN), I())
    assert t.observe(V(STOP), I()) == "done"
    assert t.observe(V(RUN), I()) == "done"


def test_starting_is_bounded_and_reports_error():
    """A channel that accepts StartChannel and never reaches RUN (or STOP
    with rows) must not poll "starting" forever -- see MAX_STARTING_POLLS."""
    t = RunTracker(max_starting_polls=2)
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.observe(V(STOP), I(rows=0)) == "error"
    assert t.seen_run is False


def test_error_is_sticky():
    t = RunTracker(max_starting_polls=1)
    t.observe(V(STOP), I(rows=0))
    assert t.observe(V(STOP), I(rows=0)) == "error"
    assert t.observe(V(RUN), I()) == "error"


def test_max_starting_polls_none_disables_the_cap():
    """A channel parked on a requested trigger waits on an external
    instrument, deliberately indefinitely -- `None` must never time out."""
    t = RunTracker(max_starting_polls=None)
    for _ in range(1000):
        assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.seen_run is False


def test_should_drain_while_rows_keep_arriving():
    t = RunTracker()
    assert t.should_drain(I(rows=3)) is True


def test_should_not_drain_once_a_segment_is_empty():
    t = RunTracker()
    assert t.should_drain(I(rows=0)) is False


def test_drain_is_bounded():
    t = RunTracker()
    for _ in range(MAX_DRAINS_PER_CALL):
        assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is False


def test_drain_stops_when_the_technique_index_advances():
    """An advancing index means the channel moved to the next linked
    technique, so it is not finishing and draining would never end."""
    t = RunTracker()
    assert t.should_drain(I(rows=1, index=0)) is True
    assert t.should_drain(I(rows=1, index=1)) is False


def test_max_drains_is_configurable_for_a_long_plan():
    t = RunTracker(max_drains=2)
    assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is False


def test_skipped_irqs_accumulate():
    t = RunTracker()
    t.observe(V(RUN), I(skipped=3))
    t.observe(V(RUN), I(skipped=2))
    assert t.skipped == 5


def test_skipped_irqs_are_not_a_column():
    """Dropped points are a log line and a counter; the emitted set is frozen."""
    from helao.deploy.hte.drivers.pstat.biologic import data

    for columns in data.COLUMNS.values():
        assert "IRQskipped" not in columns
        assert "_IRQskipped" not in columns
