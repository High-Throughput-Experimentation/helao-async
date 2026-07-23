# P3a galil-3 DEEPENED — native gclib motion driver (command-channel port)

> Deepens the slice-3 `GalilMotionHardwareAdapter` (which merely delegated to the
> legacy `Galil`) into a genuinely native motion driver that OWNS the gclib
> interaction behind a thin command-channel port. Goal: the pure motion logic
> (command generation, coordinate transform, position/status parsing) becomes
> **Linux-unit-testable for the first time**; only the gclib TCP I/O is
> at-station. Mirrors the PAL transport-port split. NOT runtime-wired.

## The boundary (verified against legacy `galil_motion_driver.py`)

Every gclib touch reduces to two things:
1. **Connection lifecycle**: `gclib.py()`, `g.GOpen(conn_str)`, `g.GInfo()`,
   `g.GVersion()`, `g.GClose()`, `gclib.GclibError`.
2. **Command channel**: `galilcmd = g.GCommand`; `galilcmd(cmd: str) -> str`.

Everything else (axis-id↔ABCDEFGH mapping, `count_to_mm` scaling, TP/PA/SC
parsing, init sequences, transform math) is pure Python over those two.

## Modules

- `helao/hexagon/ports/galil_command_channel.py` — `GalilCommandChannel`
  Protocol: `open(conn_str)`, `command(cmd) -> str`, `info() -> str`,
  `version() -> str`, `close()`, plus `GalilChannelError`.
- `helao/hexagon/adapters/legacy/galil_command_channel.py` —
  `GclibCommandChannel`: lazy `import gclib` (Windows/at-station), wraps
  `gclib.py()` + GOpen/GCommand/GInfo/GVersion/GClose. Constructible on Linux
  (no gclib at __init__); real I/O at-station.
- `helao/hexagon/adapters/native/galil_motion_native.py` —
  `NativeGalilMotion`: owns a `GalilCommandChannel` + `axis_id` + `count_to_mm`
  + slice-1 `TransformXY` + slice-2 `JsonFileCalibrationStore`. Reimplements the
  motion verbs over the channel (no legacy `Galil` wrapped).

## Slices

### native-1 (THIS pass — Linux-complete, construct+unit-tested)
- `GalilCommandChannel` port + `GclibCommandChannel` (lazy) + a `FakeChannel`
  test double (records commands, returns programmed TP/PA/SC responses).
- `NativeGalilMotion`: `connect` (open + axis-init sequence `PF 10.4`; per axl
  `MG _MO{axl}`→`SH{axl}` if off; `MT/CE/TW/SD` sets; load calib + build
  `TransformXY`), `get_status`, `get_all_axis`, `query_axis_position`
  (TP→PA→scale/map), `query_axis_moving` (SC→classify), `stop_axis`, `motor_off`,
  `motor_on`, `reset_controller`, `estop` (=stop_axis+motor_off), `disconnect`/
  `shutdown` (channel.close). Optional `position_sink` callback preserves the
  aligner position-notify feed (default None).
- **`_motor_move` and `setaxisref` raise `NotImplementedError` with a
  "deferred to native-2" message** (fail-loud, not silent) — the 380-line
  transform-move orchestration is its own focused pass.
- Unit tests over `FakeChannel`: exact command strings emitted (init sequence,
  ST/MO/SH, RS), TP/PA/SC parse → mm via `count_to_mm` + axis_id inverse,
  disconnected-construct (no gclib), estop verb sequence, position_sink feed.

### native-2 (NEXT pass)
- Port `_motor_move` (coordinate transform per `TransformationModes`
  motorxy/platexy/instrxy × `MoveModes` relative/absolute/homing; speed/accel;
  PA/BG; settle-poll) + `setaxisref` (homing) over the channel. Heavy pure
  logic → extensive unit tests with `FakeChannel`.

### cut-over (at-station only)
Repoint the galil action server `app.driver` at `NativeGalilMotion` (or have
`GalilMotionHardwareAdapter` wrap it). Validate on the controller
(`192.168.200.234`): every verb byte-parity vs legacy, real TP/PA/SC, motion,
estop. Resolve the shutdown-await framework seam (shared with all native
adapters) as part of cut-over.

## Invariants
- Command strings + parse math byte-identical to legacy (verify in unit tests
  against the exact legacy expressions).
- `gclib` import stays lazy inside the channel adapter (never at module/adapter
  construction) — Linux construct-test must pass with gclib absent.
- Return dict shapes identical to legacy verbs (`{"ax":[],"position":[]}`,
  `{"motor_status":[],"err_code":...}`) so a future cut-over is drop-in.
