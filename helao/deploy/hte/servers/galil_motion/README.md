# galil_motion: vendor software

Install by hand (not pip/conda), on Windows or Linux:

1. The Galil gclib C library: the vendor installer on Windows, the Galil package
   repository on Linux (https://www.galil.com/sw/pub/all/doc/gclib/html/).
2. One gclib Python wrapper. Both install as `import gclib`, so an env holds one,
   and the server's `gclib_api` param must match it:
   - `gclib_api: "1"` (default): wrapper 1.0.1, the `gclib.py()` API, from the
     gclib installation's Python wrapper (gclib 2.4.1 Python docs). From the
     helao env on Windows:
     `python "C:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`.
     On Linux, run the same `setup.py install` from the `wrappers/python` folder
     of the gclib installation. Alternative (`setup.py install` is deprecated
     in current setuptools): `python -m pip install "<gclib install>/source/wrappers/python"`.
   - `gclib_api: "2"`: wrapper 2.x, the `gclib.Controller` API (Python >= 3.12):
     `pip install --upgrade --index-url https://www.galil.com/sw/pub/python gclib`
     (docs: https://www.galil.com/sw/pub/python/doc/index.html).
     Not yet verified at a station (reply trimming, gcaps bypass, unsolicited
     output without `-s ALL`): before using `"2"` in production, run
     `helao/deploy/hte/tests/smoke/golden_capture_galil.py` and
     `golden_capture_galil_io.py` with `"1"` and with `"2"` and diff the captures.

A mismatch fails at connect with a message naming `gclib_api`.
