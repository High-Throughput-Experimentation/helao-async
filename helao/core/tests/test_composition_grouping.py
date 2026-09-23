# helao/core/tests/test_composition_grouping.py
"""The two grouping dropdowns.

The sequence label carries the timestamp because the probed plate has two
sequences with the same name and the same label two months apart -- the name
would render them identical.
"""

from helao.ui.shared.composition import grouping
from helao.ui.shared.composition.model import CompositionRecord


def record(**kwargs) -> CompositionRecord:
    base = dict(
        plate_id=10244,
        sample_no=1,
        global_label="legacy__solid__10244_1",
        run_use="post_anneal",
        sequence_uuid="06a7e382-a773-731d-8000-d7e3e21eacec",
        sequence_timestamp="2026-08-13T11:54:21.000000",
        process_uuid="p",
        process_timestamp="2026-08-13T11:57:41.000000",
        quant_action_uuid="a",
        quant_file_name="q.json",
        spectrum_action_uuid="a",
        spectrum_file_name="s.json",
        values={},
    )
    base.update(kwargs)
    return CompositionRecord(**base)


OLD = record()
NEW = record(
    sequence_uuid="07528a44-2e9b-56dc-a3c1-912f6f018865",
    sequence_timestamp="2026-09-10T17:02:37.000000",
    run_use="pre_anneal",
    sample_no=2,
)


def test_sequence_label_carries_the_timestamp() -> None:
    assert grouping.sequence_label(OLD) == "2026-08-13T11:54:21.000000 · 06a7e382"


def test_two_sequences_sharing_a_name_get_distinct_labels() -> None:
    assert grouping.sequence_label(OLD) != grouping.sequence_label(NEW)


def test_sequence_label_falls_back_to_the_bare_uuid() -> None:
    assert grouping.sequence_label(record(sequence_timestamp="")) == (
        "06a7e382-a773-731d-8000-d7e3e21eacec"
    )


def test_sequence_options_are_newest_first_after_all() -> None:
    options = grouping.sequence_options([OLD, NEW])
    assert options[0] == grouping.ALL
    assert options[1] == grouping.sequence_label(NEW)
    assert options[2] == grouping.sequence_label(OLD)


def test_run_use_options_start_with_all() -> None:
    assert grouping.run_use_options([OLD, NEW]) == [
        grouping.ALL,
        "post_anneal",
        "pre_anneal",
    ]


def test_an_empty_run_use_is_named_not_blank() -> None:
    """A blank dropdown entry reads as a rendering failure."""
    options = grouping.run_use_options([record(run_use="")])
    assert options == [grouping.ALL, grouping.NO_RUN_USE]


def test_filter_on_all_returns_everything() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use=grouping.ALL, sequence=grouping.ALL
    )
    assert kept == [OLD, NEW]


def test_the_two_filters_compose() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use="pre_anneal", sequence=grouping.sequence_label(NEW)
    )
    assert kept == [NEW]


def test_a_composition_that_matches_nothing_returns_empty() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use="pre_anneal", sequence=grouping.sequence_label(OLD)
    )
    assert kept == []


def test_filter_matches_the_named_empty_run_use() -> None:
    blank = record(run_use="")
    kept = grouping.filter_records(
        [blank, OLD], run_use=grouping.NO_RUN_USE, sequence=grouping.ALL
    )
    assert kept == [blank]
