"""Tests for the launcher's hotkey reader under a non-interactive stdin.

A scripted or piped launch used to die inside the reader thread with
``termios.error: Inappropriate ioctl for device`` -- a bare traceback, no
message, and the launcher process gone while its servers kept running.

Run:  conda run -n helao python -m pytest helao/core/tests/test_launch_hotkeys.py
"""

import io
import os
import subprocess

import pytest

import launch


class _NotATTY(io.StringIO):
    def isatty(self):
        return False


class _ATTY(io.StringIO):
    def isatty(self):
        return True


def test_a_piped_stdin_is_not_interactive(monkeypatch):
    monkeypatch.setattr(launch.sys, "stdin", _NotATTY())
    assert launch.stdin_is_interactive() is False


def test_a_terminal_stdin_is_interactive(monkeypatch):
    monkeypatch.setattr(launch.sys, "stdin", _ATTY())
    assert launch.stdin_is_interactive() is True


def test_a_missing_stdin_is_not_interactive(monkeypatch):
    """pythonw and some service managers leave stdin as None."""
    monkeypatch.setattr(launch.sys, "stdin", None)
    assert launch.stdin_is_interactive() is False


def test_a_closed_stdin_is_not_interactive(monkeypatch, tmp_path):
    """A real closed file raises ValueError from isatty(). Not a StringIO
    subclass: overriding isatty() would defeat the very check being tested."""
    handle = open(tmp_path / "stdin", "w", encoding="utf-8")
    handle.close()
    monkeypatch.setattr(launch.sys, "stdin", handle)
    assert launch.stdin_is_interactive() is False


def test_wait_key_on_a_non_tty_returns_the_disconnect_character(monkeypatch):
    """Not the CTRL-x character: the caller shuts the whole group down on
    '\\x18', and nobody being at a terminal must not tear down a running
    instrument."""
    monkeypatch.setattr(launch.sys, "stdin", _NotATTY())
    key = launch.wait_key()
    assert key == ("\x1a" if os.name == "nt" else "\x04")
    assert key != "\x18"


def test_wait_key_on_a_non_tty_never_touches_the_terminal(monkeypatch):
    """The guard is a check, not a rescued exception: reaching tcgetattr at
    all is what raised in the first place."""
    monkeypatch.setattr(launch.sys, "stdin", _NotATTY())

    def _boom():
        raise AssertionError("the terminal reader must not run without a tty")

    monkeypatch.setattr(launch, "_posix_getchar", _boom)
    assert launch.wait_key() == ("\x1a" if os.name == "nt" else "\x04")


def test_wait_key_survives_a_reader_that_raises(monkeypatch):
    """stdin can be redirected between the check and the read. Uncaught, this
    killed the reader thread."""
    monkeypatch.setattr(launch.sys, "stdin", _ATTY())

    def _boom():
        raise OSError("Inappropriate ioctl for device")

    monkeypatch.setattr(launch, "_posix_getchar", _boom)
    if os.name != "nt":
        assert launch.wait_key() == "\x04"


def test_wait_key_still_reports_a_real_keypress(monkeypatch):
    monkeypatch.setattr(launch.sys, "stdin", _ATTY())
    monkeypatch.setattr(launch, "_posix_getchar", lambda: "\x18")
    if os.name != "nt":
        assert launch.wait_key() == "\x18"


def test_wait_key_still_reports_an_interrupt(monkeypatch):
    monkeypatch.setattr(launch.sys, "stdin", _ATTY())

    def _interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(launch, "_posix_getchar", _interrupt)
    if os.name != "nt":
        assert launch.wait_key() == "\x03"


def test_spawn_kwargs_always_gives_servers_no_stdin(monkeypatch):
    """A shared console's input mode must not be reachable from a server."""
    mux = launch.ConsoleMux()
    assert mux.spawn_kwargs()["stdin"] is subprocess.DEVNULL
    mux.activate()
    kwargs = mux.spawn_kwargs()
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE


def _keys(monkeypatch, keys):
    it = iter(keys)
    monkeypatch.setattr(launch, "wait_key", lambda: next(it))


@pytest.mark.parametrize(
    "keys, expected",
    [
        (["1", "2", "\r"], "12"),
        (["1", "\x08", "3", "\r"], "3"),
        (["1", "\x7f", "\x7f", "3", "\r"], "3"),
        (["1", "\x1b"], ""),
        (["1", "\x1a"], ""),
        (["1", "\x03"], ""),
        (["1", "\x04"], ""),
        (["R", "\n"], "R"),
        (["1", "\x01", "2", "\r"], "12"),
        (["1", "\xe0H", "2", "\r"], "12"),
        (["\x00;", "\r"], ""),
    ],
)
def test_read_menu_line_returns(monkeypatch, capsys, keys, expected):
    _keys(monkeypatch, keys)
    assert launch.read_menu_line("> ") == expected
    assert capsys.readouterr().out.startswith("> ")


def test_read_menu_line_echoes_and_erases(monkeypatch, capsys):
    _keys(monkeypatch, ["1", "2", "\x08", "\r"])
    launch.read_menu_line("> ")
    assert capsys.readouterr().out == "> 12\b \b\n"


def test_read_menu_line_backspace_on_empty_writes_nothing(monkeypatch, capsys):
    _keys(monkeypatch, ["\x08", "\r"])
    launch.read_menu_line("> ")
    assert capsys.readouterr().out == "> \n"


class _FakeK32:
    def __init__(self, mode):
        self.mode = mode
        self.set_calls = []

    def GetStdHandle(self, n):
        return 7

    def GetConsoleMode(self, handle, ref):
        ref._obj.value = self.mode
        return 1

    def SetConsoleMode(self, handle, mode):
        self.set_calls.append(mode)
        return 1


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)

    def debug(self, msg):
        pass


def test_console_mode_check_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(launch.os, "name", "posix")
    monkeypatch.setattr(
        launch, "_kernel32", lambda: pytest.fail("must not touch kernel32")
    )
    launch._check_console_input_mode()


def test_console_mode_check_repairs_a_raw_mode(monkeypatch):
    k32, log = _FakeK32(0x0), _Log()
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch, "_kernel32", lambda: k32)
    monkeypatch.setattr(launch, "LAUNCH_LOGGER", log)
    launch._check_console_input_mode()
    assert k32.set_calls == [0x7]
    assert "0x0" in log.warnings[0]


def test_console_mode_check_leaves_a_normal_mode_alone(monkeypatch):
    k32, log = _FakeK32(0x1F7), _Log()
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch, "_kernel32", lambda: k32)
    monkeypatch.setattr(launch, "LAUNCH_LOGGER", log)
    launch._check_console_input_mode()
    assert k32.set_calls == [] and log.warnings == []


def test_console_mode_check_never_raises(monkeypatch):
    def _boom():
        raise OSError("no console")

    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch, "_kernel32", _boom)
    launch._check_console_input_mode()


def test_console_mode_check_repairs_echo_off_with_line_on(monkeypatch):
    k32, log = _FakeK32(0x1F3), _Log()
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch, "_kernel32", lambda: k32)
    monkeypatch.setattr(launch, "LAUNCH_LOGGER", log)
    launch._check_console_input_mode()
    assert k32.set_calls == [0x1F7]


@pytest.mark.skipif(os.name == "nt", reason="needs a POSIX pty")
def test_menu_keeps_input_that_arrived_before_the_read(monkeypatch, capsys):
    """Typed-ahead or pasted digits must survive the per-key cbreak switch.

    setcbreak's default TCSAFLUSH discarded unread input on every key, so a
    pasted "12" came back as "1" and restarted the wrong server.
    """
    import pty
    import threading

    master, slave = pty.openpty()
    try:
        monkeypatch.setattr(launch.sys, "stdin", os.fdopen(slave, "r", closefd=False))
        os.write(master, b"12R\r")
        got = []
        reader = threading.Thread(
            target=lambda: got.append(launch.read_menu_line("> ")), daemon=True
        )
        reader.start()
        reader.join(5)
        if reader.is_alive():
            os.write(master, b"\x04")  # unblock the leaked read before failing
            pytest.fail("read_menu_line lost the buffered input and blocked")
        assert got == ["12R"]
    finally:
        os.close(master)
        os.close(slave)
