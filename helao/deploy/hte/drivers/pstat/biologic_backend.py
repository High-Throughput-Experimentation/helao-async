"""The contract ``biologic_server`` calls, satisfied by both backends.

There is deliberately **no shared base class**. The two BioLogic drivers have
almost no implementation in common -- one talks to a firmware DLL over TCP,
the other automates a GUI application over files -- so a base would be an
empty shell that invited the wrong things to be hoisted into it. What they
genuinely share is this call surface, and a Protocol states it without
creating a dependency in either direction.

Structural, not nominal: neither driver inherits from this, and pyright checks
the conformance. The module imports nothing from either package, so it costs
nothing to import anywhere.
"""

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["BiologicBackend"]


@runtime_checkable
class BiologicBackend(Protocol):
    """What a BioLogic backend must provide to the action server."""

    ready: bool

    def connect(self) -> Any:
        """Attach to the instrument. Called once at server startup."""

    def get_status(self, channel: Optional[int] = None) -> Any:
        """Channel state, for one channel or all of them."""

    def setup(
        self,
        technique: Any,
        action_params: dict = ...,
        output_dir: Optional[str] = None,
    ) -> Any:
        """Configure a channel for the technique described by ``technique``.

        ``technique`` is backend-specific -- a ``BiologicTechnique`` for the
        eclib backend, an ``OleTechnique`` for the OLE one -- which is why it
        is untyped here. The executor picks the right registry per backend.
        """

    def start_channel(self, channel: int = 0, ttl_params: Optional[dict] = None) -> Any:
        """Start the configured technique on ``channel``."""

    async def get_data(self, channel: int = 0) -> Any:
        """New data since the last call.

        ``message`` must be ``"done"`` exactly when the technique has
        finished; ``BiologicExec._poll`` reads that string to end the action.
        """

    def stop(self, channel: Optional[int] = None) -> Any:
        """Abort one channel, or every running one."""

    def cleanup(self, channel: int) -> Any:
        """Release a channel. Must not disconnect the instrument."""

    def disconnect(self) -> Any:
        """Detach from the instrument."""

    def reset(self) -> Any:
        """Disconnect and reconnect."""

    def shutdown(self) -> None:
        """Stop everything and disconnect. Called by ``BaseAPI`` at exit."""
