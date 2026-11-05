# Galil gclib 2.0 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Galil I/O and motion servers run on either gclib Python wrapper (1.0 `gclib.py()` or 2.0 `gclib.Controller`), chosen per server by `gclib_api`, with identical action behaviour; docs stop calling Galil Windows-only.

**Architecture:** Both drivers talk to the controller only through the existing `GalilCommandChannel` port, which gains `download_program`. The 1.0 channel (`GclibCommandChannel`) is kept; a new `Gclib2CommandChannel` translates the same port onto `gclib.Controller`. `make_channel(config)` picks the channel from `gclib_api`. The I/O driver moves from raw `self.g.G*` calls onto the port, binding its existing `galilcmd`/`galilprgdownload` aliases to the channel, so every action body stays unchanged.

**Tech Stack:** Python 3.14, pytest + pytest-asyncio, gclib wrapper 1.0.1 / 2.x (vendor; faked in tests).

**Spec:** `docs/superpowers/specs/2026-11-05-galil-gclib2-backend-design.md`

## Global Constraints

- Parent repo is a public remote: never name private deployments in any tracked file or commit message.
- `import gclib` only inside channel methods (`open` and later), never at module scope: modules must import on machines without gclib.
- `gclib_api` absent ⇒ `"1"`; the `"1"` path's controller traffic stays byte-identical to today (same open string, commands, program downloads).
- Accepted `gclib_api` values: `"1"`, `"2"`, and the YAML ints `1`, `2` (normalised to strings); `True`/`False` and anything else raise `ValueError` at driver construction.
- Run everything with `/home/dan/miniforge3/envs/helao/bin/python` and `PYTHONPATH=<repo root>`; format changed `.py` with `black` before each commit; commits end with the session attribution lines.
- Galil fakes go in `helao/deploy/hte/servers/galil_motion/tests/fake_gclib.py` and are reused by the I/O tests (cross-folder import of the owner folder).

## Review Focus

1. `gclib_api: 2` written as a YAML integer — must select the 2.0 channel, not raise (Task 1 test `test_int_api_is_normalised`).
2. Wrong wrapper installed for the configured `gclib_api` — connect must fail with a message naming `gclib_api` and the fix, and the server must not crash (Task 1 `test_wrong_wrapper_*`, Task 3 `test_io_connect_wrong_wrapper_reports_failure`).
3. Controller unreachable under 2.0 (`Controller(...)` raises `gclib.Error`) — mapped to `GalilChannelError`, connect reports failure (Task 1 `test_v2_open_error_maps`).
4. Program download of the I/O digital-cycle DMC under 2.0 — the trailing `"\x00"` must not reach `set_program`, `"DL;"` passes unchanged (Task 1 `test_v2_download_strips_only_trailing_nul`, Task 4 parity).
5. `disconnect()` twice, or before `connect()` — no exception from either channel (Task 1 `test_close_is_idempotent`, Task 3 `test_io_disconnect_before_connect`).

---

### Task 1: Fake gclib modules, 2.0 channel, `download_program`, channel selection

**Files:**
- Create: `helao/deploy/hte/servers/galil_motion/tests/fake_gclib.py`
- Create: `helao/deploy/hte/servers/galil_motion/galil_command_channel2.py`
- Create: `helao/deploy/hte/servers/galil_motion/galil_channels.py`
- Modify: `helao/deploy/hte/servers/galil_motion/galil_command_channel_port.py` (add `download_program` to the Protocol; reword the module docstring's "Windows-only" to "vendor")
- Modify: `helao/deploy/hte/servers/galil_motion/galil_command_channel.py` (wrong-wrapper check in `open`, new `download_program`, docstring wording)
- Test: `helao/deploy/hte/servers/galil_motion/tests/test_galil_channels.py`

**Interfaces:**
- Produces: `GalilCommandChannel.download_program(program: str) -> None`; `Gclib2CommandChannel` (same methods as the port); `galil_channels.CHANNELS: dict[str, type]`, `galil_channels.DEFAULT_GCLIB_API = "1"`, `galil_channels.make_channel(config: dict) -> GalilCommandChannel`; test helpers `fake_gclib.Wire`, `fake_gclib.gclib_v1(wire)`, `fake_gclib.gclib_v2(wire)`, `fake_gclib.install(monkeypatch, api: str, wire) -> module`.

- [ ] **Step 1: Write the fakes**

```python
# helao/deploy/hte/servers/galil_motion/tests/fake_gclib.py
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
```

- [ ] **Step 2: Write the failing channel tests**

```python
# helao/deploy/hte/servers/galil_motion/tests/test_galil_channels.py
import pytest

from helao.deploy.hte.servers.galil_motion.galil_channels import (
    CHANNELS,
    make_channel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel import (
    GclibCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel2 import (
    Gclib2CommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilChannelError,
    GalilCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.tests.fake_gclib import Wire, install

CONN = "10.0.0.5 --direct -s ALL"


@pytest.mark.parametrize("api", ["1", "2"])
def test_same_wire_traffic_for_both_wrappers(monkeypatch, api):
    wire = Wire({"MG _TPA": "1000"})
    install(monkeypatch, api, wire)
    ch = CHANNELS[api]()
    assert isinstance(ch, GalilCommandChannel)
    ch.open(CONN)
    assert ch.command("MG _TPA") == "1000"
    ch.download_program("DL;")
    ch.download_program("#A\nEN\x00")
    ch.close()
    assert wire.calls == [
        ("open", "10.0.0.5"),
        ("command", "MG _TPA"),
        ("program", "DL;"),
        ("program", "#A\nEN"),
        ("close",),
    ]


def test_v1_download_is_passed_through_unchanged(monkeypatch):
    wire = Wire()
    install(monkeypatch, "1", wire)
    ch = GclibCommandChannel()
    ch.open(CONN)
    ch.download_program("#A\nEN\x00")
    assert wire.raw_programs == ["#A\nEN\x00"]


def test_v2_download_strips_only_trailing_nul(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    ch = Gclib2CommandChannel()
    ch.open(CONN)
    ch.download_program("DL;")
    ch.download_program("#A\nEN\x00")
    assert wire.raw_programs == ["DL;", "#A\nEN"]


def test_v2_direct_disables_gcaps(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    Gclib2CommandChannel().open(CONN)
    assert wire.gcaps is False


def test_v2_without_direct_leaves_gcaps(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    Gclib2CommandChannel().open("10.0.0.5")
    assert wire.gcaps is None


@pytest.mark.parametrize("api", ["1", "2"])
def test_info_and_version_shape(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    ch.open(CONN)
    assert ch.info() == "10.0.0.5, DMC4183 Rev 1.3a, 12345"
    assert ch.version() == ("1.0.1" if api == "1" else "2.5.0")


@pytest.mark.parametrize("api", ["1", "2"])
def test_command_error_maps(monkeypatch, api):
    install(monkeypatch, api, Wire(fail_on={"BAD"}))
    ch = CHANNELS[api]()
    ch.open(CONN)
    with pytest.raises(GalilChannelError, match="BAD"):
        ch.command("BAD")


@pytest.mark.parametrize("api", ["1", "2"])
def test_open_error_maps(monkeypatch, api):
    wire = Wire()
    wire.open_error = True
    install(monkeypatch, api, wire)
    with pytest.raises(GalilChannelError):
        CHANNELS[api]().open(CONN)


test_v2_open_error_maps = test_open_error_maps  # Review Focus 3 name


@pytest.mark.parametrize("api", ["1", "2"])
def test_close_is_idempotent(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    ch.close()  # before open
    ch.open(CONN)
    ch.close()
    ch.close()


@pytest.mark.parametrize("api", ["1", "2"])
def test_not_open_raises(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    with pytest.raises(GalilChannelError, match="not open"):
        ch.command("TP")
    with pytest.raises(GalilChannelError, match="not open"):
        ch.download_program("DL;")


def test_wrong_wrapper_for_api_1(monkeypatch):
    install(monkeypatch, "2", Wire())
    with pytest.raises(GalilChannelError, match="gclib_api"):
        GclibCommandChannel().open(CONN)


def test_wrong_wrapper_for_api_2(monkeypatch):
    install(monkeypatch, "1", Wire())
    with pytest.raises(GalilChannelError, match="gclib_api"):
        Gclib2CommandChannel().open(CONN)


def test_default_is_v1():
    assert isinstance(make_channel({}), GclibCommandChannel)


@pytest.mark.parametrize("value", ["2", 2])
def test_int_api_is_normalised(value):
    assert isinstance(make_channel({"gclib_api": value}), Gclib2CommandChannel)


@pytest.mark.parametrize("value", ["3", "", True, None, 2.0])
def test_unknown_api_raises(value):
    with pytest.raises(ValueError, match="gclib_api"):
        make_channel({"gclib_api": value})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests/test_galil_channels.py -q`
Expected: collection ERROR, `ModuleNotFoundError: ...galil_channels`.

- [ ] **Step 4: Add `download_program` to the port**

In `galil_command_channel_port.py`, inside `GalilCommandChannel`, after `command`:

```python
    def download_program(self, program: str) -> None:
        """Download a DMC program (legacy ``g.GProgramDownload(program)``)."""
        ...
```

and change the module docstring's "the Windows-only ``gclib`` runtime" to "the vendor ``gclib`` runtime (Windows or Linux)".

- [ ] **Step 5: Extend the 1.0 channel**

In `galil_command_channel.py`: reword "Windows-only ``gclib`` runtime" to "``gclib`` runtime (wrapper 1.0, ``gclib.py()``; Windows or Linux)" and the inline `# lazy: Windows/at-station only` to `# lazy: vendor package, at-station only`. In `open`, before `g = gclib.py()`:

```python
        if not hasattr(gclib, "py"):
            raise GalilChannelError(
                "gclib_api '1' needs the 1.0 wrapper (gclib.py); the installed "
                "gclib has Controller (wrapper 2.x) - set gclib_api: '2' or "
                "install wrapper 1.0.1"
            )
```

Add after `command`:

```python
    def download_program(self, program: str) -> None:
        if self._g is None:
            raise GalilChannelError("channel not open")
        import gclib

        try:
            self._g.GProgramDownload(program)
        except gclib.GclibError as exc:
            raise GalilChannelError(f"program download failed: {exc}") from exc
```

- [ ] **Step 6: Write the 2.0 channel**

```python
# helao/deploy/hte/servers/galil_motion/galil_command_channel2.py
"""gclib 2.x (``gclib.Controller``) implementation of the Galil command-channel port.

Same port as :mod:`galil_command_channel` (wrapper 1.0), so the motion and I/O
drivers run unchanged on either wrapper. Selected by ``gclib_api: "2"``.
``import gclib`` is lazy (inside ``open``); the module imports without gclib.
Windows or Linux, Python >= 3.12.
"""

from typing import Any, Optional

from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilChannelError,
)

__all__ = ["Gclib2CommandChannel"]


class Gclib2CommandChannel:
    """`GalilCommandChannel` backed by ``gclib.Controller`` (wrapper 2.x)."""

    def __init__(self) -> None:
        self._c: Optional[Any] = None
        self._gclib: Optional[Any] = None

    def open(self, connection_string: str) -> None:
        import gclib  # lazy: vendor package, at-station only

        if not hasattr(gclib, "Controller"):
            raise GalilChannelError(
                "gclib_api '2' needs the 2.x wrapper (gclib.Controller); the "
                "installed gclib is wrapper 1.0 (gclib.py) - set gclib_api: '1' "
                "or install wrapper 2.x"
            )
        parts = connection_string.split()
        if not parts:
            raise GalilChannelError("empty connection string")
        try:
            # 1.0's "--direct" bypassed gcaps; 2.x does that process-wide.
            if "--direct" in parts[1:]:
                gclib.force_gcaps(False)
            self._c = gclib.Controller(parts[0])
            self._gclib = gclib
        except gclib.Error as exc:
            raise GalilChannelError(str(exc)) from exc

    def _open_controller(self) -> Any:
        if self._c is None:
            raise GalilChannelError("channel not open")
        return self._c

    def command(self, cmd: str) -> str:
        c = self._open_controller()
        try:
            return c.command(cmd)
        except self._gclib.Error as exc:
            raise GalilChannelError(f"command {cmd!r} failed: {exc}") from exc

    def download_program(self, program: str) -> None:
        c = self._open_controller()
        try:
            # 1.0 callers append a NUL terminator; set_program takes plain text.
            c.set_program(program.removesuffix("\x00"))
        except self._gclib.Error as exc:
            raise GalilChannelError(f"program download failed: {exc}") from exc

    def info(self) -> str:
        c = self._open_controller()
        # the 1.0 GInfo() shape: "<address>, <revision>, <serial>"
        return f"{c.address()}, {c.revision_information()}, {c.serial_number()}"

    def version(self) -> str:
        self._open_controller()
        return self._gclib.version()

    def close(self) -> None:
        if self._c is None:
            return
        try:
            self._c.close()
        except self._gclib.Error:
            pass
        finally:
            self._c = None
```

- [ ] **Step 7: Write the selector**

```python
# helao/deploy/hte/servers/galil_motion/galil_channels.py
"""``gclib_api`` server param -> Galil command channel (wrapper 1.0 or 2.x).

Both wrappers install as ``import gclib``, so one env holds one of them; the
configured value must match the installed wrapper (the channel's ``open``
says so if it does not). Absent -> "1", today's behaviour.
"""

from helao.deploy.hte.servers.galil_motion.galil_command_channel import (
    GclibCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel2 import (
    Gclib2CommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilCommandChannel,
)

__all__ = ["CHANNELS", "DEFAULT_GCLIB_API", "make_channel"]

CHANNELS = {"1": GclibCommandChannel, "2": Gclib2CommandChannel}
DEFAULT_GCLIB_API = "1"


def make_channel(config: dict) -> GalilCommandChannel:
    raw = config.get("gclib_api", DEFAULT_GCLIB_API)
    name = str(raw) if type(raw) is int else raw
    if name not in CHANNELS:
        raise ValueError(
            f"unknown gclib_api {raw!r}; expected one of "
            + ", ".join(repr(k) for k in CHANNELS)
        )
    return CHANNELS[name]()
```

(`type(raw) is int` keeps `True`/`False` out; the server named in the error comes from the launcher's log line for the failing server — drivers do not know their server key.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests -q`
Expected: all PASS (new file plus the existing native/aligner/counts tests unchanged).

- [ ] **Step 9: Commit**

```bash
black helao/deploy/hte/servers/galil_motion
git add helao/deploy/hte/servers/galil_motion
git commit -m "feat(galil): gclib 2.x command channel and gclib_api selection"
```

---

### Task 2: Motion driver picks its channel from `gclib_api`

**Files:**
- Modify: `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:93-100` (default channel)
- Test: `helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py` (append)

**Interfaces:**
- Consumes: `make_channel(config) -> GalilCommandChannel` (Task 1).
- Produces: `NativeGalilMotion(config)` with no `channel=` uses `make_channel(config)`; unknown `gclib_api` raises `ValueError` at construction.

- [ ] **Step 1: Write the failing tests** (append)

```python
from helao.deploy.hte.servers.galil_motion.galil_command_channel import (
    GclibCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel2 import (
    Gclib2CommandChannel,
)


def test_default_channel_is_wrapper_1():
    drv = NativeGalilMotion({"axis_id": {"x": "A"}})
    assert isinstance(drv._channel, GclibCommandChannel)


def test_gclib_api_2_selects_wrapper_2():
    drv = NativeGalilMotion({"axis_id": {"x": "A"}, "gclib_api": "2"})
    assert isinstance(drv._channel, Gclib2CommandChannel)


def test_unknown_gclib_api_fails_construction():
    with pytest.raises(ValueError, match="gclib_api"):
        NativeGalilMotion({"axis_id": {"x": "A"}, "gclib_api": "9"})
```

(Use the module's existing `NativeGalilMotion`/`pytest` imports; add only what is missing.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py -q -k "gclib_api or default_channel"`
Expected: `test_gclib_api_2_selects_wrapper_2` and `test_unknown_gclib_api_fails_construction` FAIL.

- [ ] **Step 3: Implement**

Replace the default-channel block in `NativeGalilMotion.__init__`:

```python
        if channel is None:
            # production default: the gclib channel named by `gclib_api`
            # (lazy gclib import, so this still constructs without gclib).
            from helao.deploy.hte.servers.galil_motion.galil_channels import (
                make_channel,
            )

            channel = make_channel(self.config_dict)
```

Also reword the class/module comments that say gclib is Windows-only (line ~94: "imports/constructs on Linux without gclib" stays true — keep; drop any "Windows-only").

- [ ] **Step 4: Run the motion tests**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
black helao/deploy/hte/servers/galil_motion
git add helao/deploy/hte/servers/galil_motion
git commit -m "feat(galil): motion driver selects its gclib channel from gclib_api"
```

---

### Task 3: I/O driver onto the channel port

**Files:**
- Modify: `helao/deploy/hte/servers/galil_io/galil_io_driver.py` (module docstring lines 1-60, `__init__` ~119-122, `connect` ~127-162, `disconnect` ~186-207)
- Test: `helao/deploy/hte/tests/test_galil_io_channel.py`

**Interfaces:**
- Consumes: `make_channel`, `GalilChannelError`, fakes `Wire`/`install` (Task 1).
- Produces: `Galil._channel`; after a successful `connect()`, `galilcmd is _channel.command` and `galilprgdownload is _channel.download_program` (bound methods; compare with `==`).

- [ ] **Step 1: Write the failing tests**

```python
# helao/deploy/hte/tests/test_galil_io_channel.py
import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.servers.galil_io.galil_io_driver import Galil
from helao.deploy.hte.servers.galil_motion.tests.fake_gclib import Wire, install

CFG = {"galil_ip_str": "10.0.0.5", "dev_do": {"do1": 1}}


@pytest.mark.parametrize("api", ["1", "2"])
def test_io_connect_binds_channel(monkeypatch, api):
    wire = Wire()
    install(monkeypatch, api, wire)
    drv = Galil(config={**CFG, "gclib_api": api})
    resp = drv.connect()
    assert resp.response == DriverResponseType.success
    assert drv.galil_enabled is True
    assert drv.galilcmd == drv._channel.command
    assert drv.galilprgdownload == drv._channel.download_program
    assert wire.calls == [("open", "10.0.0.5")]


@pytest.mark.parametrize("api", ["1", "2"])
def test_io_disconnect_closes(monkeypatch, api):
    wire = Wire()
    install(monkeypatch, api, wire)
    drv = Galil(config={**CFG, "gclib_api": api})
    drv.connect()
    assert drv.disconnect().response == DriverResponseType.success
    assert wire.calls[-1] == ("close",)
    assert drv.galil_enabled is False


@pytest.mark.parametrize("api", ["1", "2"])
def test_io_disconnect_before_connect(monkeypatch, api):
    install(monkeypatch, api, Wire())
    drv = Galil(config={**CFG, "gclib_api": api})
    assert drv.disconnect().response == DriverResponseType.success


def test_io_connect_wrong_wrapper_reports_failure(monkeypatch, caplog):
    install(monkeypatch, "1", Wire())
    drv = Galil(config={**CFG, "gclib_api": "2"})
    resp = drv.connect()
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.error
    assert drv.galil_enabled is False


def test_io_no_ip_is_uninitialized(monkeypatch):
    install(monkeypatch, "2", Wire())
    drv = Galil(config={"gclib_api": "2"})
    resp = drv.connect()
    assert resp.status == DriverStatus.uninitialized


def test_io_unknown_api_fails_construction():
    with pytest.raises(ValueError, match="gclib_api"):
        Galil(config={**CFG, "gclib_api": "x"})
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_galil_io_channel.py -q`
Expected: FAIL (`Galil` has no `_channel`; `gclib.py()` path ignores `gclib_api`).

- [ ] **Step 3: Implement**

In `galil_io_driver.py`:
- import at module top: `from helao.deploy.hte.servers.galil_motion.galil_channels import make_channel`
- in `__init__`, replace `self.g = None` with `self._channel = make_channel(self.config_dict)` (keep `self.galilcmd = None`, `self.galilprgdownload = None`).
- replace `connect` body:

```python
        try:
            galil_ip = self.config_dict.get("galil_ip_str", None)
            if galil_ip:
                self._channel.open(f"{galil_ip} --direct -s ALL")
                LOGGER.info(f"gclib version: {self._channel.version()}")
                LOGGER.info(self._channel.info())
                self.galilcmd = self._channel.command
                # downloads a DMC program to galil
                self.galilprgdownload = self._channel.download_program
                self.galil_enabled = True
                response = DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.ok
                )
            else:
                LOGGER.error("no Galil IP configured")
                self.galil_enabled = False
                response = DriverResponse(
                    response=DriverResponseType.failed,
                    status=DriverStatus.uninitialized,
                )
        except Exception:
            LOGGER.error("could not connect to Galil controller", exc_info=True)
            self.galil_enabled = False
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response
```

(The `import gclib` at the top of `connect` is removed; the channel imports it.)
- in `disconnect`, replace `self.g.GClose()` with `self._channel.close()`.
- docstrings: module docstring and `Galil` class docstring — replace "Requires gclib (Windows)" and the `setup.py install` instructions with: "Requires the gclib C library and one of its Python wrappers (Windows or Linux); the server's `gclib_api` param (\"1\" default, or \"2\") must match the installed wrapper — see this folder's README.md." Document `gclib_api` in the class's "Server config parameters" list. Replace "The `gclib.py()` connection" with "The controller connection".
- `rg -n "self\.g\b" helao/deploy/hte` must return nothing afterwards.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_galil_io_channel.py helao/deploy/hte/tests/test_galil_io_digital_cycle.py helao/deploy/hte/tests/test_digital_out_private_endpoints.py helao/deploy/hte/tests/test_driver_disconnected_construct.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
black helao/deploy/hte/servers/galil_io helao/deploy/hte/tests/test_galil_io_channel.py
git add helao/deploy/hte/servers/galil_io helao/deploy/hte/tests/test_galil_io_channel.py
git commit -m "feat(galil): I/O driver talks to the controller through the gclib channel"
```

---

### Task 4: Parity — every driver action, wrapper 1.0 vs 2.0

**Files:**
- Test: `helao/deploy/hte/tests/test_galil_gclib_parity.py`

**Interfaces:**
- Consumes: `Galil` (Task 3), `NativeGalilMotion` (Task 2), fakes (Task 1).

The test runs one scripted session per wrapper and asserts identical controller traffic (`wire.calls`) and identical action results. If a result dict carries a time-varying value (a timestamp), drop that key in `_stable()` and say which key in a comment; nothing else may be dropped.

- [ ] **Step 1: Read the existing motion fixture**

Read `helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py` (how `NativeGalilMotion` is constructed and connected with `FakeChannel`, what `config` keys, `base_hook`, and how `motor_move` gets its `active` object) and `helao/deploy/hte/tests/test_galil_io_digital_cycle.py` (arguments for `set_digital_cycle`). Reuse those exact constructions, replacing `FakeChannel` with `channel=None` plus `install(monkeypatch, api, wire)` and `"gclib_api": api` in the config.

- [ ] **Step 2: Write the parity test**

```python
# helao/deploy/hte/tests/test_galil_gclib_parity.py
"""The same driver calls produce the same controller traffic and results on
gclib wrapper 1.0 and 2.x (the logic is shared; this pins the channel layer)."""

import pytest

from helao.deploy.hte.servers.galil_io.enum import TriggerType
from helao.deploy.hte.servers.galil_io.galil_io_driver import Galil
from helao.deploy.hte.servers.galil_motion.tests.fake_gclib import Wire, install

IO_CFG = {
    "galil_ip_str": "10.0.0.5",
    "dev_ai": {"ai1": 1},
    "dev_ao": {"ao1": 2},
    "dev_di": {"di1": 3, "gamry_ttl0": 4},
    "dev_do": {"do1": 5, "do2": 6},
}
IO_REPLIES = {"MG @AN[1]": " 1.2340", "MG @IN[3]": " 1.0000", "MG @OUT[5]": " 0.0000"}


def _stable(x):
    return x  # add key drops here only for time-varying values, with a comment


async def _io_session(monkeypatch, api):
    wire = Wire(dict(IO_REPLIES))
    install(monkeypatch, api, wire)
    drv = Galil(config={**IO_CFG, "gclib_api": api})
    out = [drv.connect().response]
    out.append(await drv.get_analog_in("ai1"))
    out.append(await drv.get_digital_in("di1"))
    out.append(await drv.get_digital_out("do1"))
    out.append(await drv.set_analog_out(1.5, "ao1"))
    out.append(await drv.set_digital_out(True, "do1"))
    out.append(await drv.set_digital_out(False, "do1"))
    out.append(
        await drv.set_digital_cycle(
            trigger_name="gamry_ttl0",
            triggertype=TriggerType.fallingedge,
            out_name="do1",
            toggle_init_delay=0.0,
            toggle_duty=0.5,
            toggle_period=2.0,
            toggle_duration=10.0,
        )
    )
    out.append(await drv.stop_digital_cycle())
    out.append(await drv.estop(True))
    out.append(drv.disconnect().response)
    return wire, [_stable(o) for o in out]


@pytest.mark.asyncio
async def test_io_parity(monkeypatch):
    w1, r1 = await _io_session(monkeypatch, "1")
    w2, r2 = await _io_session(monkeypatch, "2")
    assert w1.calls == w2.calls
    assert r1 == r2
    assert any(c[0] == "program" for c in w2.calls)  # the cycle downloaded a program
    assert all("\x00" not in p for p in w2.raw_programs)
    assert w2.gcaps is False
```

Then add `_motion_session(monkeypatch, api)` and `test_motion_parity` in the same shape: construct `NativeGalilMotion` exactly as Step 1 found (config with `"gclib_api": api`, no `channel=`), then call, appending each result: `connect()` (`.response`), `query_axis_position(["x", "y"])`, `query_axis_position_counts(["x"])`, `query_axis_moving(["x"])`, `motor_on(["x"])`, `motor_off(["x"])`, `stop_axis(["x"])`, `motor_move(active)` (one absolute move built as in the existing tests), `setaxisref()`, `reset_controller()`, `estop(True)`, `motor_disconnect()`, `disconnect()` (`.response`). Give `Wire` the replies the existing motion tests program for `TP`/`MG _BG`/`MG _MO` so positions are non-zero. Assert `w1.calls == w2.calls` and `r1 == r2`. If any of these calls cannot run against a fake (e.g. it needs a live host or sleeps for seconds), monkeypatch the sleep the way the existing tests do; if still impossible, leave that call out and list it in the task report with the reason.

- [ ] **Step 3: Run**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_galil_gclib_parity.py -q`
Expected: PASS.

- [ ] **Step 4: Prove the test can fail**

Temporarily change `Gclib2CommandChannel.download_program` to pass the program through without `removesuffix`, re-run: `test_io_parity` must FAIL; then temporarily make `Gclib2CommandChannel.command` append a space to `cmd`: both parity tests must FAIL. Revert both and re-run to PASS. Record the results in the report.

- [ ] **Step 5: Commit**

```bash
black helao/deploy/hte/tests/test_galil_gclib_parity.py
git add helao/deploy/hte/tests/test_galil_gclib_parity.py
git commit -m "test(galil): wrapper 1.0 vs 2.x parity for every I/O and motion action"
```

---

### Task 5: Docs — Linux support, install steps, `gclib_api`

**Files:**
- Modify: `CLAUDE.md` (the "Windows-only drivers" bullet, ~line 112)
- Modify: `readme.md` (~line 7)
- Modify: `helao/helpers/win_job.py` (docstring ~line 6)
- Modify: `helao/deploy/hte/servers/galil_io/README.md`, `helao/deploy/hte/servers/galil_motion/README.md`
- Modify: `docs/config-schema.md` (server params section; add `gclib_api`)
- Modify: docstrings citing Galil as Windows-only: `helao/deploy/hte/tests/browser_parity/check_aligner.py:11`, `helao/deploy/hte/tests/test_motion_private_endpoints.py:39`, `helao/deploy/hte/tests/smoke/golden_capture_galil.py:38`, `helao/deploy/hte/tests/smoke/golden_capture_galil_io.py:48`, and any further hit of the Step 1 search outside dated docs.
- Do NOT edit: dated `docs/superpowers/{plans,specs}/20*` files and `docs/cards-refactor/*` (history).

- [ ] **Step 1: Find every claim**

Run: `rg -n -i "galil|gclib" -g '*.md' -g '*.py' -g '*.yml' . | rg -i "windows|win32"` and list hits outside the do-not-edit set.

- [ ] **Step 2: Edit**

- `CLAUDE.md` bullet becomes: "Windows-only drivers: Gamry (`comtypes`) here, plus Ocean Insight (`oceandirect`) in a private deployment. Galil (`gclib`) runs on Windows and Linux; its servers take `gclib_api` (`\"1\"` default: wrapper 1.0 `gclib.py()`; `\"2\"`: wrapper 2.x `gclib.Controller`), which must match the wrapper installed in the env. Most other code, ..." — keep the rest of the bullet (vendor packages imported inside `connect()`/`open()`, `ENV` in `run_tests.py`) and make "All three" read correctly for the new list.
- `readme.md` line: "Windows is required for Gamry (comtypes) drivers. Galil (gclib) drivers run on Windows and Linux."
- `win_job.py`: Galil no longer listed as Windows-only; keep the docstring's point about held ports.
- Both galil READMEs:

```markdown
# galil_io: vendor software

Install by hand (not pip/conda), on Windows or Linux:

1. The Galil gclib C library: the vendor installer on Windows, the Galil package
   repository on Linux (https://www.galil.com/sw/pub/all/doc/gclib/html/).
2. One gclib Python wrapper. Both install as `import gclib`, so an env holds one,
   and the server's `gclib_api` param must match it:
   - `gclib_api: "1"` (default): wrapper 1.0.1, the `gclib.py()` API, from the
     gclib installation's Python wrapper (gclib 2.4.1 Python docs).
   - `gclib_api: "2"`: wrapper 2.x, the `gclib.Controller` API (Python >= 3.12):
     `pip install --upgrade --index-url https://www.galil.com/sw/pub/python gclib`
     (docs: https://www.galil.com/sw/pub/python/doc/index.html).

A mismatch fails at connect with a message naming `gclib_api`.
```

(same text with `galil_motion` in the title for the motion README).
- `docs/config-schema.md`: add `gclib_api` to the per-server params documentation next to other driver params, with values, default and the mismatch rule (one short paragraph or table row, matching the file's style).
- Test/smoke docstrings: "Windows-only" -> "needs the vendor gclib (Windows or Linux)"; "AT-STATION, Windows" -> "AT-STATION".

- [ ] **Step 3: Verify**

Run: `rg -n -i "galil|gclib" -g '*.md' -g '*.py' . | rg -i "windows-only|\\(windows\\)|windows/at-station"` — only dated plans/specs and `docs/cards-refactor/*` may remain. Grep the changed files for the names of the nested private deployments (`ls helao/deploy`, minus `hte` and `test`) — no new hits.

- [ ] **Step 4: Run the touched tests**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python run_tests.py --filter galil` and `--filter test_motion_private_endpoints`
Expected: PASS (docstring-only changes).

- [ ] **Step 5: Commit**

```bash
black helao/helpers/win_job.py helao/deploy/hte/tests
git add CLAUDE.md readme.md docs/config-schema.md helao/helpers/win_job.py helao/deploy/hte
git commit -m "docs(galil): gclib runs on Linux; install steps for both wrappers and gclib_api"
```

The controller (not the implementer) then greps the nested private deployments for the same Windows-only wording about Galil and fixes it in their own repos.
