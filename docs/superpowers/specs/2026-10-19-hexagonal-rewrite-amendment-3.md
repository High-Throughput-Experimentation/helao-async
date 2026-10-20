# Hexagonal Rewrite — Amendment 3: the host owns the driver lifecycle, and two ports shrink to what is used

**Date:** 2026-10-19
**Amends:** `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` (master
spec), as previously amended by
`docs/superpowers/specs/2026-08-04-hexagonal-rewrite-ui-amendment.md` (Amendment 1) and
`docs/superpowers/specs/2026-08-08-hexagonal-rewrite-amendment-2.md` (Amendment 2)
**Status:** Adopted. §13 of the master spec requires an amendment to change a phase's scope
or a wire contract. This changes the scope of §4.3.1, §4.3.2 and §4.5.
**Baseline:** the `feat/hexagon-completion` branch @ `bf302ba2`.
**Privacy rule:** inherited verbatim from the master spec §8 preamble. The private
deployments are **Deployment-A/B/C/E** only.

Design: `docs/superpowers/specs/2026-10-19-hardware-datasink-wiring-design.md`. Measured
corrections: §2 (A1–A13) of `docs/superpowers/plans/2026-10-19-hardware-datasink-wiring.md`.

---

## 1. §4.3.1 — the hardware contract is the `HelaoDriver` ABC

`HardwarePort` and `ExclusiveAccess` are dropped. They were never wired and had no
production caller. The hardware contract is the `HelaoDriver` ABC plus one new class
attribute, `connect_on_startup: ClassVar[bool] = False`. Bus exclusivity stays inside each
driver.

A driver must not do device I/O in `__init__`. One class, which no hte station uses, still does;
every other driver now connects through the host (§5).

## 2. §4.3.2 — `DataSinkPort` is ten members, with no adapter

`DataSinkPort` keeps the members drivers and executors actually use: `enqueue_data`,
`enqueue_data_nowait`, `get_realtime_nowait`, `finish_hlo_header` (now synchronous),
`write_file`, `write_file_nowait`, `track_file`, `append_sample`, `split`, `set_estop`.
`ActionSession` satisfies it structurally. `NativeDataSinkAdapter` and
`ActiveDataSinkAdapter` are deleted.

`_base_hook` does not collapse into the DataSink. It is typed as the host-scoped
`DriverHostPort` (`ports/hardware.py`): ten members, read-only properties for data
members, satisfied by `ActionHost` with no adapter. An AST test restricts every
`Executor`, `HelaoDriver` and `DriverPoller` subclass to those members and forbids
handing the host off whole.

## 3. §4.5 — `PortWiring` slots

`PortWiring` has no `hardware`, `data_sink`, `sample_state` or `ui_host` slot, and
`data_sink` leaves `ACTION_REQUIRED`. The `SampleStatePort` and `UiHostPort` Protocols
stay, minus `UiHostPort.build_ui_app`.

## 4. §4.5 — host-owned lifecycle

For each `HelaoDriver` class, `ActionHost` startup constructs it from `server_params`, sets
`_base_hook`, calls `connect()` once if `connect_on_startup` is true, then builds the poller,
then runs `dyn_endpoints`.

**A `connect()` that raises does not stop startup** (user decision; this replaces the
master spec's "the exception propagates" rule, A3). The host logs it at ERROR with the
traceback, raises an alert, and continues with the driver disconnected. The poller and
`dyn_endpoints` still run. A constructor that raises still stops startup.

## 5. §10.4 — the disconnected-construct ratchet

`test_driver_disconnected_construct.py` holds two exact sets keyed by `module.qualname`:
`CONSTRUCTOR_CONNECT_PENDING` (checked by AST) and `CONNECT_ON_STARTUP`. Each increment
moves its classes from the first into the second. The first set ends at one class, the
driver that no hte station uses and that this work does not flip.

---

Everything else in the master spec and Amendments 1 and 2 stands.
