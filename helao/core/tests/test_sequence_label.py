"""The plate/sample suffix lives in sequence_label itself (spec §3.3)."""

from datetime import datetime
from pathlib import Path

import pytest

from helao.helpers.premodels import Sequence

TS = datetime(2026, 9, 25, 9, 41, 2)


def _seq(label, params):
    s = Sequence(sequence_name="XRFS_noStandards", sequence_label=label)
    s.sequence_params = params
    s.sequence_timestamp = TS
    s.apply_label_suffix()
    return s


@pytest.mark.parametrize(
    "label,params,expected",
    [
        # no plate -> untouched
        ("mylabel", {}, "mylabel"),
        (None, {}, "noLabel"),
        # plate absent from the label -> serial appended, check digit 1+0+1+3+1=6
        ("mylabel", {"plate_id": 10131}, "mylabel-101316"),
        # plate already named -> not appended twice
        ("run-101316", {"plate_id": 10131}, "run-101316"),
        # one sample, each of the four accepted sources
        ("m", {"plate_id": 10131, "sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "solid_sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "plate_sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "plate_sample_no_list": [42]}, "m-101316-42"),
        # more than one sample -> plate only
        ("m", {"plate_id": 10131, "plate_sample_no_list": [1, 2]}, "m-101316"),
        # sample with no plate -> no suffix at all
        ("m", {"sample_no": 42}, "m"),
    ],
)
def test_label_suffix_rule(label, params, expected):
    assert _seq(label, params).sequence_label == expected


def test_source_precedence_is_first_that_yields_exactly_one():
    s = _seq(
        "m",
        {"plate_id": 10131, "sample_no": 7, "plate_sample_no_list": [1, 2, 3]},
    )
    assert s.sequence_label == "m-101316-7"


def test_applying_twice_is_idempotent():
    """init_seq may run more than once; the suffix must not stack."""
    s = _seq("m", {"plate_id": 10131, "sample_no": 42})
    s.apply_label_suffix()
    assert s.sequence_label == "m-101316-42"


def test_sequence_dir_is_year_monthday_and_uses_the_label_verbatim():
    s = _seq("m", {"plate_id": 10131})
    assert s.get_sequence_dir() == "2026/0925/094102__XRFS_noStandards__m-101316"


def test_sequence_dir_is_forward_slash():
    """Spec §9: stored run-relative paths are forward-slash on every platform."""
    assert "\\" not in _seq("m", {}).get_sequence_dir()


def test_experiment_dir_nests_under_the_sequence_output_dir_verbatim():
    """The invariant `d563cb67` restored, made falsifiable on Linux.

    ``sequence_output_dir`` is a ``Path`` field, so ``str()`` of it is
    OS-native -- backslashes on Windows. ``get_experiment_dir()`` joins onto
    that string, so if it normalizes separators the result no longer starts
    with ``str(sequence_output_dir)`` and every "nests under" assertion fails.
    That is a Windows-only break, which is why it was shipped twice.

    A backslash is an ordinary character in a POSIX path name, so seeding one
    here reproduces the failure on Linux: a method that rewrites ``\\`` to
    ``/`` breaks the prefix, a method that leaves it alone does not.

    The forward-slash contract lives at serialization (Path -> posix in
    yml/RPC), not in these methods' return values.
    """
    from helao.helpers.premodels import Experiment

    e = Experiment(experiment_name="exp")
    e.sequence_output_dir = Path(r"2026/0925/094102__s__l\odd")
    e.experiment_timestamp = TS

    got = e.get_experiment_dir()
    assert got.startswith(str(e.sequence_output_dir)), (
        f"{got!r} does not nest under {str(e.sequence_output_dir)!r} -- "
        "get_experiment_dir must not normalize separators (see d563cb67)"
    )
