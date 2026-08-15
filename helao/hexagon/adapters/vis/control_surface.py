"""The hexagon's control-surface face (P7g).

:class:`ControlSurface` satisfies
:class:`~helao.hexagon.ports.control_surface.ControlSurfacePort` by
**delegating to the shared wrappers** in ``helao/ui/shared/io_control.py``
and ``helao/ui/shared/motion_control.py``. Nothing is reimplemented here,
and that is the whole design: those wrappers carry three behaviours that a
second implementation would silently lose --

* ``CALL_TIMEOUT = 5`` with ``READ_RETRIES = 1`` / ``WRITE_RETRIES = 2``, far
  below the dispatcher's 60 s / 5 retries. These calls run on a UI callback,
  so a server that is down does not merely delay a read -- it holds the page
  *blank* while it retries. Measured against a server with no such endpoint,
  the dispatcher defaults left the panel empty for minutes.
* The error-body discard: on a non-``none`` code the body is dropped
  unparsed, because a 404 still carries ``{"detail": "Not Found"}`` and
  parsing it yields a phantom control named "detail" reading ON.
* The two-transport unwrap: the RPC fast path preserves the
  ``(error_code, payload)`` tuple while the HTTP fallback JSON-decodes it to a
  two-element list, and both arrive at the same coercion.

This module is under ``adapters/vis/``, not ``adapters/native/``: the native
layer may not import ``helao.core.servers.*`` (test_boundaries.py:131-143),
which is precisely where both wrapper modules live.
"""

from typing import Optional

from helao.ui.shared import io_control, motion_control
from helao.hexagon.ports.control_surface import ControlSurfacePort

__all__ = ["ControlSurface"]


class ControlSurface:
    """:class:`ControlSurfacePort` over the two shared control modules.

    Stateless: every method takes the server it addresses, so one instance
    serves every control target on a page. That mirrors how the panels already
    work -- a station's ``/control`` page addresses several action servers, and
    a per-server object would only be a place for a stale host to hide.
    """

    async def read_digital_outs(self, server_key: str, host: str, port: int) -> dict:
        """Delegate to :func:`io_control.read_digital_outs`."""
        return await io_control.read_digital_outs(
            server_key=server_key, host=host, port=port
        )

    async def set_digital_out(
        self, server_key: str, host: str, port: int, do_name: str, on: bool
    ) -> dict:
        """Delegate to :func:`io_control.set_digital_out`."""
        return await io_control.set_digital_out(
            server_key=server_key, host=host, port=port, do_name=do_name, on=on
        )

    async def read_axis_positions(self, server_key: str, host: str, port: int) -> dict:
        """Delegate to :func:`motion_control.read_axis_positions`."""
        return await motion_control.read_axis_positions(
            server_key=server_key, host=host, port=port
        )

    async def move_axis(
        self,
        server_key: str,
        host: str,
        port: int,
        axis: str,
        value: float,
        units: object,
        mode: object = None,
        speed: Optional[int] = None,
    ) -> tuple:
        """Delegate to :func:`motion_control.move_axis`.

        ``units`` and ``mode`` cross the port as ``object`` (a port may not
        import that module's enums) and are handed through untouched. The
        wrapper renders each with ``str(getattr(x, "value", x))``, so an enum
        member and its ``.value`` string produce the same wire call -- pinned
        in ``test_control_surface_port.py`` rather than left to be discovered
        at a station.

        ``value`` is **not** converted, here or in the wrapper: it reaches the
        driver exactly as typed, with ``units`` as its discriminator.
        """
        return await motion_control.move_axis(
            server_key=server_key,
            host=host,
            port=port,
            axis=axis,
            value=value,
            mode=mode,
            units=units,  # type: ignore[arg-type]
            speed=speed,
        )

    async def stop_motion(self, server_key: str, host: str, port: int) -> tuple:
        """Delegate to :func:`motion_control.stop_motion`."""
        return await motion_control.stop_motion(
            server_key=server_key, host=host, port=port
        )


_PORT_CONFORMANCE: ControlSurfacePort = ControlSurface()
