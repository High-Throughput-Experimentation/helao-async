"""ZeroMQ + msgspec RPC fast-path for HELAO inter-server calls.

See zmq_rpc.py for the full implementation.  This package is intentionally
small: it exposes ``RPCDispatcher`` (server side) and ``RPCClient`` (client
side), plus the msgspec Struct envelopes used on the wire.
"""

from helao.core.rpc.zmq_rpc import (
    RPCDispatcher,
    RPCClient,
    RPCSyncClient,
    RPCRequest,
    RPCResponse,
    RPCError,
    derive_rpc_port,
)

__all__ = [
    "RPCDispatcher",
    "RPCClient",
    "RPCSyncClient",
    "RPCRequest",
    "RPCResponse",
    "RPCError",
    "derive_rpc_port",
]
