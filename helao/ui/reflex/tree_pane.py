"""The attribute-tree pane shared by /operator and /group."""

import reflex as rx


def tree_pane(header_var, html_var):
    """The attribute tree beside a set of tables.

    Mirrors the Bokeh operator's header Div plus tree Div. The HTML is nested
    ``<details>``, so expanding a node needs no round trip.
    """
    return rx.vstack(
        rx.text(header_var, weight="bold", size="1"),
        rx.scroll_area(
            rx.html(html_var),
            type="auto",
            scrollbars="vertical",
            height="14em",
        ),
        width="100%",
        spacing="1",
        font_size="0.8em",
    )
