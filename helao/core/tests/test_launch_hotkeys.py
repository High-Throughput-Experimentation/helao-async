"""Tests for the launcher's hotkey reader under a non-interactive stdin.

A scripted or piped launch used to die inside the reader thread with
``termios.error: Inappropriate ioctl for device`` -- a bare traceback, no
message, and the launcher process gone while its servers kept running.

Run:  conda run -n helao python -m pytest helao/core/tests/test_launch_hotkeys.py
"""

import io
import os

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
    handle = open(tmp_path / "stdin", "w")
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
