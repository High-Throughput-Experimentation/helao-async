# Galil gclib 2.0 backend — design

Date: 2026-11-05. Status: approved approach (shared channel port), spec pending review.

## Goal

A recent gclib release ships a reorganised Python wrapper (2.0, `gclib.Controller`) that is not
compatible with the 1.0 wrapper (`gclib.py()` / `GOpen` / `GCommand`) the Galil drivers use. Keep the
1.0 path working unchanged and add a 2.0 path for both Galil servers (`galil_io`, `galil_motion`),
chosen per server in the config, with identical action behaviour. Also correct documentation that calls
Galil/gclib Windows-only: gclib and both wrappers run on Linux too.

## Facts that shape the design

- Both wrappers install as the same import name `gclib`. One env holds one of them, so a station's
  config choice must match what is installed there.
- Calls the drivers make today (1.0): `gclib.py()`, `GOpen("<ip> --direct -s ALL")`, `GCommand`,
  `GInfo`, `GVersion`, `GClose`, and (I/O only) `GProgramDownload("DL;")` / `GProgramDownload(prog + "\x00")`;
  errors are `gclib.GclibError`. No messages, interrupts, data records or arrays are used; the DMC
  programs the I/O server downloads emit no `MG` output.
- 2.0 (docs: https://www.galil.com/sw/pub/python/doc/api.html): `gclib.Controller(address)` opens on
  construction; `.command(cmd) -> str`, `.revision_information()`, `.serial_number()`, `.address()`,
  `.set_program(program, insert="")`, `.close()`; module `gclib.version()`, `gclib.force_gcaps(on)`;
  errors `gclib.Error`. Requires Python >= 3.12. Install:
  `pip install --upgrade --index-url https://www.galil.com/sw/pub/python gclib` on top of the gclib C
  library (Windows and Linux packages from Galil).
- Motion already isolates gclib: `NativeGalilMotion` talks only to the `GalilCommandChannel` port
  (`galil_motion/galil_command_channel_port.py`); `GclibCommandChannel` (`galil_command_channel.py`)
  is the 1.0 implementation. The I/O driver (`galil_io/galil_io_driver.py`) calls `self.g.G*` directly
  through two aliases, `self.galilcmd` and `self.galilprgdownload`.

## Design

### One port, two channels
- `GalilCommandChannel` (port) gains `download_program(program: str) -> None`. It stays in
  `galil_motion/galil_command_channel_port.py`; `galil_io` imports it across folders (shared code lives
  with its owner).
- `GclibCommandChannel` (1.0) keeps its behaviour; it adds `download_program`, which calls
  `GProgramDownload(program)` exactly as the I/O driver does today (callers keep passing `"DL;"` and
  `prog + "\x00"` unchanged).
- New `Gclib2CommandChannel` (2.0), same module family (`galil_motion/galil_command_channel2.py`):
  - `open(connection_string)`: takes the IP (first whitespace token of the legacy string, so callers
    keep passing `"<ip> --direct -s ALL"`); calls `gclib.force_gcaps(False)` when `--direct` is present,
    then `gclib.Controller(ip)`.
  - `command(cmd)` -> `Controller.command(cmd)`; `download_program(p)` -> `Controller.set_program(p)`
    with a trailing `"\x00"` stripped (the 1.0 terminator).
  - `info()` -> `"<address>, <revision_information>, <serial_number>"` (the 1.0 `GInfo` shape);
    `version()` -> `gclib.version()`; `close()` idempotent.
  - `gclib.Error` maps to the port's `GalilChannelError`, like the 1.0 channel maps `GclibError`.
- Both channels import `gclib` lazily inside `open` (the modules import on any machine without gclib).
- Wrong wrapper installed: the 1.0 channel raises `GalilChannelError("gclib_api '1' needs the 1.0
  wrapper (gclib.py); the installed gclib has Controller — set gclib_api: '2' or install wrapper 1.0.1")`
  when `gclib` lacks `py`; the 2.0 channel raises the mirror message when `gclib` lacks `Controller`.

### Selection
- Server param `gclib_api` on `galil_io` and `galil_motion` servers: `"1"` (default when absent) or
  `"2"`; anything else raises at driver construction naming the server and the allowed values (the
  `pstat_backend` rule). A YAML integer `1`/`2` is accepted and normalised to the string.
- `CHANNELS = {"1": GclibCommandChannel, "2": Gclib2CommandChannel}` beside the port; both drivers pick
  from it. `NativeGalilMotion` keeps its injectable `channel=` argument (tests).

### I/O driver onto the port
- `GalilIODriver.connect()` builds the selected channel, `open("<ip> --direct -s ALL")`, logs
  `version()`/`info()`, and binds `self.galilcmd = channel.command`,
  `self.galilprgdownload = channel.download_program`; `disconnect()` calls `channel.close()`. All other
  driver code (17 `galilcmd` and 2 `galilprgdownload` call sites) is untouched. `self.g` is removed
  (grep for remaining users first; tests that set `galilcmd` fakes keep working).

### Docs
- Replace "Windows-only"/"Windows" claims about Galil/gclib with "Windows and Linux" in: root
  `CLAUDE.md` (Windows-only drivers bullet: Gamry stays Windows-only), `readme.md`,
  `helao/helpers/win_job.py` docstring, the galil driver/channel docstrings, both galil `README.md`
  (add install steps for both wrappers and the `gclib_api` param), hte test/smoke docstrings that cite
  it. Dated plans/specs stay as history. `docs/config-schema.md` documents `gclib_api`. The same
  correction in nested private deployments is done in their own repos.

## Testing
- Fake `gclib` modules (1.0 shape and 2.0 shape) injected via `sys.modules`; a recording fake records
  every call.
- Parity: drive each I/O and motion action path used by the servers through the driver with each fake
  and assert the controller command sequence and returned values are identical between `"1"` and `"2"`
  (the logic is shared, so this pins the channel translation). Includes program download (`DL;`, DMC
  body with and without `"\x00"`), info/version, close, and error mapping (`GclibError` / `Error` ->
  `GalilChannelError`).
- Selection: absent -> 1.0 channel; `"2"`/`2` -> 2.0; unknown -> error; wrong wrapper -> clear error.
- Existing galil tests and `run_tests.py` sweep unchanged-green.
- At station (out of scope for CI): run `tests/smoke/golden_capture_galil*.py` with `gclib_api: "1"`
  on wrapper 1.0.1 and `"2"` on wrapper 2.0 and diff; confirm `set_program` with the DMC programs and
  that no unsolicited output leaks into command responses without `-s ALL`.

## Out of scope
- Using 2.0-only features (data records, interrupts, callbacks).
- Installing the wrapper via `setup_env` (the index URL and C library are per-station vendor installs;
  documented in the folder READMEs).
