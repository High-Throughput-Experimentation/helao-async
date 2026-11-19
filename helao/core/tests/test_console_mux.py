"""ConsoleMux must drain child pipes whatever the terminal does."""

import os
import threading
import time
import types

import launch

LINE = b"x" * 99 + b"\n"


class _Stream:
    """Terminal stand-in whose write blocks until ``gate`` is set."""

    def __init__(self, gate=None):
        self.gate = gate
        self.out = []

    def write(self, text):
        if self.gate is not None:
            self.gate.wait()
        self.out.append(text)

    def flush(self):
        pass

    def isatty(self):
        return False

    def text(self):
        return "".join(self.out)


def _child(mux, key):
    r, w = os.pipe()
    mux.register(key, types.SimpleNamespace(stdout=os.fdopen(r, "rb")))
    return os.fdopen(w, "wb")


def _feed(wf, nbytes, done):
    for _ in range(nbytes // len(LINE)):
        wf.write(LINE)
    wf.flush()
    done.set()


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_blocked_terminal_never_stops_pipe_drain():
    gate = threading.Event()
    mux = launch.ConsoleMux(_Stream(gate))
    wf = _child(mux, "A")
    done = threading.Event()
    threading.Thread(
        target=_feed, args=(wf, 3 * 1024 * 1024, done), daemon=True
    ).start()
    try:
        assert done.wait(10), "child blocked writing its pipe: reader stuck on tty"
    finally:
        gate.set()
        wf.close()


def test_one_childs_blocked_write_does_not_delay_another():
    gate = threading.Event()
    mux = launch.ConsoleMux(_Stream(gate))
    a, b = _child(mux, "A"), _child(mux, "B")
    done = threading.Event()
    threading.Thread(target=_feed, args=(a, 3 * 1024 * 1024, done), daemon=True).start()
    done_b = threading.Event()
    threading.Thread(
        target=_feed, args=(b, 2 * 1024 * 1024, done_b), daemon=True
    ).start()
    try:
        assert done.wait(10) and done_b.wait(10)
    finally:
        gate.set()
        a.close()
        b.close()


def test_output_resumes_with_dropped_note_after_unblock():
    gate = threading.Event()
    stream = _Stream(gate)
    mux = launch.ConsoleMux(stream)
    wf = _child(mux, "A")
    done = threading.Event()
    threading.Thread(
        target=_feed, args=(wf, 3 * 1024 * 1024, done), daemon=True
    ).start()
    assert done.wait(10)
    gate.set()
    wf.write(b"tail-marker\n")
    wf.flush()
    assert _wait(lambda: "tail-marker" in stream.text())
    assert "line(s) dropped" in stream.text()
    wf.close()


def test_isolation_holds_output_until_resume():
    stream = _Stream()
    mux = launch.ConsoleMux(stream)
    wf = _child(mux, "A")
    with mux.isolated():
        wf.write(b"held\n")
        wf.flush()
        time.sleep(0.3)
        assert "held" not in stream.text()
    assert _wait(lambda: "held" in stream.text())
    wf.close()


class _StrictStream(_Stream):
    def write(self, text):
        if "→" in text:
            raise UnicodeEncodeError("cp1252", text, 0, 1, "bad")
        super().write(text)


def test_bad_chunk_costs_one_line_and_is_counted():
    stream = _StrictStream()
    mux = launch.ConsoleMux(stream)
    mux._write_out(["a\n", "→\n", "b\n"], 0)
    assert stream.text() == "a\nb\n"
    assert mux._failed_lines == 1 and mux._dropped_lines == 0
    mux._write_out([], 0, 1)
    assert "1 line(s) lost" in stream.text()
    assert "overflowed" not in stream.text()


def test_isolation_mid_batch_returns_remainder_to_buffer():
    class _Isolating(_Stream):
        def write(self, text):
            super().write(text)
            mux._display.clear()

    stream = _Isolating()
    mux = launch.ConsoleMux(stream)
    mux._write_out(["a\n", "b\n", "c\n"], 0)
    assert stream.text() == "a\n"
    assert list(mux._buffer) == ["b\n", "c\n"]
    assert mux._buffered_bytes == 4


def test_drain_waits_for_a_blocked_write_then_returns():
    gate = threading.Event()
    stream = _Stream(gate)
    mux = launch.ConsoleMux(stream)
    wf = _child(mux, "A")
    wf.write(b"last words\n")
    wf.flush()
    time.sleep(0.2)
    threading.Timer(0.3, gate.set).start()
    mux.drain(5.0)
    assert "last words" in stream.text()
    wf.close()


def test_drain_gives_up_on_a_terminal_that_stays_blocked():
    gate = threading.Event()
    mux = launch.ConsoleMux(_Stream(gate))
    wf = _child(mux, "A")
    wf.write(b"stuck\n")
    wf.flush()
    time.sleep(0.2)
    t = threading.Thread(target=mux.drain, args=(0.5,), daemon=True)
    t.start()
    t.join(2.0)
    assert not t.is_alive(), "drain ignored its timeout"
    gate.set()
    wf.close()
