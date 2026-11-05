"""Fake ``gclib`` modules in the 1.0 (``gclib.py``) and 2.0 (``gclib.Controller``)
shapes, both recording onto one ``Wire`` so the two can be compared call for call.

``Wire.calls`` holds what reached the "controller": ``("open", ip)``,
``("command", cmd)``, ``("program", text_without_trailing_nul)``, ``("close",)``.
"""

import sys
import types


class Wire:
    def __init__(self, responses=None, fail_on=()):
        self.calls = []
        self.responses = dict(responses or {})
        self.fail_on = set(fail_on)
        self.raw_programs = []  # exactly what the wrapper received
        self.gcaps = None  # last force_gcaps() argument (2.0 only)
        self.open_error = False  # make open/Controller() fail

    def reply(self, cmd):
        r = self.responses.get(cmd, "0")
        return r.pop(0) if isinstance(r, list) else r


def gclib_v1(wire):
    m = types.ModuleType("gclib")

    class GclibError(Exception):
        pass

    class py:
        def GVersion(self):
            return "1.0.1"

        def GOpen(self, s):
            if wire.open_error:
                raise GclibError("open failed")
            wire.calls.append(("open", s.split()[0]))

        def GInfo(self):
            return "10.0.0.5, DMC4183 Rev 1.3a, 12345"

        def GCommand(self, cmd):
            wire.calls.append(("command", cmd))
            if cmd in wire.fail_on:
                raise GclibError("question mark")
            return wire.reply(cmd)

        def GProgramDownload(self, program, preprocessor=""):
            wire.raw_programs.append(program)
            wire.calls.append(("program", program.removesuffix("\x00")))

        def GClose(self):
            wire.calls.append(("close",))

    m.GclibError = GclibError
    m.py = py
    return m


def gclib_v2(wire):
    m = types.ModuleType("gclib")

    class Error(Exception):
        pass

    class Controller:
        def __init__(self, address):
            if wire.open_error:
                raise Error("open failed")
            wire.calls.append(("open", address))
            self._address = address

        def address(self):
            return self._address

        def revision_information(self):
            return "DMC4183 Rev 1.3a"

        def serial_number(self):
            return 12345

        def command(self, cmd):
            wire.calls.append(("command", cmd))
            if cmd in wire.fail_on:
                raise Error("question mark")
            return wire.reply(cmd)

        def set_program(self, program, insert=""):
            wire.raw_programs.append(program)
            wire.calls.append(("program", program))

        def close(self):
            wire.calls.append(("close",))

    def force_gcaps(on):
        wire.gcaps = on

    m.Error = Error
    m.Controller = Controller
    m.version = lambda: "2.5.0"
    m.force_gcaps = force_gcaps
    return m


def install(monkeypatch, api, wire):
    """Put the fake for ``api`` ("1" or "2") at ``sys.modules['gclib']``."""
    mod = gclib_v1(wire) if api == "1" else gclib_v2(wire)
    monkeypatch.setitem(sys.modules, "gclib", mod)
    return mod
