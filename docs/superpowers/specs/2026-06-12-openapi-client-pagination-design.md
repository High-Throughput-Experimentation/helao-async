# OpenAPI Client Pagination — Design

Date: 2026-06-12
Target: `helao/helpers/openapi_client.py`

## Goal

Extend `OpenAPIClient` (sync) and `AsyncOpenAPIClient` (async) so the dynamically
generated operation methods transparently handle paginated API responses.

Requirements (from request):

1. Handle responses with pagination.
2. Generated methods print a message when pagination exists in a response.
3. Every applicable method gains a `limit` parameter capping the number of
   returned objects, default `100`.
4. `limit=None` → retrieve **all** objects across pages, showing a `tqdm`
   progress bar.

## Clarified decisions

- **Pagination style is parameterized** via a pluggable `PaginationStrategy`
  passed to the client constructor. Built-in strategies cover the common
  conventions; users may subclass for bespoke APIs.
- **Paginated responses are detected at runtime** — the strategy inspects each
  response. A response without pagination markers is returned unchanged
  (fully backward-compatible).
- **`limit` is a client-side total cap** (objects returned to the caller), not a
  server page-size knob. Server page size is the strategy's concern.
- **Pagination loop applies to GET and POST** uniformly, driven by runtime
  detection. POST keeps its JSON body constant across page fetches.
- **An `AutoPagination` heuristic strategy is included** as a convenience for
  unknown APIs.
- **Default `pagination=None`** → pagination disabled; methods still accept
  `limit` but it is inert. Opt-in by passing a strategy.

## Architecture

Builds on the existing `_BaseOpenAPIClient` / `OpenAPIClient` / `AsyncOpenAPIClient`
split. Pagination logic is verb- and sync/async-agnostic except for the single
HTTP dispatch, which already lives in each subclass.

### `PaginationStrategy` (ABC, new)

```python
class PaginationStrategy:
    def extract_items(self, response, body) -> list | None:
        """Return the list of items if `response`/`body` IS paginated,
        else None (caller then returns the body unchanged)."""

    def next_request(self, response, body, sent_params) -> dict | None:
        """Return query params to MERGE into the next page request, or None
        when no further pages exist. To follow an absolute next-page URL
        (e.g. Link header), return {"__next_url__": "<absolute url>"}."""

    def total_hint(self, response, body) -> int | None:
        """Optional total item count to seed the tqdm bar (offset/page
        styles). Return None when unknown (cursor/link styles)."""
```

Shared helper (module-level or base method) for runtime item location when a
strategy does not override it:

```python
_ITEM_FIELDS = ("items", "data", "results", "records")

def _locate_items(body, items_field=None):
    if items_field is not None:
        return body.get(items_field) if isinstance(body, dict) else None
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for f in _ITEM_FIELDS:
            if isinstance(body.get(f), list):
                return body[f]
    return None
```

### Built-in strategies

All take optional constructor args to override field/param names.

- **`CursorPagination(cursor_field="next_cursor", param="cursor", items_field=None)`**
  - `extract_items`: `_locate_items(body, items_field)` when `cursor_field` key
    is present in body (even if null); else None.
  - `next_request`: cursor = `body.get(cursor_field)`; if truthy →
    `{param: cursor}`, else None.
  - `total_hint`: None.

- **`OffsetPagination(offset_param="offset", limit_param="limit", total_field="total", items_field=None)`**
  - `extract_items`: items via `_locate_items`; paginated when `total_field`
    present OR a full page returned.
  - `next_request`: next offset = `sent_params.get(offset_param, 0) + len(items)`;
    return `{offset_param: next_offset}` while `next_offset < total` (or while
    last page was full when total unknown); else None.
  - `total_hint`: `body.get(total_field)`.

- **`PagePagination(page_param="page", size_param="per_page", total_pages_field="total_pages", items_field=None)`**
  - `extract_items`: items via `_locate_items`; paginated when `total_pages_field`
    present OR a full page returned.
  - `next_request`: next page = `sent_params.get(page_param, 1) + 1`; stop when
    `page >= total_pages` (or when last page not full / empty when unknown).
  - `total_hint`: `total_pages * page_size` if derivable, else None.

- **`LinkHeaderPagination(items_field=None)`**
  - `extract_items`: `_locate_items(body, items_field)` (typically body is a list).
  - `next_request`: parse `response.headers.get("link")` for `rel="next"`;
    return `{"__next_url__": url}` or None.
  - `total_hint`: None.

- **`AutoPagination(...)`** — heuristic, tries in order per response:
  1. `Link` header with `rel="next"` → behave like `LinkHeaderPagination`.
  2. Body dict with a cursor-ish field (`next_cursor`, `next`, `next_page_token`,
     `nextPageToken`) → behave like `CursorPagination` against that field, using
     a matching cursor query param name (configurable map; default reuses the
     field name minus a `next`/`next_` prefix, e.g. `next_cursor` → `cursor`).
  3. Body dict with `total`/`count` + offset-able items → behave like
     `OffsetPagination`.
  Otherwise `extract_items` returns None (not paginated).
  AutoPagination memoizes which sub-mode it detected for a given operation only
  within a single method call (not across calls).

### Pagination loop (in `_BaseOpenAPIClient`)

Two twins because of sync/async dispatch: `_paginate(...)` (sync) and
`_apaginate(...)` (async). They are structurally identical apart from
`await`/`async with`; the per-page dispatch reuses the subclass's existing
request code (factored so both the single-call path and the loop share it).

Pseudocode (sync):

```python
def _paginate(self, op_id, do_request, sent_params, first_response):
    body = decode(first_response)
    items = self.pagination.extract_items(first_response, body)
    if items is None:
        return self._handle_response(op_id, first_response)  # not paginated

    print(f"Pagination detected for '{op_id}'; fetching "
          f"{'all' if self._limit is None else f'up to {self._limit}'} items.")

    collected = list(items)
    response, params = first_response, dict(sent_params)
    bar = tqdm(total=self.pagination.total_hint(response, body)) if self._limit is None else None
    try:
        while True:
            if self._limit is not None and len(collected) >= self._limit:
                if self.pagination.next_request(response, body, params) is not None:
                    print(f"Reached limit={self._limit} for '{op_id}'; more results available.")
                collected = collected[: self._limit]
                break
            nxt = self.pagination.next_request(response, body, params)
            if nxt is None:
                break
            response = do_request(nxt)           # subclass dispatch (merges params / __next_url__)
            # raises RuntimeError on non-2xx, same as _handle_response
            body = self._raise_and_decode(response)
            page = self.pagination.extract_items(response, body) or []
            collected.extend(page)
            if bar is not None:
                bar.update(len(page))
    finally:
        if bar is not None:
            bar.close()
    return collected
```

The `limit` value is passed into the loop per call (popped from kwargs), not
stored on the instance, to stay reentrant/thread-safe — shown above as
`self._limit` only for brevity; implementation threads it as a parameter.

### Generated method signature change

Each generated `dynamic_method` pops `limit` from kwargs (default `100`) before
building the request, then routes the first response through `_paginate` /
`_apaginate`:

```python
def dynamic_method(self_instance, *, limit=100, **kwargs):
    full_url, query, body = self_instance._build_request(...)
    def do_request(extra_params):   # closure used for page N>1
        merged, url = merge_next(full_url, query, extra_params)
        return self_instance._raw_request(http_method, url, merged, body)
    first = self_instance._raw_request(http_method, full_url, query, body)
    return self_instance._paginate(op_id, do_request, query, first, limit)
```

`_raw_request` is the new shared single-call dispatch (the part that currently
lives inline in each subclass's `_make_method`), returning the raw
`httpx.Response` and translating `httpx.RequestError` → `RuntimeError`.
`merge_next` applies `{"__next_url__": ...}` (replace URL) or merges query params.

`limit` is documented in the generated docstring (added by `_build_docstring`).

## Error handling

- Non-2xx on any page → `RuntimeError` (existing `_handle_response` behavior),
  aborting the loop.
- `RequestError` on any page → `RuntimeError` (existing behavior).
- A strategy returning malformed/None items mid-loop is treated as an empty
  page (loop ends on next `next_request` None) — no crash.
- `tqdm` import is at module top (dependency confirmed present, 4.67.3).

## Backward compatibility

- `pagination=None` (default): `extract_items` never called; methods behave
  exactly as today, except they now accept (and ignore) `limit`.
- Existing single-object GET/POST responses (non-list, no markers) detected as
  not-paginated → returned unchanged.

## Testing (extend `helao/core/tests/openapi_client_test.py`)

Add a cursor-paginated mock endpoint serving 3 pages (e.g. items 0..24,
`page_size=10`, `next_cursor` field). Assert, sync and async, with
`CursorPagination`:

1. Default `limit=100` returns all 25 (fewer than cap) — full set, no truncation.
2. `limit=15` returns exactly 15 and prints the "more results available" notice.
3. `limit=None` returns all 25 (tqdm bar path executes without error).
4. "Pagination detected" message printed when paginated.
5. Non-paginated endpoint (existing `get_item`) unaffected, `limit` inert.
6. `pagination=None` client: paginated endpoint returns only the raw first-page
   body unchanged (no loop).

Captured stdout checked for the printed messages. tqdm output goes to stderr;
test sets `file`/disable as needed or just asserts return values for the
`limit=None` case.

## Out of scope

- Concurrent/prefetch page fetching (sequential only).
- Persisting/streaming items (returns a fully materialized list).
- Rate-limit/retry handling.
