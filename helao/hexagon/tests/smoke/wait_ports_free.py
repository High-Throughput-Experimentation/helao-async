"""Poll until the given TCP ports (and their RPC siblings, port+10000) are FREE.

Pre-launch guard for the ``*_canary.bat`` / ``*_diff.bat`` station smoke
scripts. Before launching a server group onto a fixed port, refuse to proceed
while a stale binder -- a leftover server or ZMQ RPC listener from a previous
leg or a prior canary/diff run -- still owns the HTTP port or its co-located
RPC port (HTTP + 10000, see ``helao.core.rpc.derive_rpc_port``).

Why this matters: if the RPC port is still held, the freshly launched server
cannot bind it and falls back to the ``0.0.0.0`` wildcard, while the STALE
binder keeps ``127.0.0.1:<rpc>``. The capture's RPC-first action dispatch then
reaches the stale binder -- the call is ACK'd but the action never runs on the
live server -- so nothing is written and the capture hangs (``settle`` waits
out its full timeout for an ``-act.yml`` that never appears). The ``:kill_one``
teardown already waits for release AFTER a leg; this guard closes the gap
BEFORE a leg, where a binder left by the *previous* script/leg would otherwise
go uncaught.

For each HTTP port given, both ``<port>`` and ``<port> + 10000`` are checked.
Exits 0 once all are free; exits 2 if any is still bound after ``--timeout``
seconds, naming the stuck port(s) so the operator can kill the holder
(``netstat -ano | findstr <port>``).

Usage: ``python wait_ports_free.py <http_port> [<http_port> ...]``
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

RPC_OFFSET = 10000


def _bound(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """True if a TCP connect to ``host:port`` succeeds (something is listening)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def wait_ports_free(
    http_ports: list[int],
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    poll: float = 1.0,
    _sleep=time.sleep,
    _clock=time.monotonic,
) -> list[int]:
    """Poll until every ``port`` and ``port + RPC_OFFSET`` is free.

    Returns the list of ports STILL BOUND when the timeout elapsed (empty list
    means all released). ``_sleep`` / ``_clock`` are injectable for testing.
    """
    targets: list[int] = []
    for p in http_ports:
        targets.append(p)
        rpc = p + RPC_OFFSET
        # real HELAO HTTP ports are ~8xxx so the RPC sibling is ~18xxx (in range);
        # only add the sibling when it is a valid TCP port so a stray argument can
        # never crash the guard.
        if rpc <= 65535:
            targets.append(rpc)
    t0 = _clock()
    while True:
        stuck = [p for p in targets if _bound(p, host)]
        if not stuck:
            return []
        if _clock() - t0 >= timeout:
            return stuck
        _sleep(poll)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wait_ports_free.py", description=__doc__)
    ap.add_argument(
        "ports",
        nargs="+",
        type=int,
        help="HTTP port(s); the RPC sibling port+10000 is also checked",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--poll", type=float, default=1.0)
    a = ap.parse_args(argv)

    all_targets = [p for port in a.ports for p in (port, port + RPC_OFFSET)]
    stuck = wait_ports_free(a.ports, host=a.host, timeout=a.timeout, poll=a.poll)
    if not stuck:
        print(f"[wait_ports_free] ports free: {all_targets}")
        return 0
    print(
        f"[wait_ports_free] STILL BOUND after {a.timeout:g}s: {stuck} -- a stale "
        f"server/RPC listener owns these; kill it (netstat -ano | findstr "
        f"{stuck[0]}) and retry",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
