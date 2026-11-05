# spec: vendor software

Install by hand (not pip/conda):

- Spectral Products SDK: `SMdbUSBm.dll` (SM303), loaded with `ctypes.CDLL` from the `lib_path` key of the server config (the driver fails to connect if that file is missing).
