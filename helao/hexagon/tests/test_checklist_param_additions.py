"""`filter_allowed_param_additions` allows exactly one kind of route change.

A listed route may gain the listed parameters while every frozen parameter
stays as frozen. Each new one must match the annotation and default its entry
pins, have a literal (or literal ``Query``/``Header``/``Cookie``) default, and
have a scalar annotation. That is the one change a caller written against the
frozen record cannot notice. Everything else still fails, however the entry is
worded. The bypass cases below are the ones review reproduced against the
earlier, looser rule; each returned 422 to an old caller.

``strip_listed_additions`` is the freezer's half: it hides listed additions
from ``--accept-drift`` and must never strip a parameter the record has.
"""

import pytest

from harness.endpoints import (
    diff_route_sets,
    filter_allowed_param_additions,
    is_optional_query_default,
    is_scalar_annotation,
)
from harness.freeze import strip_listed_additions

ROUTE = {"path": "/PSTAT/run_CV", "method": "post", "tags": ["action"]}
FROZEN = [
    {"name": "Vinit__V", "annotation": "float", "default": "0.0"},
    {"name": "samples", "annotation": "List[str]", "default": "[]"},
]
NEW = {"name": "versus_OCV", "annotation": "bool", "default": "False"}
PIN = {"annotation": "bool", "default": "False"}
ENTRY = [{"path": "/PSTAT/run_CV", "method": "post", "params": {"versus_OCV": PIN}}]


def _diffs(current_params, tags=("action",)):
    frozen = [{**ROUTE, "params": FROZEN}]
    current = [{**ROUTE, "tags": list(tags), "params": current_params}]
    return diff_route_sets(frozen, current)


def _allowed_with(default: str, annotation: str = "bool") -> bool:
    """Gate verdict for a new param whose entry pins exactly what it carries."""
    new = {**NEW, "annotation": annotation, "default": default}
    pin = {"annotation": annotation, "default": default}
    entry = [{**ENTRY[0], "params": {"versus_OCV": pin}}]
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [new]), entry)
    return failing == []


def test_listed_optional_param_is_allowed():
    failing, allowed = filter_allowed_param_additions(_diffs(FROZEN + [NEW]), ENTRY)
    assert failing == [] and len(allowed) == 1


def test_pep585_respelling_of_a_frozen_param_still_counts_as_unchanged():
    respelled = [FROZEN[0], {**FROZEN[1], "annotation": "list[str]"}, NEW]
    failing, _ = filter_allowed_param_additions(_diffs(respelled), ENTRY)
    assert failing == []


def test_unlisted_new_param_fails():
    other = {"name": "surprise", "annotation": "int", "default": "0"}
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [NEW, other]), ENTRY)
    assert len(failing) == 1


def test_entry_naming_a_param_that_was_not_added_fails():
    entry = [{**ENTRY[0], "params": {"versus_OCV": PIN, "never_added": PIN}}]
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [NEW]), entry)
    assert len(failing) == 1


def test_changed_frozen_default_fails_even_when_listed():
    changed = [{**FROZEN[0], "default": "0.1"}, FROZEN[1], NEW]
    failing, _ = filter_allowed_param_additions(_diffs(changed), ENTRY)
    assert len(failing) == 1


def test_removed_frozen_param_fails_even_when_listed():
    failing, _ = filter_allowed_param_additions(_diffs([FROZEN[0], NEW]), ENTRY)
    assert len(failing) == 1


def test_reordered_frozen_params_fail():
    failing, _ = filter_allowed_param_additions(
        _diffs([FROZEN[1], FROZEN[0], NEW]), ENTRY
    )
    assert len(failing) == 1


def test_unlisted_route_fails():
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [NEW]), [])
    assert len(failing) == 1


def test_tags_change_on_a_listed_route_fails():
    failing, allowed = filter_allowed_param_additions(
        _diffs(FROZEN + [NEW], tags=("private",)), ENTRY
    )
    assert [d["field"] for d in failing] == ["tags"]
    assert [d["field"] for d in allowed] == ["params"]


def test_missing_and_extra_routes_are_never_allowed():
    frozen = [{**ROUTE, "params": FROZEN}]
    current = [{**ROUTE, "path": "/PSTAT/run_CV2", "params": FROZEN}]
    entries = ENTRY + [{**ENTRY[0], "path": "/PSTAT/run_CV2"}]
    failing, allowed = filter_allowed_param_additions(
        diff_route_sets(frozen, current), entries
    )
    assert {d["kind"] for d in failing} == {"missing", "extra"} and allowed == []


def test_default_other_than_the_pinned_one_fails():
    """`bool = True` is schema-compatible but changes every existing caller."""
    new = {**NEW, "default": "True"}
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [new]), ENTRY)
    assert len(failing) == 1


def test_annotation_other_than_the_pinned_one_fails():
    """A later retype must not ride on an approved entry."""
    new = {**NEW, "annotation": "int"}
    failing, _ = filter_allowed_param_additions(_diffs(FROZEN + [new]), ENTRY)
    assert len(failing) == 1


@pytest.mark.parametrize(
    "default",
    [
        "Query(...)",
        "Query()",
        "Query(default=...)",
        "...",
        "Query(..., ge=0)",
        "Query(default_factory=list)",
        "fastapi.Query(1)",
        "Q(...)",
        "Q(1)",
        "Depends(dep)",
        "REQ",
        "Body(1)",
        "Body(1, embed=True)",
        "B(1)",
        "Form('x')",
        "File(None)",
    ],
)
def test_defaults_outside_the_allowlist_fail_even_when_pinned(default):
    """Required, body, dependency, aliased and named-constant defaults all fail."""
    assert not _allowed_with(default)


@pytest.mark.parametrize(
    "default",
    ["False", "None", "0.1", "'auto'", "Query(-1, ge=-1, le=3)", "Query(default=2)"],
)
def test_literal_and_literal_query_defaults_pass(default):
    assert _allowed_with(default)


@pytest.mark.parametrize(
    "annotation",
    [
        "list[int]",
        "Optional[list[int]]",
        "List[int]",
        "Dict[str, int]",
        "tuple[int, int]",
        "Annotated[int, Body()]",
        "Annotated[int, Query()]",
        "UploadFile",
    ],
)
def test_container_and_marker_annotations_fail_even_when_pinned(annotation):
    """FastAPI reads these as body (or multi-value) fields, whatever the default."""
    assert not _allowed_with("None", annotation)


@pytest.mark.parametrize(
    "annotation", ["bool", "float", "Optional[GamrySamplingMode]", "Literal['a', 'b']"]
)
def test_scalar_annotations_pass(annotation):
    assert _allowed_with("None", annotation)


def test_no_default_and_no_annotation_are_refused():
    assert not is_optional_query_default(None)
    assert not is_scalar_annotation(None)


# --- freezer strip ------------------------------------------------------------


def _strip(current_params, entry_params):
    frozen = [{**ROUTE, "params": FROZEN}]
    current = [{**ROUTE, "params": current_params}]
    entries = [{**ENTRY[0], "params": entry_params}]
    return strip_listed_additions(current, frozen, entries)[0]["params"]


def test_strip_hides_a_listed_addition_from_the_merge():
    assert _strip(FROZEN + [NEW], {"versus_OCV": PIN}) == FROZEN


def test_strip_never_removes_a_frozen_param_even_when_listed():
    """A mistaken entry naming a frozen param must not let a merge delete it."""
    pin = {"annotation": "float", "default": "0.0"}
    assert _strip(FROZEN + [NEW], {"Vinit__V": pin, "versus_OCV": PIN}) == FROZEN


def test_strip_keeps_an_addition_that_drifted_from_its_pin():
    drifted = {**NEW, "default": "True"}
    assert _strip(FROZEN + [drifted], {"versus_OCV": PIN}) == FROZEN + [drifted]
