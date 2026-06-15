"""Standalone unit tests for helao.helpers.openapi_pagination.

Run: PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py
"""

import httpx

from helao.helpers.openapi_pagination import (
    PaginationStrategy,
    CursorPagination,
    OffsetPagination,
    _locate_items,
)

_failures = []


def check(cond, msg):
    if cond:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        _failures.append(msg)


def resp(json_body, headers=None):
    return httpx.Response(200, json=json_body, headers=headers or {})


def test_locate_items():
    print("test_locate_items")
    check(_locate_items([1, 2, 3]) == [1, 2, 3], "bare list returned as items")
    check(_locate_items({"items": [1]}) == [1], "items field located")
    check(_locate_items({"data": [2]}) == [2], "data field located")
    check(_locate_items({"results": [3]}) == [3], "results field located")
    check(_locate_items({"records": [4]}) == [4], "records field located")
    check(_locate_items({"foo": [5]}, items_field="foo") == [5], "explicit field located")
    check(_locate_items({"nope": 1}) is None, "no list field -> None")
    check(_locate_items(42) is None, "scalar body -> None")


def test_base_total_hint_default():
    print("test_base_total_hint_default")

    class _Stub(PaginationStrategy):
        def extract_items(self, response, body):
            return None
        def next_request(self, response, body, sent_params):
            return None

    check(_Stub().total_hint(resp({}), {}) is None,
          "base total_hint defaults to None")


def test_cursor():
    print("test_cursor")
    s = CursorPagination()  # next_cursor / cursor
    b1 = {"items": [1, 2], "next_cursor": "abc"}
    check(s.extract_items(resp(b1), b1) == [1, 2], "cursor extracts items")
    check(s.next_request(resp(b1), b1, {}) == {"cursor": "abc"}, "cursor builds next param")
    b2 = {"items": [3], "next_cursor": None}
    check(s.next_request(resp(b2), b2, {}) is None, "null cursor ends pagination")
    b3 = {"foo": 1}  # no cursor field
    check(s.extract_items(resp(b3), b3) is None, "missing cursor field -> not paginated")
    s2 = CursorPagination(cursor_field="next", param="c", items_field="data")
    b4 = {"data": [9], "next": "tok"}
    check(s2.extract_items(resp(b4), b4) == [9], "configurable fields work")
    check(s2.next_request(resp(b4), b4, {}) == {"c": "tok"}, "configurable param works")


def test_offset():
    print("test_offset")
    s = OffsetPagination(page_size=2)  # offset/limit/total
    b1 = {"items": [1, 2], "total": 5}
    check(s.extract_items(resp(b1), b1) == [1, 2], "offset extracts items (total present)")
    check(s.next_request(resp(b1), b1, {}) == {"offset": 2}, "offset advances by page len")
    check(s.total_hint(resp(b1), b1) == 5, "offset total_hint reads total")
    b2 = {"items": [5], "total": 5}
    check(s.next_request(resp(b2), b2, {"offset": 4}) is None,
          "offset stops when offset+len >= total")
    b3 = {"items": [1, 2]}
    check(s.extract_items(resp(b3), b3) == [1, 2], "full page without total is paginated")
    check(s.next_request(resp(b3), b3, {}) == {"offset": 2},
          "no total + full page -> continue")
    b4 = {"items": [1]}
    check(s.next_request(resp(b4), b4, {}) is None, "no total + short page -> stop")


def main():
    test_locate_items()
    test_base_total_hint_default()
    test_cursor()
    test_offset()
    if _failures:
        print(f"\n{len(_failures)} FAILED")
        raise SystemExit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
