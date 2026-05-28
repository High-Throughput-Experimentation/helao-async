"""ZeroMQ + msgspec RPC fast-path for HELAO inter-server calls.

Re-exports the public surface from :mod:`zmq_rpc`: ``RPCDispatcher`` (server
side), ``RPCClient`` / ``RPCSyncClient`` (client side), the on-wire
``RPCRequest`` / ``RPCResponse`` Structs, the ``RPCError`` exception, and the
``derive_rpc_port`` helper that pairs an HTTP port with its RPC port.
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
