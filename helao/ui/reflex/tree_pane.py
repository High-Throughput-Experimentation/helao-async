"""The attribute-tree pane shared by /operator and /group."""

import reflex as rx


def tree_pane(header_var, html_var, *, fill=False):
    """The attribute tree beside a set of tables.

    Mirrors the Bokeh operator's header Div plus tree Div. The HTML is nested
    ``<details>``, so expanding a node needs no round trip. ``fill`` lets the
    scroll area take the height its (flex) parent gives it instead of 14em.
    """
    flex, min_height = ("1", "0") if fill else (None, None)
    return rx.vstack(
        rx.text(header_var, weight="bold", size="1"),
        rx.scroll_area(
            rx.html(html_var),
            type="auto",
            scrollbars="vertical",
            height="100%" if fill else "14em",
            flex=flex,
            min_height=min_height,
        ),
        width="100%",
        spacing="1",
        font_size="0.8em",
        flex=flex,
        min_height=min_height,
    )
