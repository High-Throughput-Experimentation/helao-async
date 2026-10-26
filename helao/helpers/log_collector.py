"""Launcher-side log collector: one PULL socket, one unified JSONL file (spec §2)."""

import sys
import threading
import time

import zmq

from helao.helpers.log_jsonl import (
    HWM,
    LEDGER_FRAME,
    ROTATE_RECORDS,
    SOCK_BUF,
    RotatingJsonlWriter,
)

__all__ = ["LogCollector", "log_endpoint", "resolve_log_port"]

# mirrors helao.core.rpc.zmq_rpc.RPC_PORT_OFFSET (importing it would start make_logger sinks)
RPC_PORT_OFFSET = 10000


def log_endpoint(port: int) -> str:
    return f"tcp://127.0.0.1:{port}"


def resolve_log_port(config: dict) -> int:
    """``log_port`` from the config, else one above every port a server occupies.

    The port must be in 1..65535 and clear of every server's address and of the
    RPC port paired with each server port and of any plate-aligner port.
    """
    from helao.hexagon.preflight import _aligner_port
    from helao.ui.shared.discovery import reserved_addresses

    taken, http = set(), set()
    for entry in (config.get("servers") or {}).values():
        if not isinstance(entry, dict):
            continue
        ports = {int(addr.rsplit(":", 1)[1]) for addr in reserved_addresses(entry)}
        http |= ports
        taken |= ports
        # unsure which group kinds bind an RPC port: reserve it for every int port
        if isinstance(entry.get("port"), int):
            taken.add(entry["port"] + RPC_PORT_OFFSET)
        # the aligner's Bokeh port is in no config key unless bokeh_port is set;
        # preflight owns the rule (params.bokeh_port, else port + 1000)
        aligner = _aligner_port(entry)
        if aligner is not None:
            taken.add(aligner)
    port = config.get("log_port")
    if port is None:
        port = max(http, default=8000) + 1
        while port in taken:
            port += 1
        if port > 65535:
            raise ValueError(f"no free log_port below 65536 (taken: {sorted(taken)})")
        return port
    if (
        not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or port in taken
    ):
        raise ValueError(
            f"log_port {port!r} must be an int in 1..65535 that no server "
            f"or server RPC port occupies (taken: {sorted(taken)})"
        )
    return port


class LogCollector:
    """Daemon thread that appends every child's records to one file.

    Never raises into another thread; a disk error is reported to stderr and
    the record dropped. Children whose sends fail spill to their own files.
    """

    def __init__(
        self,
        endpoint: str,
        log_dir,
        prefix: str,
        *,
        rotate_records: int = ROTATE_RECORDS,
    ):
        self.endpoint = endpoint
        self._log = RotatingJsonlWriter(
            log_dir, f"helao_{prefix}", rotate_records=rotate_records
        )
        self._ledger = RotatingJsonlWriter(
            log_dir,
            f"artifacts_{prefix}",
            rotate_records=rotate_records,
            retain_days=None,
        )
        self._stop = threading.Event()
        self._drain_s = 2.0
        self._sock = None
        self._thread = None

    def start(self) -> None:
        self._stop.clear()
        sock = zmq.Context.instance().socket(zmq.PULL)
        sock.setsockopt(zmq.RCVHWM, HWM)
        sock.setsockopt(zmq.RCVBUF, SOCK_BUF)
        sock.setsockopt(zmq.LINGER, 0)
        try:
            sock.bind(self.endpoint)
        except zmq.ZMQError:
            sock.close()
            raise
        self._sock = sock
        self._thread = threading.Thread(
            target=self._run, name="log_collector", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            poller = zmq.Poller()
            poller.register(self._sock, zmq.POLLIN)
            while not self._stop.is_set():
                if poller.poll(500):
                    self._drain()
            deadline = time.monotonic() + self._drain_s
            while time.monotonic() < deadline and poller.poll(100):
                self._drain()
        finally:
            self._sock.close()
            self._log.close()
            self._ledger.close()

    def _drain(self) -> None:
        """Write up to HWM queued records, so the caller can re-check stop/deadline."""
        for _ in range(HWM):
            try:
                frames = self._sock.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                return
            try:
                self._log.write(frames[-1])
            except Exception as exc:  # a writer bug must not kill the thread
                sys.stderr.write(f"log collector write failed: {exc}\n")
            if len(frames) == 2 and frames[0] == LEDGER_FRAME:
                try:
                    self._ledger.write(frames[1])
                except Exception as exc:
                    sys.stderr.write(f"log collector ledger write failed: {exc}\n")

    def stop(self, drain_s: float = 2.0) -> None:
        """Drain for up to ``drain_s`` seconds, close files, finish gzips."""
        if self._thread is None:
            return
        self._drain_s = drain_s
        self._stop.set()
        self._thread.join(timeout=drain_s + 65)
        self._thread = None
