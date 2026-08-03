"""Collapsible HTML renderers shared by both operator UIs.

The operator shows two kinds of nested detail: the attributes of a selected
sequence/experiment/action object, and the docstring of a selected library
item. Both render as nested ``<details>`` elements, which collapse and expand
with no JavaScript of their own -- so the same string serves Bokeh's ``Div``
and Reflex's ``rx.html``.

These lived as private helpers inside :mod:`bokeh_operator`, which meant the
Reflex operator had no way to show either without reimplementing them. They
belong beside :mod:`param_forms`, :mod:`param_store` and :mod:`spec_parser`
for the same reason those do: one logic layer, two UIs.

Every data value is HTML-escaped here, because the caller interpolates the
result straight into markup.
"""

__all__ = [
    "render_node",
    "object_to_html",
    "open_keys_for",
    "truncate_uuid",
    "tree_header_text",
    "server_header_text",
    "doc_to_html",
]

import html as _html
import re

from helao.core.servers.operator.param_forms import parse_arg_docs

#: Section headers that end an ``Args:`` block in a Google-style docstring.
_ARGS_HEADER = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.I)
_NEXT_SECTION = re.compile(
    r"^\s*(Returns?|Raises|Yields?|Examples?|Notes?|Attributes)\s*:\s*$",
    re.I,
)


def render_node(key, val, top=False, open_keys=()):
    """Render one object node as collapsible HTML. Top-level nodes whose key is
    in ``open_keys`` start expanded; everything else starts collapsed."""
    open_attr = " open" if (top and key in open_keys) else ""
    label = _html.escape(str(key))
    if isinstance(val, dict):
        inner = "".join(
            render_node(k, v, top=False, open_keys=open_keys) for k, v in val.items()
        )
        return f"<details{open_attr}><summary>{label}</summary>{inner}</details>"
    if isinstance(val, (list, tuple)):
        inner = "".join(
            render_node(f"[{i}]", v, top=False, open_keys=open_keys)
            for i, v in enumerate(val)
        )
        return (
            f"<details{open_attr}><summary>{label} [{len(val)}]</summary>"
            f"{inner}</details>"
        )
    return f"<div style='margin-left:1em'>{label}: {_html.escape(str(val))}</div>"


def object_to_html(obj, open_keys=()):
    """Render a dict (or scalar) as a nested ``<details>`` tree string."""
    if not isinstance(obj, dict):
        return f"<div>{_html.escape(str(obj))}</div>"
    if not obj:
        return "<div><i>empty</i></div>"
    return "".join(
        render_node(k, v, top=True, open_keys=open_keys) for k, v in obj.items()
    )


def open_keys_for(obj):
    """Top-level keys to expand by default: any ``*_params`` key.

    The parameters are what an operator inspecting a queued or finished object
    is nearly always looking for, so they start open while the rest stays
    collapsed.
    """
    if not isinstance(obj, dict):
        return []
    return [k for k in obj if k.endswith("_params")]


def truncate_uuid(value):
    """Last 8 characters of a uuid, which is enough to tell rows apart."""
    return str(value)[-8:] if value else ""


def tree_header_text(kind, obj):
    """Header line for a sequence/experiment/action object: 'name · uuid8'.

    Data fields are HTML-escaped so the result is safe to interpolate directly
    into markup (e.g. ``<b>{header_text}</b>``); the literal middle dot is not
    data and is left unescaped.
    """
    name = obj.get(f"{kind}_name", "") if isinstance(obj, dict) else ""
    uuid8 = truncate_uuid(obj.get(f"{kind}_uuid")) if isinstance(obj, dict) else ""
    name = _html.escape(str(name))
    uuid8 = _html.escape(str(uuid8))
    return f"{name} · {uuid8}" if uuid8 else f"{name}"


def server_header_text(server_name, cfg):
    """Header line for an action-server row: 'NAME · host:port'.

    Data fields are HTML-escaped so the result is safe to interpolate directly
    into markup; the literal middle dot is not data and is left unescaped.
    """
    cfg = cfg or {}
    name = _html.escape(str(server_name))
    host = _html.escape(str(cfg.get("host", "")))
    port = _html.escape(str(cfg.get("port", "")))
    return f"{name} · {host}:{port}"


def doc_to_html(doc: str) -> str:
    """Render a docstring as HTML, with the ``Args:`` block as a collapsed tree.

    Text before/after the ``Args:`` section is kept as-is (newlines -> <br>);
    the argument list is rendered inside a closed ``<details>`` element so it
    starts collapsed and expands on click. A docstring with no ``Args:`` block
    is returned as escaped text, so this is safe to call on anything.

    Args:
        doc: The library item's docstring, possibly empty.

    Returns:
        str: HTML, or ``""`` for an empty docstring.
    """
    if not doc:
        return ""
    lines = doc.splitlines()
    hdr = next((i for i, l in enumerate(lines) if _ARGS_HEADER.match(l)), None)
    if hdr is None:
        return _html.escape(doc).replace("\n", "<br>")
    # end of the Args block: first blank line or next section header
    end = len(lines)
    for j in range(hdr + 1, len(lines)):
        if lines[j].strip() == "" or _NEXT_SECTION.match(lines[j]):
            end = j
            break
    args = parse_arg_docs(doc)
    items = "".join(
        f"<div style='margin-left:1em'>{_html.escape(k)}: {_html.escape(v)}</div>"
        for k, v in args.items()
    )
    tree = f"<details><summary><b>Args:</b></summary>{items}</details>"
    pre = "<br>".join(_html.escape(l) for l in lines[:hdr])
    post = "<br>".join(_html.escape(l) for l in lines[end:])
    return "".join(p for p in (pre, tree, post) if p)
