"""Queue mutation and persistence round trips (B3a).

The index trap, documented in CLAUDE.md and found the hard way in the
operator pagination work: the orchestrator indexes its deques ABSOLUTELY
(``get_queue_object``, ``move_*``, ``remove_*`` all do), while a rendered
row index is page-local. A handler that forgets to add the page offset
deletes the wrong queued item with nothing on screen looking wrong.

``limit=None`` means the whole queue, and that default matters: the queue
readers used to default to ``limit=10`` while the ``/list_*`` endpoints
called them bare, so no operator UI could ever see an eleventh queued item
-- and the subtab counts reported that truncation as the queue's depth.
"""

import pytest

from helao.helpers.premodels import Sequence
from helao.hexagon.tests.test_orch_host_surface import _host


def _fake_sequence(i: int) -> Sequence:
    """A queue entry distinguishable by name, with nothing else set.

    Deliberately minimal: this file tests QUEUE mechanics -- ordering,
    offsets, bounds -- and a fully-populated Sequence would make an
    ordering bug look like a model bug.
    """
    return Sequence(sequence_name=f"seq{i}", sequence_params={})


def test_list_sequences_defaults_to_the_whole_queue():
    host = _host()
    for i in range(12):
        host.sequence_dq.append(_fake_sequence(i))

    assert len(host.list_sequences()) == 12
    assert len(host.list_sequences(limit=5)) == 5
    assert len(host.list_sequences(limit=5, offset=10)) == 2


@pytest.mark.asyncio
async def test_move_and_remove_use_absolute_indices():
    """A page-local index passed straight through hits the wrong entry."""
    host = _host()
    for i in range(5):
        host.sequence_dq.append(_fake_sequence(i))

    await host.move_sequence(0, 4)
    assert [s.sequence_name for s in host.sequence_dq] == [
        "seq1",
        "seq2",
        "seq3",
        "seq4",
        "seq0",
    ]

    await host.remove_sequence(4)
    assert [s.sequence_name for s in host.sequence_dq] == [
        "seq1",
        "seq2",
        "seq3",
        "seq4",
    ]


@pytest.mark.asyncio
async def test_out_of_range_mutations_are_no_ops_not_errors():
    """The operator can race the loop; an index that has gone stale must
    not raise, because the caller has no way to have avoided it."""
    host = _host()
    host.sequence_dq.append(_fake_sequence(0))

    await host.move_sequence(0, 99)
    await host.remove_sequence(99)
    assert len(host.sequence_dq) == 1
