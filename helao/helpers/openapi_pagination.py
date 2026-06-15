"""Pagination strategies for the dynamic OpenAPI clients.

A ``PaginationStrategy`` inspects each HTTP response at runtime and tells the
client (a) the list of items on the page, (b) how to fetch the next page, and
(c) an optional total count for progress bars. ``extract_items`` returning
``None`` means "this response is not paginated" — the client then returns the
response body unchanged.
"""

import re
from abc import ABC, abstractmethod

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


class PaginationStrategy(ABC):
    """Contract for runtime pagination handling."""

    @abstractmethod
    def extract_items(self, response, body):
        """Return items list if the response IS paginated, else ``None``."""
        raise NotImplementedError

    @abstractmethod
    def next_request(self, response, body, sent_params):
        """Return query params to merge for the next page, or ``None`` when
        exhausted. Return ``{"__next_url__": <abs url>}`` to follow a URL."""
        raise NotImplementedError

    def total_hint(self, response, body):
        """Optional total item count for a progress bar; ``None`` if unknown."""
        return None


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
