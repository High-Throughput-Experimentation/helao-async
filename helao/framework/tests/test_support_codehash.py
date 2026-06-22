"""Tests for helao.framework.support.codehash.

A pure, deterministic source-hash utility used for sequence/experiment code
versioning. Derived from the legacy git-hash approach but stdlib-only
(hashlib), so it is stable across runs without a git checkout.
"""
import inspect

import pytest

from helao.framework.support import codehash
from helao.framework.support.codehash import (
    code_hash,
    file_hash,
    object_hash,
)


def test_code_hash_is_deterministic():
    assert code_hash("def f():\n    return 1\n") == code_hash(
        "def f():\n    return 1\n"
    )


def test_code_hash_differs_for_different_input():
    assert code_hash("a = 1\n") != code_hash("a = 2\n")


def test_code_hash_returns_hex_string():
    h = code_hash("x")
    assert isinstance(h, str)
    assert all(c in "0123456789abcdef" for c in h)


def test_code_hash_length_truncation():
    short = code_hash("payload", length=8)
    full = code_hash("payload")
    assert len(short) == 8
    assert full.startswith(short)


def test_file_hash_matches_code_hash_of_contents(tmp_path):
    src = "def g():\n    return 42\n"
    p = tmp_path / "mod.py"
    p.write_text(src)
    assert file_hash(str(p)) == code_hash(src)
    assert file_hash(p) == code_hash(src)


def test_file_hash_missing_file_returns_empty():
    assert file_hash("/no/such/file/__nope__.py") == ""


def test_object_hash_of_function_is_stable():
    def sample():
        return "hello"

    h1 = object_hash(sample)
    h2 = object_hash(sample)
    assert h1 == h2
    assert h1 == code_hash(inspect.getsource(sample))


def test_object_hash_of_unsourceable_returns_empty():
    # builtins have no retrievable source
    assert object_hash(len) == ""
