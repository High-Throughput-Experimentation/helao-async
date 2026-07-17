"""UUID -> ordinal mapping incl. the uuid5 process-derivation check (§5.5)."""

import uuid

import pytest

from harness.uuidmap import UuidMapper

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def test_ordinals_follow_first_seen_order():
    m = UuidMapper()
    assert m.map(U1) == "UUID-0"
    assert m.map(U2) == "UUID-1"
    assert m.map(U1) == "UUID-0"  # stable on re-query
    assert m.map(U1.upper()) == "UUID-0"  # case-insensitive


def test_sub_replaces_embedded_uuids():
    m = UuidMapper()
    text = f"raw_data/{U1}/WsSim-0.0.0.0__0.hlo.json"
    assert m.sub(text) == "raw_data/UUID-0/WsSim-0.0.0.0__0.hlo.json"


def test_sub_strict_raises_on_unseeded_uuid():
    m = UuidMapper()
    with pytest.raises(KeyError):
        m.sub(f"x/{U1}/y", strict=True)
    m.map(U1)
    assert m.sub(f"x/{U1}/y", strict=True) == "x/UUID-0/y"


def test_process_uuid_derivation_is_checked():
    # spec §5.5: when an exp has no process_list,
    # process_uuid = uuid5(NAMESPACE_URL, f"{experiment_uuid}__{pidx}") —
    # normalize by tagging the derivation so the diff CHECKS it.
    m = UuidMapper()
    exp = U1
    derived = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{exp}__0"))
    assert m.register_derived(derived, exp, 0) is True
    assert m.map(derived) == "DERIVED:UUID-0__0"
    # a non-derived uuid is NOT tagged and falls through to ordinary mapping
    assert m.register_derived(U2, exp, 1) is False
    assert m.map(U2) == "UUID-1"


def test_sub_any_recurses_dicts_and_lists():
    m = UuidMapper()
    obj = {"a": [U1, {"b": U2}], "c": "no uuid here"}
    assert m.sub_any(obj) == {
        "a": ["UUID-0", {"b": "UUID-1"}],
        "c": "no uuid here",
    }
