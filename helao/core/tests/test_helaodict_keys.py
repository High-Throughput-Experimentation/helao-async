"""``HelaoDict._serialize_dict`` must not call ``str`` methods on non-str keys.

The dunder filter skips ``"__x": <str>`` entries. It used to call
``k.startswith`` on every key whose value was a str, so an int key crashed.
"""

from helao.core.helaodict import HelaoDict


def test_int_key_with_str_value_serializes():
    assert HelaoDict()._serialize_dict({1: "a"}) == {1: "a"}


def test_dunder_str_entries_are_still_skipped():
    assert HelaoDict()._serialize_dict({"__x": "y", "a": "b"}) == {"a": "b"}
