# OpenAPI Client Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pluggable, runtime-detected pagination to the dynamic OpenAPI clients, with a per-method `limit` cap (default 100, `None` = fetch all with a tqdm progress bar).

**Architecture:** A new `helao/helpers/openapi_pagination.py` holds a `PaginationStrategy` ABC, a shared `_locate_items` helper, four concrete strategies, and an `AutoPagination` heuristic. `helao/helpers/openapi_client.py` gains a verb-agnostic pagination loop in `_BaseOpenAPIClient` (`_paginate` sync / `_apaginate` async), a shared single-request dispatch `_raw_request` (the only sync/async split), and threads a `limit` kwarg through every generated method.

**Tech Stack:** Python 3.12, httpx 0.28, tqdm 4.67. No pytest — tests are standalone scripts under `helao/core/tests/` using `httpx.MockTransport`, run with `python <path>` (`PYTHONPATH=.`).

---

## File Structure

- Create: `helao/helpers/openapi_pagination.py` — strategies + `_locate_items`.
- Create: `helao/core/tests/openapi_pagination_test.py` — strategy unit tests.
- Modify: `helao/helpers/openapi_client.py` — loop, `_raw_request`, `_quote_query`, `limit` kwarg, docstring line. `_build_request` stops quoting (quoting moves to `_quote_query`).
- Modify: `helao/core/tests/openapi_client_test.py` — paginated mock endpoint + integration tests.

Convention reminders: standalone test harness uses module-level `check(cond, msg)` / `expect_raises(...)` collecting into `_failures`; runner exits 1 on any failure. RED = run the script and see a specific `FAIL:` line; GREEN = `ALL PASSED`.

---

### Task 1: Pagination module skeleton — `PaginationStrategy` ABC + `_locate_items`

**Files:**
- Create: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/openapi_pagination_test.py`:

```python
"""Standalone unit tests for helao.helpers.openapi_pagination.

Run: PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py
"""

import httpx

from helao.helpers.openapi_pagination import (
    PaginationStrategy,
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
    check(PaginationStrategy().total_hint(resp({}), {}) is None,
          "base total_hint defaults to None")


def main():
    test_locate_items()
    test_base_total_hint_default()
    if _failures:
        print(f"\n{len(_failures)} FAILED")
        raise SystemExit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.helpers.openapi_pagination'`.

- [ ] **Step 3: Write minimal implementation**

Create `helao/helpers/openapi_pagination.py`:

```python
"""Pagination strategies for the dynamic OpenAPI clients.

A ``PaginationStrategy`` inspects each HTTP response at runtime and tells the
client (a) the list of items on the page, (b) how to fetch the next page, and
(c) an optional total count for progress bars. ``extract_items`` returning
``None`` means "this response is not paginated" — the client then returns the
response body unchanged.
"""

import re

_ITEM_FIELDS = ("items", "data", "results", "records")
_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')


def _locate_items(body, items_field=None):
    """Find the list of items in a response body.

    With ``items_field`` given, read that key from a dict body. Otherwise a
    bare list IS the items, or the first present of ``items``/``data``/
    ``results``/``records`` in a dict body. Returns ``None`` when no list is
    found.
    """
    if items_field is not None:
        return body.get(items_field) if isinstance(body, dict) else None
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for field in _ITEM_FIELDS:
            if isinstance(body.get(field), list):
                return body[field]
    return None


class PaginationStrategy:
    """Contract for runtime pagination handling."""

    def extract_items(self, response, body):
        """Return items list if the response IS paginated, else ``None``."""
        raise NotImplementedError

    def next_request(self, response, body, sent_params):
        """Return query params to merge for the next page, or ``None`` when
        exhausted. Return ``{"__next_url__": <abs url>}`` to follow a URL."""
        raise NotImplementedError

    def total_hint(self, response, body):
        """Optional total item count for a progress bar; ``None`` if unknown."""
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add PaginationStrategy ABC and item locator"
```

---

### Task 2: `CursorPagination`

**Files:**
- Modify: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Add to `openapi_pagination_test.py` (and add `CursorPagination` to the import from `helao.helpers.openapi_pagination`):

```python
from helao.helpers.openapi_pagination import CursorPagination


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
```

Add `test_cursor()` to `main()` before the failure check.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ImportError: cannot import name 'CursorPagination'`.

- [ ] **Step 3: Write minimal implementation**

Append to `openapi_pagination.py`:

```python
class CursorPagination(PaginationStrategy):
    """Body carries an opaque next cursor (null/absent when done).

    Args:
        cursor_field: Body key holding the next cursor.
        param: Query param name used to send the cursor on the next request.
        items_field: Optional explicit items key (else auto-located).
    """

    def __init__(self, cursor_field="next_cursor", param="cursor", items_field=None):
        self.cursor_field = cursor_field
        self.param = param
        self.items_field = items_field

    def extract_items(self, response, body):
        if isinstance(body, dict) and self.cursor_field in body:
            return _locate_items(body, self.items_field)
        return None

    def next_request(self, response, body, sent_params):
        cursor = body.get(self.cursor_field) if isinstance(body, dict) else None
        return {self.param: cursor} if cursor else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add CursorPagination strategy"
```

---

### Task 3: `OffsetPagination`

**Files:**
- Modify: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Add to test file (extend import with `OffsetPagination`):

```python
from helao.helpers.openapi_pagination import OffsetPagination


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
    # no total field, full page -> paginated, more pages assumed
    b3 = {"items": [1, 2]}
    check(s.extract_items(resp(b3), b3) == [1, 2], "full page without total is paginated")
    check(s.next_request(resp(b3), b3, {}) == {"offset": 2},
          "no total + full page -> continue")
    # no total, short page -> not more
    b4 = {"items": [1]}
    check(s.next_request(resp(b4), b4, {}) is None, "no total + short page -> stop")
```

Add `test_offset()` to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ImportError: cannot import name 'OffsetPagination'`.

- [ ] **Step 3: Write minimal implementation**

Append to `openapi_pagination.py`:

```python
class OffsetPagination(PaginationStrategy):
    """Offset/limit pagination. Paginated when a ``total`` field is present or
    a full page (``page_size`` items) is returned.

    Args:
        offset_param: Query param carrying the running offset.
        limit_param: Query param carrying the server page size (set per request).
        total_field: Body key holding the total item count.
        page_size: Expected server page size, used to detect "more pages" when
            no total is given.
        items_field: Optional explicit items key (else auto-located).
    """

    def __init__(self, offset_param="offset", limit_param="limit",
                 total_field="total", page_size=100, items_field=None):
        self.offset_param = offset_param
        self.limit_param = limit_param
        self.total_field = total_field
        self.page_size = page_size
        self.items_field = items_field

    def _items(self, body):
        return _locate_items(body, self.items_field)

    def extract_items(self, response, body):
        items = self._items(body)
        if items is None:
            return None
        has_total = isinstance(body, dict) and self.total_field in body
        if has_total or len(items) >= self.page_size:
            return items
        # No total and a short page: treat as a single, complete result set.
        # Still return items so the loop runs once; next_request returns None.
        return items

    def next_request(self, response, body, sent_params):
        items = self._items(body) or []
        current = sent_params.get(self.offset_param, 0)
        nxt = current + len(items)
        if isinstance(body, dict) and self.total_field in body:
            return {self.offset_param: nxt} if nxt < body[self.total_field] else None
        # No total: continue only while pages are full.
        return {self.offset_param: nxt} if len(items) >= self.page_size else None

    def total_hint(self, response, body):
        if isinstance(body, dict):
            return body.get(self.total_field)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add OffsetPagination strategy"
```

---

### Task 4: `PagePagination`

**Files:**
- Modify: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Add to test file (extend import with `PagePagination`):

```python
from helao.helpers.openapi_pagination import PagePagination


def test_page():
    print("test_page")
    s = PagePagination(page_size=2)  # page/per_page/total_pages
    b1 = {"items": [1, 2], "total_pages": 3}
    check(s.extract_items(resp(b1), b1) == [1, 2], "page extracts items (total_pages present)")
    check(s.next_request(resp(b1), b1, {}) == {"page": 2}, "page advances from default 1")
    check(s.next_request(resp(b1), b1, {"page": 3}) is None, "stop at last page")
    check(s.total_hint(resp(b1), b1) == 6, "total_hint = total_pages * page_size")
    # no total_pages, full page -> continue
    b2 = {"items": [1, 2]}
    check(s.next_request(resp(b2), b2, {}) == {"page": 2}, "full page without total -> continue")
    b3 = {"items": [1]}
    check(s.next_request(resp(b3), b3, {}) is None, "short page without total -> stop")
```

Add `test_page()` to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ImportError: cannot import name 'PagePagination'`.

- [ ] **Step 3: Write minimal implementation**

Append to `openapi_pagination.py`:

```python
class PagePagination(PaginationStrategy):
    """Page-number pagination. Paginated when ``total_pages_field`` is present
    or a full page (``page_size`` items) is returned.

    Args:
        page_param: Query param carrying the 1-based page number.
        size_param: Query param carrying the page size.
        total_pages_field: Body key holding the total page count.
        page_size: Expected server page size, used to detect "more pages" when
            no total is given.
        items_field: Optional explicit items key (else auto-located).
    """

    def __init__(self, page_param="page", size_param="per_page",
                 total_pages_field="total_pages", page_size=100, items_field=None):
        self.page_param = page_param
        self.size_param = size_param
        self.total_pages_field = total_pages_field
        self.page_size = page_size
        self.items_field = items_field

    def _items(self, body):
        return _locate_items(body, self.items_field)

    def extract_items(self, response, body):
        items = self._items(body)
        if items is None:
            return None
        return items

    def next_request(self, response, body, sent_params):
        items = self._items(body) or []
        current = sent_params.get(self.page_param, 1)
        if isinstance(body, dict) and self.total_pages_field in body:
            return {self.page_param: current + 1} if current < body[self.total_pages_field] else None
        return {self.page_param: current + 1} if len(items) >= self.page_size else None

    def total_hint(self, response, body):
        if isinstance(body, dict) and self.total_pages_field in body:
            return body[self.total_pages_field] * self.page_size
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add PagePagination strategy"
```

---

### Task 5: `LinkHeaderPagination`

**Files:**
- Modify: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Add to test file (extend import with `LinkHeaderPagination`):

```python
from helao.helpers.openapi_pagination import LinkHeaderPagination


def test_link_header():
    print("test_link_header")
    s = LinkHeaderPagination()
    body = [1, 2, 3]
    headers = {"Link": '<https://api.test/items?page=2>; rel="next"'}
    check(s.extract_items(resp(body, headers), body) == [1, 2, 3], "link extracts list body")
    check(
        s.next_request(resp(body, headers), body, {})
        == {"__next_url__": "https://api.test/items?page=2"},
        "link header next url parsed",
    )
    check(s.next_request(resp(body, {}), body, {}) is None, "no link header -> stop")
    check(s.extract_items(resp({"x": 1}, {}), {"x": 1}) is None,
          "non-list body without items -> not paginated")
```

Add `test_link_header()` to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ImportError: cannot import name 'LinkHeaderPagination'`.

- [ ] **Step 3: Write minimal implementation**

Append to `openapi_pagination.py`:

```python
class LinkHeaderPagination(PaginationStrategy):
    """RFC 5988 ``Link`` header pagination (GitHub-style). The body is the item
    list; the next page is the ``rel="next"`` URL in the ``Link`` header.

    Args:
        items_field: Optional explicit items key (else auto-located).
    """

    def __init__(self, items_field=None):
        self.items_field = items_field

    def extract_items(self, response, body):
        return _locate_items(body, self.items_field)

    def next_request(self, response, body, sent_params):
        link = response.headers.get("link", "")
        match = _LINK_NEXT_RE.search(link)
        return {"__next_url__": match.group(1)} if match else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add LinkHeaderPagination strategy"
```

---

### Task 6: `AutoPagination` heuristic

**Files:**
- Modify: `helao/helpers/openapi_pagination.py`
- Test: `helao/core/tests/openapi_pagination_test.py`

- [ ] **Step 1: Write the failing test**

Add to test file (extend import with `AutoPagination`):

```python
from helao.helpers.openapi_pagination import AutoPagination


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
    check(s.next_request(resp(body, headers), body, {}) == {"__next_url__": "https://api.test/next"},
          "auto detects link header")
    # offset/total body
    b3 = {"items": [1, 2], "total": 4}
    check(s.extract_items(resp(b3), b3) == [1, 2], "auto detects offset items")
    check(s.total_hint(resp(b3), b3) == 4, "auto offset total_hint")
    # not paginated
    b4 = {"id": 7, "name": "x"}
    check(s.extract_items(resp(b4), b4) is None, "auto: plain object not paginated")
```

Add `test_auto()` to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: FAIL — `ImportError: cannot import name 'AutoPagination'`.

- [ ] **Step 3: Write minimal implementation**

Append to `openapi_pagination.py`:

```python
_CURSOR_FIELDS = ("next_cursor", "next", "next_page_token", "nextPageToken")


class AutoPagination(PaginationStrategy):
    """Heuristic strategy for unknown APIs. Per response, probes in order:
    ``Link`` header next -> cursor-ish body field -> ``total``/``count`` body
    field. Falls back to "not paginated" when nothing matches.
    """

    def _detect(self, response, body):
        if _LINK_NEXT_RE.search(response.headers.get("link", "")):
            return LinkHeaderPagination()
        if isinstance(body, dict):
            for field in _CURSOR_FIELDS:
                if field in body:
                    if field == "next":
                        param = "cursor"
                    elif field.startswith("next_"):
                        param = field[len("next_"):]
                    else:
                        param = field
                    return CursorPagination(cursor_field=field, param=param)
            if "total" in body:
                return OffsetPagination(total_field="total")
            if "count" in body:
                return OffsetPagination(total_field="count")
        return None

    def extract_items(self, response, body):
        strat = self._detect(response, body)
        return strat.extract_items(response, body) if strat else None

    def next_request(self, response, body, sent_params):
        strat = self._detect(response, body)
        return strat.next_request(response, body, sent_params) if strat else None

    def total_hint(self, response, body):
        strat = self._detect(response, body)
        return strat.total_hint(response, body) if strat else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_pagination_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_pagination.py helao/core/tests/openapi_pagination_test.py
git commit -m "feat: add AutoPagination heuristic strategy"
```

---

### Task 7: Refactor client dispatch into shared `_raw_request` + `_quote_query` (no behavior change)

This isolates the single HTTP call so the pagination loop can reuse it. `_build_request` stops quoting; quoting moves to `_quote_query`, applied at dispatch. External behavior (httpx still receives quoted params) is unchanged. The existing `openapi_client_test.py` is the regression guard.

**Files:**
- Modify: `helao/helpers/openapi_client.py`
- Test: `helao/core/tests/openapi_client_test.py` (run existing, unchanged)

- [ ] **Step 1: Run existing tests to capture green baseline**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: `ALL PASSED` (9 checks).

- [ ] **Step 2: Modify `_build_request` to return RAW query params**

In `helao/helpers/openapi_client.py`, in `_BaseOpenAPIClient._build_request`, replace the quoting block at the end. Find:

```python
        relative_path_for_join = resolved_path_template.lstrip("/")
        full_url = urljoin(base_url, relative_path_for_join)

        quoted_query_params = {}
        for _key, value in query_params.items():
            key = quote(_key, safe="") if isinstance(_key, str) else _key
            quoted_query_params[key] = (
                quote(value, safe="") if isinstance(value, str) else value
            )

        return full_url, quoted_query_params, request_body_data
```

Replace with:

```python
        relative_path_for_join = resolved_path_template.lstrip("/")
        full_url = urljoin(base_url, relative_path_for_join)

        return full_url, query_params, request_body_data
```

- [ ] **Step 3: Add `_quote_query` and `_raw_request` (sync) to base + subclass**

In `_BaseOpenAPIClient`, add after `_build_request`:

```python
    @staticmethod
    def _quote_query(query_params):
        """Percent-quote string keys/values of a query-params dict."""
        quoted = {}
        for _key, value in query_params.items():
            key = quote(_key, safe="") if isinstance(_key, str) else _key
            quoted[key] = quote(value, safe="") if isinstance(value, str) else value
        return quoted
```

Add the abstract hook to `_BaseOpenAPIClient` (near `_fetch_spec`):

```python
    def _raw_request(self, op_id, http_method, url, raw_query, body):
        """Issue one request, returning the raw httpx.Response. Subclass impl."""
        raise NotImplementedError
```

In `OpenAPIClient`, add:

```python
    def _raw_request(self, op_id, http_method, url, raw_query, body):
        params = self._quote_query(raw_query)
        try:
            if http_method == "get":
                return self._client.get(url, params=params)
            return self._client.post(url, params=params, json=body)
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Request failed for operation '{op_id}' to {e.request.url}: {e}"
            )
```

In `AsyncOpenAPIClient`, add:

```python
    async def _raw_request(self, op_id, http_method, url, raw_query, body):
        params = self._quote_query(raw_query)
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
                if http_method == "get":
                    return await client.get(url, params=params)
                return await client.post(url, params=params, json=body)
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Request failed for operation '{op_id}' to {e.request.url}: {e}"
            )
```

- [ ] **Step 4: Rewrite `_make_method` bodies to use `_raw_request`**

In `OpenAPIClient._make_method`, replace the `dynamic_method` body with:

```python
        def dynamic_method(self_instance, **kwargs):
            """Generated method that dispatches a single API call."""
            full_url, raw_query, body = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )
            response = self_instance._raw_request(op_id, http_method, full_url, raw_query, body)
            return self_instance._handle_response(op_id, response)

        return dynamic_method
```

In `AsyncOpenAPIClient._make_method`, replace with:

```python
        async def dynamic_method(self_instance, **kwargs):
            """Generated async method that dispatches a single API call."""
            full_url, raw_query, body = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )
            response = await self_instance._raw_request(
                op_id, http_method, full_url, raw_query, body
            )
            return self_instance._handle_response(op_id, response)

        return dynamic_method
```

- [ ] **Step 5: Run existing tests to verify still green**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: `ALL PASSED` (9 checks) — behavior preserved.

- [ ] **Step 6: Commit**

```bash
git add helao/helpers/openapi_client.py
git commit -m "refactor: extract _raw_request/_quote_query for reuse by pagination"
```

---

### Task 8: Add paginated mock + RED integration tests (sync + async)

**Files:**
- Modify: `helao/core/tests/openapi_client_test.py`

- [ ] **Step 1: Add a cursor-paginated endpoint to the mock spec + handler**

In `openapi_client_test.py`, add a path to `SPEC["paths"]` (a sibling of `/items`):

```python
        "/things": {
            "get": {
                "operationId": "list_things",
                "summary": "List Things",
                "responses": {"200": {"description": "A page of things."}},
            }
        },
```

In `_handler`, add before the final `return httpx.Response(404, ...)`:

```python
    if request.method == "GET" and path == "/things":
        cursor = int(dict(request.url.params).get("cursor", 0))
        page = list(range(cursor, min(cursor + 10, 25)))
        nxt = cursor + 10
        return httpx.Response(
            200,
            json={"items": page, "next_cursor": str(nxt) if nxt < 25 else None},
        )
```

This serves 25 items (0..24) in pages of 10; `next_cursor` is null on the last page.

- [ ] **Step 2: Add an output-capture helper + write the failing tests**

Add near the top of `openapi_client_test.py` (after imports):

```python
import contextlib
import io

from helao.helpers.openapi_pagination import CursorPagination
```

Add a capture helper:

```python
@contextlib.contextmanager
def capture_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf
```

Add the sync pagination test:

```python
def test_sync_pagination():
    print("test_sync_pagination")
    client = OpenAPIClient(URL, pagination=CursorPagination())
    with capture_stdout() as out:
        res = client.list_things()  # default limit=100, fewer than cap
    check(res == list(range(25)), "sync default limit returns all 25 items")
    check("Pagination detected for 'list_things'" in out.getvalue(),
          "sync prints pagination-detected message")

    with capture_stdout() as out:
        res = client.list_things(limit=15)
    check(res == list(range(15)), "sync limit=15 caps to 15 items")
    check("Reached limit=15 for 'list_things'" in out.getvalue(),
          "sync prints more-results-available message at cap")

    with capture_stdout():
        res = client.list_things(limit=None)
    check(res == list(range(25)), "sync limit=None fetches all items")

    # pagination disabled -> raw first-page body unchanged
    plain = OpenAPIClient(URL)
    res = plain.list_things()
    check(res == {"items": list(range(10)), "next_cursor": "10"},
          "sync no-strategy returns raw first page")
    plain.close()
    client.close()
```

Add the async pagination test:

```python
def test_async_pagination():
    print("test_async_pagination")

    async def run():
        client = AsyncOpenAPIClient(URL, pagination=CursorPagination())
        with capture_stdout() as out:
            res = await client.list_things()
        check(res == list(range(25)), "async default limit returns all 25 items")
        check("Pagination detected for 'list_things'" in out.getvalue(),
              "async prints pagination-detected message")

        with capture_stdout() as out:
            res = await client.list_things(limit=15)
        check(res == list(range(15)), "async limit=15 caps to 15 items")
        check("Reached limit=15 for 'list_things'" in out.getvalue(),
              "async prints more-results-available message at cap")

        res = await client.list_things(limit=None)
        check(res == list(range(25)), "async limit=None fetches all items")
        client.close()

    asyncio.run(run())
```

Register both in `main()` after the existing calls:

```python
        test_sync_pagination()
        test_async_pagination()
```

- [ ] **Step 3: Run to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: FAIL — `OpenAPIClient(URL, pagination=...)` raises `TypeError: __init__() got an unexpected keyword argument 'pagination'` (constructor not yet updated).

- [ ] **Step 4: Commit the tests (red)**

```bash
git add helao/core/tests/openapi_client_test.py
git commit -m "test: add paginated mock and pagination integration tests (red)"
```

---

### Task 9: Wire pagination into the clients (GREEN)

**Files:**
- Modify: `helao/helpers/openapi_client.py`

- [ ] **Step 1: Import tqdm and accept a `pagination` arg in `__init__`**

At the top of `helao/helpers/openapi_client.py`, add imports:

```python
from tqdm import tqdm
```

In `_BaseOpenAPIClient.__init__`, change the signature and store the strategy. Find:

```python
    def __init__(self, openapi_json_url: str, api_key: str = ""):
```

Replace with:

```python
    def __init__(self, openapi_json_url: str, api_key: str = "", pagination=None):
```

Update its docstring Args by adding:

```
            pagination: Optional ``PaginationStrategy``. When ``None`` (default)
                pagination is disabled and generated methods return responses
                unchanged (the ``limit`` kwarg is then inert).
```

Immediately after `self.api_key = api_key`, add:

```python
        self.pagination = pagination
```

- [ ] **Step 2: Add `_merge_params`, `_paginate`, and `_apaginate` to the base**

In `_BaseOpenAPIClient`, add after `_quote_query`:

```python
    @staticmethod
    def _merge_params(base_params, extra):
        """Merge next-page params into the running params, dropping the
        internal ``__next_url__`` redirect key."""
        merged = dict(base_params)
        for key, value in extra.items():
            if key != "__next_url__":
                merged[key] = value
        return merged

    def _pagination_setup(self, op_id, first_response, limit):
        """Shared first-page handling. Returns (items, body) or (None, body)
        when not paginated. Emits the 'detected' message when paginated."""
        body = self._handle_response(op_id, first_response)
        if self.pagination is None:
            return None, body
        items = self.pagination.extract_items(first_response, body)
        if items is None:
            return None, body
        scope = "all" if limit is None else f"up to {limit}"
        print(f"Pagination detected for '{op_id}'; fetching {scope} items.")
        return list(items), body

    def _paginate(self, op_id, sent_params, first_response, limit, do_request):
        """Sync pagination loop. ``do_request(extra_params) -> httpx.Response``."""
        collected, body = self._pagination_setup(op_id, first_response, limit)
        if collected is None:
            return body  # not paginated
        strat = self.pagination
        response, params = first_response, dict(sent_params)
        bar = tqdm(total=strat.total_hint(first_response, body)) if limit is None else None
        try:
            while True:
                nxt = strat.next_request(response, body, params)
                if limit is not None and len(collected) >= limit:
                    if nxt is not None:
                        print(f"Reached limit={limit} for '{op_id}'; more results available.")
                    return collected[:limit]
                if nxt is None:
                    return collected
                response = do_request(nxt)
                body = self._handle_response(op_id, response)
                page = strat.extract_items(response, body) or []
                collected.extend(page)
                if bar is not None:
                    bar.update(len(page))
                params = self._merge_params(params, nxt)
        finally:
            if bar is not None:
                bar.close()

    async def _apaginate(self, op_id, sent_params, first_response, limit, do_request):
        """Async twin of ``_paginate``. ``do_request`` is a coroutine fn."""
        collected, body = self._pagination_setup(op_id, first_response, limit)
        if collected is None:
            return body
        strat = self.pagination
        response, params = first_response, dict(sent_params)
        bar = tqdm(total=strat.total_hint(first_response, body)) if limit is None else None
        try:
            while True:
                nxt = strat.next_request(response, body, params)
                if limit is not None and len(collected) >= limit:
                    if nxt is not None:
                        print(f"Reached limit={limit} for '{op_id}'; more results available.")
                    return collected[:limit]
                if nxt is None:
                    return collected
                response = await do_request(nxt)
                body = self._handle_response(op_id, response)
                page = strat.extract_items(response, body) or []
                collected.extend(page)
                if bar is not None:
                    bar.update(len(page))
                params = self._merge_params(params, nxt)
        finally:
            if bar is not None:
                bar.close()
```

- [ ] **Step 3: Thread `limit` + pagination through the sync `_make_method`**

In `OpenAPIClient._make_method`, replace the `dynamic_method` body (from Task 7) with:

```python
        def dynamic_method(self_instance, limit=100, **kwargs):
            """Generated method that dispatches an API call with pagination."""
            full_url, raw_query, body = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )

            def do_request(extra):
                if "__next_url__" in extra:
                    return self_instance._raw_request(
                        op_id, http_method, extra["__next_url__"], {}, body
                    )
                merged = self_instance._merge_params(raw_query, extra)
                return self_instance._raw_request(
                    op_id, http_method, full_url, merged, body
                )

            first = self_instance._raw_request(op_id, http_method, full_url, raw_query, body)
            return self_instance._paginate(op_id, raw_query, first, limit, do_request)

        return dynamic_method
```

- [ ] **Step 4: Thread `limit` + pagination through the async `_make_method`**

In `AsyncOpenAPIClient._make_method`, replace the `dynamic_method` body with:

```python
        async def dynamic_method(self_instance, limit=100, **kwargs):
            """Generated async method that dispatches an API call with pagination."""
            full_url, raw_query, body = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )

            async def do_request(extra):
                if "__next_url__" in extra:
                    return await self_instance._raw_request(
                        op_id, http_method, extra["__next_url__"], {}, body
                    )
                merged = self_instance._merge_params(raw_query, extra)
                return await self_instance._raw_request(
                    op_id, http_method, full_url, merged, body
                )

            first = await self_instance._raw_request(
                op_id, http_method, full_url, raw_query, body
            )
            return await self_instance._apaginate(op_id, raw_query, first, limit, do_request)

        return dynamic_method
```

- [ ] **Step 5: Run the integration tests to verify green**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: `ALL PASSED` (now includes the sync + async pagination checks). tqdm bars for `limit=None` print to stderr — harmless.

- [ ] **Step 6: Commit**

```bash
git add helao/helpers/openapi_client.py
git commit -m "feat: wire pluggable pagination + limit kwarg into OpenAPI clients"
```

---

### Task 10: Document the `limit` kwarg in generated docstrings

**Files:**
- Modify: `helao/helpers/openapi_client.py`
- Test: `helao/core/tests/openapi_client_test.py`

- [ ] **Step 1: Write the failing test**

In `openapi_client_test.py`, inside `test_sync` (after the existing docstring check), add:

```python
    check("limit (" in (client.get_item.__doc__ or ""),
          "generated docstring documents the limit parameter")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: FAIL — `FAIL: generated docstring documents the limit parameter`.

- [ ] **Step 3: Add the limit line in `_build_docstring`**

In `_BaseOpenAPIClient._build_docstring`, find the request-body docstring block that ends by appending to `param_docs_list`, then locate:

```python
        docstring_parts.append(
            "\n\nArgs:\n"
            + ("\n".join(param_docs_list) if param_docs_list else "    None")
        )
```

Immediately BEFORE that, add:

```python
        param_docs_list.append(
            "    limit (int|None, optional): Max objects to return across pages; "
            "None fetches all pages with a progress bar (default 100)."
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python helao/core/tests/openapi_client_test.py`
Expected: `ALL PASSED`.

- [ ] **Step 5: Commit**

```bash
git add helao/helpers/openapi_client.py helao/core/tests/openapi_client_test.py
git commit -m "docs: document limit kwarg in generated method docstrings"
```

---

## Self-Review

**Spec coverage:**
- Handle paginated responses → Tasks 1-6 (strategies) + Task 9 (loop). ✓
- Print message when pagination exists → Task 9 `_pagination_setup` + Task 8 asserts. ✓
- `limit` on every method, default 100 → Task 9 `dynamic_method(limit=100, ...)`. ✓
- `limit=None` fetches all + tqdm → Task 9 loop (`bar = tqdm(...) if limit is None`). ✓
- Parameterized style → Tasks 2-6 strategies + Task 9 `pagination=` arg. ✓
- Runtime detection → `extract_items` returning None across strategies; Task 9 `_pagination_setup`. ✓
- limit = client-side total cap → Task 9 truncation `collected[:limit]`. ✓
- GET + POST verb-agnostic → loop uses `do_request`/`_raw_request` independent of verb. ✓
- AutoPagination heuristic → Task 6. ✓
- Default pagination=None backward-compatible → Task 9 Step 1 + Task 8 no-strategy assertion. ✓
- Tests extend existing mock-transport script → Tasks 1,8 (+ new strategy test file). ✓

**Placeholder scan:** No TBD/TODO; all steps carry complete code. ✓

**Type/name consistency:** `_locate_items`, `_LINK_NEXT_RE`, `_quote_query`, `_raw_request(op_id, http_method, url, raw_query, body)`, `_merge_params`, `_pagination_setup`, `_paginate`/`_apaginate(op_id, sent_params, first_response, limit, do_request)`, `extract_items`/`next_request`/`total_hint`, `__next_url__` — used consistently across tasks. `_build_request` returns `(full_url, raw_query, body)` after Task 7; all callers updated. ✓

**Note on detection edge:** With `pagination=None`, a list-bodied endpoint returns the raw body (no loop) — verified by Task 8 no-strategy assertion against the dict-bodied `/things` first page.
