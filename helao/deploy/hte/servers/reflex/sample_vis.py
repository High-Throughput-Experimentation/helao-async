"""Reflex panel for the newest samples on a SAMPLE server.

Reflex port of ``servers/visualizer/sample_vis.py``, and the odd one out: it
renders no chart. It asks the server's ``list_new_samples`` endpoint for the
latest samples of each type and stacks four tables.

Declared as an ``action_vis`` panel because it refreshes when the server is
active, but its data comes from that endpoint rather than from the packets --
so ``pull`` only notices activity, and the fetch is a background event.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "panel_id"]

import reflex as rx

from helao.core.servers.reflex.state import ActionVisState, assign
from helao.deploy.hte.servers.reflex._action import latest_action_uuid
from helao.deploy.hte.servers.reflex._samples import (
    SAMPLE_COLUMNS,
    SAMPLE_TYPES,
    tables_for,
)

WS_PATH = "ws_data"

#: Samples requested per type, matching the Bokeh panel's default.
DEFAULT_MAX_SAMPLES = 10


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel. Kept for contract parity: this
    panel draws no chart and so claims no buffer."""
    return f"samples-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """Four sample tables and the action that last prompted a refresh."""

    solid_rows: list[list[str]] = []
    liquid_rows: list[list[str]] = []
    gas_rows: list[list[str]] = []
    assembly_rows: list[list[str]] = []
    max_samples: int = DEFAULT_MAX_SAMPLES
    give_only: bool = False
    action_uuid: str = ""
    status: str = ""

    def panel_key(self) -> str:
        """Session-scoped key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Notice which action is running.

        The tables come from `refresh`, not from the packets: this panel reads
        the server's sample registry, which the data stream does not carry.

        Written only on change. This panel's body is four ``rx.data_table``s,
        which rebuild on any state delta -- so an unconditional write here made
        them rebuild at the render cadence forever, bouncing every panel below
        them as the tables changed height.
        """
        assign(self, "action_uuid", latest_action_uuid(ingest))

    @rx.event
    def set_max_samples(self, value: str):
        """Set how many samples per type to request."""
        try:
            self.max_samples = max(1, int(value))
        except (TypeError, ValueError):
            # Leave the previous value rather than blanking the tables on a
            # half-typed number.
            return

    @rx.event
    def toggle_give_only(self, value: bool):
        """Filter to samples this server gave rather than inherited."""
        self.give_only = value

    @rx.event(background=True)
    async def refresh(self):
        """Fetch the newest samples of every type."""
        async with self:
            server_key = self.server_key
            params = {
                "num_smps": self.max_samples,
                "give_only": "true" if self.give_only else "false",
            }
        from helao.core.error import ErrorCodes
        from helao.helpers.config_loader import CONFIG
        from helao.helpers.dispatcher import async_private_dispatcher

        server = ((CONFIG or {}).get("servers") or {}).get(server_key) or {}
        host, port = server.get("host"), server.get("port")
        if not host or not port:
            async with self:
                self.status = f"no host configured for {server_key}"
            return
        try:
            response, error = await async_private_dispatcher(
                server_key, host, port, "list_new_samples", params, {}
            )
        except Exception as exc:
            async with self:
                self.status = f"sample list unavailable: {exc}"
            return
        if error != ErrorCodes.none:
            async with self:
                self.status = f"sample list failed: {error}"
            return
        tables = tables_for(response)
        async with self:
            self.solid_rows = tables["solid"]
            self.liquid_rows = tables["liquid"]
            self.gas_rows = tables["gas"]
            self.assembly_rows = tables["assembly"]
            self.status = ""


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    columns = list(SAMPLE_COLUMNS)

    def table(label, rows):
        return rx.vstack(
            rx.text(f"Newest {label} samples:", size="2", weight="medium"),
            rx.data_table(
                data=rows,
                columns=columns,
                pagination=False,
                search=False,
                sort=False,
            ),
            width="100%",
            spacing="1",
        )

    rows_by_type = {
        "solid": state_cls.solid_rows,
        "liquid": state_cls.liquid_rows,
        "gas": state_cls.gas_rows,
        "assembly": state_cls.assembly_rows,
    }
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Samples: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=state_cls.max_samples.to_string(),
                    on_blur=state_cls.set_max_samples,
                    placeholder="latest N",
                    width="8em",
                ),
                rx.checkbox(
                    "given only",
                    checked=state_cls.give_only,
                    on_change=state_cls.toggle_give_only,
                ),
                rx.button("Refresh", size="1", on_click=state_cls.refresh),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.status != "",
                rx.text(state_cls.status, size="2", class_name="text-amber-700"),
            ),
            *[table(name, rows_by_type[name]) for name in SAMPLE_TYPES],
            width="100%",
            spacing="3",
            on_mount=[state_cls.render_loop, state_cls.refresh],
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
