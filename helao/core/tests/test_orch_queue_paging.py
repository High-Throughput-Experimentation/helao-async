"""Paging over the orchestrator's run queues and history containers.

These cover the server half of the operator's paginated tables. The bug they
pin is specific: ``list_sequences``/``list_experiments``/``list_actions`` used
to default to ``limit=10`` and the three ``/list_*`` endpoints called them with
no arguments, so **no operator UI could ever see an eleventh queued item** --
and the tab counts, being ``len(rows)``, reported the truncation as the queue's
depth. A 400-deep experiment queue read ``Experiments [10]``.

The history half is newer: ``get_histories`` returns all three containers whole
and is left that way (``helao/hexagon/tests/smoke/conc_items.py`` calls it), so
paging arrived as ``get_history_page`` beside it.
"""

from collections import deque
from types import SimpleNamespace

from helao.core.servers.orch_api import _histories_payload, _history_page_payload
from helao.hexagon.app.orch_queues import _dq_page
from helao.helpers.dequedict import DequeDict

# -- queue paging ------------------------------------------------------------


def _dq(n):
    return deque(SimpleNamespace(name=f"item{i}") for i in range(n))


def _render(item):
    return item.name


def test_a_page_is_the_requested_window():
    assert _dq_page(_dq(120), 50, 50, _render) == [f"item{i}" for i in range(50, 100)]


def test_no_limit_means_the_whole_queue():
    """What the Bokeh operator now gets. Its tables scroll, so it wants every
    row rather than a page; ``limit=None`` is how it asks."""
    assert _dq_page(_dq(37), None, 0, _render) == [f"item{i}" for i in range(37)]


def test_a_short_last_page_is_not_padded():
    assert _dq_page(_dq(12), 50, 0, _render) == [f"item{i}" for i in range(12)]
    assert _dq_page(_dq(120), 50, 100, _render) == [f"item{i}" for i in range(100, 120)]


def test_an_offset_past_the_end_is_an_empty_page_not_an_error():
    """The offset comes from a paged UI and the queue drains under it, so a
    stale offset must render an empty table rather than raise inside a poll."""
    assert _dq_page(_dq(5), 50, 500, _render) == []


def test_a_negative_offset_or_limit_does_not_wrap():
    """Python's negative slicing would silently return the *end* of the queue
    for a negative offset, which is a plausible-looking wrong answer."""
    assert _dq_page(_dq(10), 50, -5, _render) == [f"item{i}" for i in range(10)]
    assert _dq_page(_dq(10), -5, 0, _render) == []


def test_the_ten_row_default_is_gone_from_every_layer():
    """The regression this whole change exists for. A default of 10 anywhere in
    the chain re-truncates every operator table at ten rows."""
    import inspect

    from helao.core.servers.orch import Orch
    from helao.hexagon.app.orch_queues import RunQueues

    for owner in (Orch, RunQueues):
        for name in ("list_sequences", "list_experiments", "list_actions"):
            params = inspect.signature(getattr(owner, name)).parameters
            assert params["limit"].default is None, f"{owner.__name__}.{name}"
            assert params["offset"].default == 0, f"{owner.__name__}.{name}"


# -- history paging ----------------------------------------------------------


def _orch_with_history(n):
    """An orch stub whose three history containers hold ``n`` entries each."""

    def container():
        d = DequeDict(maxlen=1000)
        for i in range(n):
            d[f"uuid{i:04d}"] = {"index": i}
        return d

    return SimpleNamespace(
        action_history=container(),
        experiment_history=container(),
        sequence_history=container(),
    )


def test_history_page_is_newest_first():
    """Offset 0 has to be the *newest* entries. Paging an oldest-first list
    would make the caller compute the newest page from a total that grows
    under it."""
    page = _history_page_payload(_orch_with_history(10), "action", 3, 0)
    assert [payload["index"] for _, payload in page["items"]] == [9, 8, 7]


def test_history_page_reports_the_full_total_not_the_page():
    page = _history_page_payload(_orch_with_history(120), "sequence", 50, 0)
    assert page["total"] == 120
    assert len(page["items"]) == 50


def test_a_later_history_page_walks_backwards_in_time():
    page = _history_page_payload(_orch_with_history(120), "experiment", 10, 100)
    assert [payload["index"] for _, payload in page["items"]] == list(range(19, 9, -1))
    assert page["offset"] == 100


def test_history_page_without_a_limit_returns_everything_from_the_offset():
    page = _history_page_payload(_orch_with_history(30), "action", None, 25)
    assert len(page["items"]) == 5


def test_an_unknown_history_kind_is_an_empty_page_not_a_500():
    """The kind names a UI tab, so a typo must not take down the operator's
    poll."""
    page = _history_page_payload(_orch_with_history(10), "nonsense", 50, 0)
    assert page == {"kind": "nonsense", "total": 0, "offset": 0, "items": []}


def test_a_negative_history_offset_does_not_wrap():
    page = _history_page_payload(_orch_with_history(10), "action", 3, -5)
    assert page["offset"] == 0
    assert [payload["index"] for _, payload in page["items"]] == [9, 8, 7]


def test_get_histories_still_returns_all_three_containers_whole():
    """`conc_items.py` calls this at three sites. Paging was added beside it,
    not on top of it."""
    payload = _histories_payload(_orch_with_history(7))
    assert set(payload) == {"action", "experiment", "sequence"}
    assert all(len(v) == 7 for v in payload.values())
    # Oldest-first, i.e. insertion order -- unchanged, unlike the paged view.
    assert [p["index"] for _, p in payload["action"]] == list(range(7))
