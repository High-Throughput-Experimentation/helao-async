# hte Andor Zyla + spectrograph — two driver variants

<!-- Split out of the root CLAUDE.md. Loaded when work touches this directory. -->

`helao/deploy/hte/drivers/spec/andor/` holds one camera base and two variants,
selected by the action server's `wl_source` param (`spectrograph` | `calibration`).

- **The base is abstract on `_wavelengths()` alone.** Everything else — SDK handle,
  camera, imaging, acquire loop, cooling, buffers — is shared. A subclass that
  forgot the hook would acquire against a fabricated wavelength axis, which is
  invisible in the recorded data, so it is `@abstractmethod` rather than a
  defaulted hook.
- **`spectrograph.py` is the only module that imports `pyAndorSpectrograph`**, pinned by
  `test_andor_vendor_isolation.py`, which parses imports rather than grepping source —
  a grep also matches the docstrings explaining the rule. What actually makes a spectrograph-free station
  possible is that `_load_andor()` was split into `_load_camera()` and
  `_load_spectrograph()`: the combined loader was called unconditionally from
  `connect()`, so the class split alone would have changed nothing — a subclass
  inherits that `connect()`. Two pre-existing standalone scripts in that package
  (`test_funcs.py`, `test_read_loop.py`) do import the vendor package; they are
  exempted by exact name because nothing imports *them* — each builds `AndorSDK3()`
  at module scope, so they are in no station's import graph, and a test pins that.
- **An absent `wl_source` yields the spectrograph driver**, so every existing station
  config keeps working unedited. An *unrecognized* value raises: a typo would
  otherwise hand a lamp-calibrated station the spectrograph driver and fail much
  later at `connect()` with a vendor import error.
- **`connect()` succeeds on an uncalibrated station; `acquire` is what refuses.** The
  calibration action runs on the same server, so a refusing `connect()` would leave
  the station uncalibratable forever. `acquire` cannot fall back to a pixel index —
  both the channel names and `optional.wl` come from `wl_arr`.
- **`run_wl_calibration()` is on the base, so a spectrograph station can measure a
  lamp too** and compare the fit against `GetCalibration` without changing its live
  axis. The response's `applied` field says which happened. On the lamp-calibrated
  variant the fit becomes the live axis immediately, with no restart.
- **`base_api` names the driver namedtuple field from the class name**, so
  `app.drivers.AndorSpectrographDriver` and `app.drivers.AndorCalibratedDriver`
  differ per station. Use `app.driver`.
- Persisted calibration: `<STATES>/<host>_<server_key>_andor_wl_calib.json`,
  coefficients not an array, with `model` refused on an unrecognized value rather
  than mis-evaluated.
- **Known pre-existing defect, deliberately not fixed here: `/ANDOR/adjust_nd` has
  never worked.** `Executor.__init__` (`helao/helpers/executor.py`) sets no
  `self.driver` and the class defines no `__getattr__`, while `AndorAdjustND` has no
  `__init__` of its own — only a bare `driver: AndorSpectrographDriver` class
  annotation, which binds nothing. Its `_exec` therefore raises `AttributeError`
  before reaching the driver. The siblings `AndorCooling`, `AndorCalibrateWavelength`
  and `AndorAcquire` each bind `self.driver = self.active.driver` in their own
  `__init__`; the fix is one such `__init__`. It was left alone because the endpoint
  is *inert* today: repairing it would make a station suddenly begin physically
  driving the ND filter wheel through six exposures (`adjust_ND` sweeps positions
  1..6), a hardware-affecting change outside this plan and the station owner's call.
