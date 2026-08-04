"""Backend-agnostic logic for the digital-output control panels.

The engineering control panel exists in both UI stacks — a Bokeh document and a
Reflex page — and, as with the data browser and the operator, the behaviour
lives here so the two cannot drift. Nothing in this module imports ``bokeh`` or
``reflex``; it knows only the config and the private endpoints.

Two things are shared:

* **Which lines a station has.** The panel's contents are generated from the
  station config, not hardcoded, so a server gains or loses a control by having
  its ``dev_*`` block edited. The three servers enumerate differently — the
  Galil and Advantech ones have a single ``dev_do`` block, while the NI server
  spreads its outputs across one group per function — which is why
  :func:`discover_do_items` takes the group names from the caller.
* **How a toggle reaches the hardware.** Through the *private*
  ``get_digital_outs`` / ``set_digital_out`` endpoints, never the action twins:
  an action would write a row into the run record for every click and would
  queue behind whatever the orchestrator is running on that server.

**Tri-state, deliberately.** A line is on, off, or *unknown*, and the third is
not a placeholder for "off". The NI server cannot read its outputs back at all
(one-shot tasks, no readback), so a line it has not written since startup is
genuinely unknown and may be energised from a previous run. Rendering that as
off would be a confident lie on a panel whose whole job is to tell an engineer
what the instrument is doing.
"""

__all__ = [
    "UNKNOWN",
    "DoItem",
    "discover_do_items",
    "read_digital_outs",
    "set_digital_out",
    "state_label",
]

from typing import NamedTuple, Optional

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The state of a line that has not been read, or whose readback failed. A
#: distinct value rather than ``False`` — see the module docstring.
UNKNOWN = None

#: Seconds a panel will wait on one call, and how many times it will try.
#:
#: Far below the dispatcher's defaults (60s, 5 retries), and that is the point.
#: These calls run on the Bokeh document's callback, so a server that is down or
#: answering 404 does not merely delay the read — it holds the document while it
#: retries, and the page renders *blank* until it gives up. Measured against a
#: server with no such endpoint: the defaults left the panel empty for minutes,
#: with the only symptom a wall of retry lines in the log. One short attempt
#: fails fast into the honest "could not read" state instead.
#:
#: A toggle is worth one retry because a dropped write is worse than a slow one,
#: but the ceiling stays low for the same reason.
CALL_TIMEOUT = 5
READ_RETRIES = 1
WRITE_RETRIES = 2


class DoItem(NamedTuple):
    """One togglable digital output, as the config declares it.

    Attributes:
        name: The line's config key, and the ``do_name`` the private endpoints
            take.
        group: The ``dev_*`` config block it came from. Shown as a section
            heading, so an NI panel reads as pumps / gas valves / liquid valves
            rather than as one undifferentiated list of names.
    """

    name: str
    group: str


def discover_do_items(server_config: dict, groups) -> list:
    """Enumerate a server's togglable digital outputs from its config.

    Args:
        server_config: The server's entry in the world config (the block with
            ``host``, ``port`` and ``params``).
        groups: ``dev_*`` block names to read, in display order. One entry for
            the Galil and Advantech servers (``dev_do``); nine for the NI one.

    Returns:
        list[DoItem]: Every configured line, in group order then config order.
        Empty when the server declares none, which a panel should render as an
        explicit "no digital outputs configured" rather than as a blank box.
    """
    params = server_config.get("params") or {}
    items = []
    seen = set()
    for group in groups:
        for name in params.get(group) or {}:
            if name in seen:
                # Two groups claiming one name is refused by the server's own
                # set_digital_out, so a second control for it would be a button
                # that cannot work. Skip it and say why.
                LOGGER.error(
                    f"digital output '{name}' appears in more than one group; "
                    f"'{group}' will not get a control"
                )
                continue
            seen.add(name)
            items.append(DoItem(name=name, group=group))
    return items


async def read_digital_outs(server_key: str, host: str, port: int) -> dict:
    """Read every digital output on a server, once.

    Called when a panel is first opened rather than on a timer: these are
    engineering controls, not a data stream, and polling every station's IO
    servers forever to catch a change almost nobody makes is not worth the
    traffic. A panel therefore shows truth at open plus whatever it has
    commanded since.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.

    Returns:
        dict: ``{do_name: True | False | None}``. Empty on a failed call, which
        leaves every control unknown rather than inventing states.
    """
    try:
        response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action="get_digital_outs",
            timeout=CALL_TIMEOUT,
            retries=READ_RETRIES,
        )
    except Exception:
        LOGGER.error(f"'{server_key}' get_digital_outs failed", exc_info=True)
        return {}
    if error_code != ErrorCodes.none:
        # Discard the body, do not parse it. An HTTP error still carries a
        # JSON dict — a 404 from a server without the endpoint replies
        # ``{"detail": "Not Found"}`` — and parsing that yields a phantom
        # control named "detail" reading ON. Measured, not hypothetical.
        LOGGER.error(f"'{server_key}' get_digital_outs -> {error_code}")
        return {}
    return _as_state_dict(response)


async def set_digital_out(
    server_key: str, host: str, port: int, do_name: str, on: bool
) -> dict:
    """Drive one digital output and return the state the server reports back.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.
        do_name: The line to drive.
        on: Requested state.

    Returns:
        dict: ``{do_name: True | False | None}`` from the server's post-write
        readback. Empty when the call failed, which a panel should show as
        unknown — the write may or may not have landed, and guessing either way
        would misreport the instrument.
    """
    try:
        response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action="set_digital_out",
            params_dict={"do_name": do_name, "on": on},
            timeout=CALL_TIMEOUT,
            retries=WRITE_RETRIES,
        )
    except Exception:
        LOGGER.error(f"'{server_key}' set_digital_out({do_name}) failed", exc_info=True)
        return {}
    if error_code != ErrorCodes.none:
        LOGGER.error(f"'{server_key}' set_digital_out({do_name}) -> {error_code}")
        return {}
    return _as_state_dict(response)


def state_label(state: Optional[bool]) -> str:
    """Return the label a control carries for ``state``.

    Shared so the two stacks cannot disagree about what unknown looks like.

    Args:
        state: ``True``, ``False``, or ``None``.

    Returns:
        str: ``"ON"``, ``"OFF"`` or ``"?"``.
    """
    if state is None:
        return "?"
    return "ON" if state else "OFF"


def _as_state_dict(response) -> dict:
    """Normalise a private-endpoint reply to ``{name: bool | None}``.

    The dispatcher hands back whatever the endpoint returned, and the two
    transports it can use do not agree on shape: the RPC fast path preserves the
    ``(error_code, payload)`` tuple, while the HTTP fallback JSON-decodes it to
    a two-element list. Both arrive here, so both are unwrapped.

    Args:
        response: The dispatcher's first return value.

    Returns:
        dict: States keyed by name; empty if nothing dict-shaped was found.
    """
    if isinstance(response, (list, tuple)) and len(response) == 2:
        response = response[1]
    if not isinstance(response, dict):
        return {}
    return {
        name: (None if value is None else bool(value))
        for name, value in response.items()
    }
