"""Control-surface port (P7g; Amendment §4.3, §6 gate item 4).

One seam over **both** halves of the engineering control panel: the digital
outputs (``helao/core/servers/io_control.py``, 2 routes) and the motion axes
(``helao/core/servers/motion_control.py``, 3 routes). Five methods, one port,
because the two shared modules were deliberately written to the same shape --
their discovery functions were aligned (``discover_do_items(config, groups)``
/ ``discover_axes(config, axis_source)``) so that a single port could wrap
them rather than two ports wrapping one panel.

Three contract clauses, all carried from the modules this mirrors:

* **Unknown is a third value, never ``False`` and never ``0.0``.** A line that
  was not read is ``None``; a coordinate that was not read is ``None``. On a
  panel whose whole job is telling an engineer what the instrument is doing,
  rendering an unread line as off -- or an unread axis as its origin -- is a
  confident lie. ``None`` therefore survives every hop through this seam and
  is never normalized away.
* **The value is dispatched exactly as typed.** :meth:`move_axis` converts
  nothing: the unit rides alongside as a discriminator and the conversion (or
  its deliberate absence) happens in the driver, where the encoder lives.
* **Fidelity is declared, not assumed.** :meth:`read_digital_outs` and
  :meth:`read_axis_positions` are *measured* reads -- they ask the controller
  -- while what a panel holds between reads is a mirror of what it commanded.
  The two are not interchangeable, which is why there is no "cached read"
  method here: a caller that wants the last known state holds it itself.

**No error body is ever parsed.** The adapter delegates to the shared
wrappers, which discard the payload on a non-``none`` error code. Without
that, a 404 from a server with no such endpoint replies ``{"detail": "Not
Found"}`` and a naive parse renders a phantom control named "detail" reading
ON -- measured, not hypothetical.

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82). That excludes
``helao.core.error``, so no ``ErrorCodes`` member appears below: the two
command methods return a bare ``tuple`` -- ``(error_code, payload)`` at every
call site, so unpacking is part of the contract while the code's *type* stays
the legacy layer's business. It equally excludes
``helao.core.servers.motion_control``, so ``units`` and ``mode`` are ``object``
rather than that module's enums, and ``units`` carries **no default**: a
defaulted unit would have to be a bare string invented here, and ``"counts"``
mistaken for ``"mm"`` executes a 10 000-*count* move as 10 000 *millimetres*.
The caller states the unit. Both an enum member and its ``.value`` string are
accepted and produce an identical wire call (pinned in
``test_control_surface_port.py``).

The concrete face lives in ``adapters/vis/control_surface.py`` -- not under
``adapters/native/``, which may not import ``helao.core.servers.*``
(test_boundaries.py:131-143) and is exactly where the wrappers live.
"""

from typing import Optional, Protocol, runtime_checkable

__all__ = ["CONTROL_ROUTES", "ControlSurfacePort"]

#: The five private routes this port covers, in the order the panels use them,
#: mapped to the port method that issues each. Pinned here so a face can be
#: checked against the vocabulary rather than against a string literal at each
#: call site -- and so the row-15 negative harness can enumerate "every
#: control route" from one place instead of from a hand-kept list.
#:
#: All five are **bare-path** ``tags=["private"]`` routes on their action
#: servers, never ``/{server_key}/...``: that prefix is the action namespace,
#: and a panel toggle that entered it would put a row in the run record for
#: every click and queue behind whatever the orchestrator is running. That is
#: the whole substance of artifact row 15 -- a control that drives hardware and
#: writes nothing.
CONTROL_ROUTES: dict[str, str] = {
    "get_digital_outs": "read_digital_outs",
    "set_digital_out": "set_digital_out",
    "get_axis_positions": "read_axis_positions",
    "move_axis": "move_axis",
    "stop_motion": "stop_motion",
}


@runtime_checkable
class ControlSurfacePort(Protocol):
    async def read_digital_outs(self, server_key: str, host: str, port: int) -> dict:
        """Read every digital output on a server, once.

        Returns:
            dict: ``{do_name: True | False | None}``. **Empty** on a failed
            call -- which leaves every control unknown rather than inventing
            states, and is not the same as a server that answered with no
            lines configured.
        """
        ...

    async def set_digital_out(
        self, server_key: str, host: str, port: int, do_name: str, on: bool
    ) -> dict:
        """Drive one digital output and return the server's post-write readback.

        Returns:
            dict: ``{do_name: True | False | None}``. Empty when the call
            failed: the write may or may not have landed, and guessing either
            way would misreport the instrument.
        """
        ...

    async def read_axis_positions(self, server_key: str, host: str, port: int) -> dict:
        """Read every axis's coordinate on a server, once, in both units.

        Returns:
            dict: ``{axis: {"mm": float|None, "counts": int|None,
            "moving": bool|None}}``. Both units come from one sample, so the
            two halves always describe the same instant. Empty on a failed
            call.
        """
        ...

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
        """Command one axis; report how the server answered.

        ``value`` is dispatched **exactly as typed** in ``units``. ``mode`` and
        ``speed`` are omitted from the wire call when ``None``, so the server
        keeps its configured defaults rather than being told this layer's
        guess at them.

        Returns:
            tuple: ``(error_code, payload)``. The code is returned rather than
            swallowed because *refused* (a sequence is running) and *failed*
            are different outcomes a panel must show differently.
        """
        ...

    async def stop_motion(self, server_key: str, host: str, port: int) -> tuple:
        """Halt every axis on a server, leaving the motors energized.

        Not an estop, deliberately: an estop de-energizes, and a de-energized
        vertical axis drops under gravity. Unconditional -- a stage heading
        somewhere it should not go must not wait on the orchestrator.

        Returns:
            tuple: ``(error_code, payload)``, the payload typically
            ``{"stopped": [axis, ...]}``.
        """
        ...
