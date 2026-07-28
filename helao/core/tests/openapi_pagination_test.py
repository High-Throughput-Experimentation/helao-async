"""Standalone unit tests for helao.helpers.openapi_pagination.

Run: PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py
"""

import httpx

from helao.helpers.openapi_pagination import (
    PaginationStrategy,
    CursorPagination,
    OffsetPagination,
    PagePagination,
    LinkHeaderPagination,
    AutoPagination,
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
    check(
        _locate_items({"foo": [5]}, items_field="foo") == [5], "explicit field located"
    )
    check(_locate_items({"nope": 1}) is None, "no list field -> None")
    check(_locate_items(42) is None, "scalar body -> None")


def test_base_total_hint_default():
    print("test_base_total_hint_default")

    class _Stub(PaginationStrategy):
        def extract_items(self, response, body):
            return None

        def next_request(self, response, body, sent_params):
            return None

    check(_Stub().total_hint(resp({}), {}) is None, "base total_hint defaults to None")


def test_cursor():
    print("test_cursor")
    s = CursorPagination()  # next_cursor / cursor
    b1 = {"items": [1, 2], "next_cursor": "abc"}
    check(s.extract_items(resp(b1), b1) == [1, 2], "cursor extracts items")
    check(
        s.next_request(resp(b1), b1, {}) == {"cursor": "abc"},
        "cursor builds next param",
    )
    b2 = {"items": [3], "next_cursor": None}
    check(s.next_request(resp(b2), b2, {}) is None, "null cursor ends pagination")
    b3 = {"foo": 1}  # no cursor field
    check(
        s.extract_items(resp(b3), b3) is None, "missing cursor field -> not paginated"
    )
    s2 = CursorPagination(cursor_field="next", param="c", items_field="data")
    b4 = {"data": [9], "next": "tok"}
    check(s2.extract_items(resp(b4), b4) == [9], "configurable fields work")
    check(s2.next_request(resp(b4), b4, {}) == {"c": "tok"}, "configurable param works")


def test_offset():
    print("test_offset")
    s = OffsetPagination(page_size=2)  # offset/limit/total
    b1 = {"items": [1, 2], "total": 5}
    check(
        s.extract_items(resp(b1), b1) == [1, 2], "offset extracts items (total present)"
    )
    check(
        s.next_request(resp(b1), b1, {}) == {"offset": 2}, "offset advances by page len"
    )
    check(s.total_hint(resp(b1), b1) == 5, "offset total_hint reads total")
    b2 = {"items": [5], "total": 5}
    check(
        s.next_request(resp(b2), b2, {"offset": 4}) is None,
        "offset stops when offset+len >= total",
    )
    b3 = {"items": [1, 2]}
    check(
        s.extract_items(resp(b3), b3) == [1, 2], "full page without total is paginated"
    )
    check(
        s.next_request(resp(b3), b3, {}) == {"offset": 2},
        "no total + full page -> continue",
    )
    b4 = {"items": [1]}
    check(s.next_request(resp(b4), b4, {}) is None, "no total + short page -> stop")
    b5 = {"items": []}
    check(
        s.next_request(resp(b5), b5, {"offset": 4}) is None,
        "empty page without total -> stop",
    )


def test_page():
    print("test_page")
    s = PagePagination(page_size=2)  # page/per_page/total_pages
    b1 = {"items": [1, 2], "total_pages": 3}
    check(
        s.extract_items(resp(b1), b1) == [1, 2],
        "page extracts items (total_pages present)",
    )
    check(
        s.next_request(resp(b1), b1, {}) == {"page": 2}, "page advances from default 1"
    )
    check(s.next_request(resp(b1), b1, {"page": 3}) is None, "stop at last page")
    check(s.total_hint(resp(b1), b1) == 6, "total_hint = total_pages * page_size")
    b2 = {"items": [1, 2]}
    check(
        s.next_request(resp(b2), b2, {}) == {"page": 2},
        "full page without total -> continue",
    )
    b3 = {"items": [1]}
    check(s.next_request(resp(b3), b3, {}) is None, "short page without total -> stop")


def test_link_header():
    print("test_link_header")
    s = LinkHeaderPagination()
    body = [1, 2, 3]
    headers = {"Link": '<https://api.test/items?page=2>; rel="next"'}
    check(
        s.extract_items(resp(body, headers), body) == [1, 2, 3],
        "link extracts list body",
    )
    check(
        s.next_request(resp(body, headers), body, {})
        == {"__next_url__": "https://api.test/items?page=2"},
        "link header next url parsed",
    )
    check(s.next_request(resp(body, {}), body, {}) is None, "no link header -> stop")
    check(
        s.extract_items(resp({"x": 1}, {}), {"x": 1}) is None,
        "non-list body without items -> not paginated",
    )


def test_auto():
    print("test_auto")
    s = AutoPagination()
    # cursor body
    b1 = {"items": [1], "next_cursor": "z"}
    check(s.extract_items(resp(b1), b1) == [1], "auto detects cursor items")
    check(s.next_request(resp(b1), b1, {}) == {"cursor": "z"}, "auto cursor next param")
    # link header
    body = [1, 2]
    headers = {"Link": '<https://api.test/next>; rel="next"'}
    check(
        s.next_request(resp(body, headers), body, {})
        == {"__next_url__": "https://api.test/next"},
        "auto detects link header",
    )
    # offset/total body
    b3 = {"items": [1, 2], "total": 4}
    check(s.extract_items(resp(b3), b3) == [1, 2], "auto detects offset items")
    check(s.total_hint(resp(b3), b3) == 4, "auto offset total_hint")
    # not paginated
    b4 = {"id": 7, "name": "x"}
    check(s.extract_items(resp(b4), b4) is None, "auto: plain object not paginated")
    # DRF-style next URL in body field -> __next_url__ (not a cursor param)
    b5 = {"results": [1, 2], "next": "https://api.test/x?page=2"}
    check(s.extract_items(resp(b5), b5) == [1, 2], "auto DRF extracts results")
    check(
        s.next_request(resp(b5), b5, {})
        == {"__next_url__": "https://api.test/x?page=2"},
        "auto DRF next-url -> __next_url__",
    )
    b6 = {"results": [3], "next": None}
    check(s.next_request(resp(b6), b6, {}) is None, "auto DRF null next -> stop")


def main():
    test_locate_items()
    test_base_total_hint_default()
    test_cursor()
    test_offset()
    test_page()
    test_link_header()
    test_auto()
    if _failures:
        print(f"\n{len(_failures)} FAILED")
        raise SystemExit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
