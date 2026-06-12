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
