# helao.servers.action package

## Submodules

## helao.servers.action.analysis_server module

Analysis server

The analysis server produces and uploads ESAMP-style analyses to S3 and API,
it differs from calc_server.py which does not produce Analysis models.

### helao.servers.action.analysis_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.andor_server module

## helao.servers.action.biologic_server module

## helao.servers.action.calc_server module

General calculation server

Calc server is used for in-sequence data processing.

### helao.servers.action.calc_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.cam_server module

Webcam server

### helao.servers.action.cam_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.co2sensor_server module

Serial sensor server

### helao.servers.action.co2sensor_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.cpsim_server module

## helao.servers.action.dbpack_server module

Data packaging server

The data packaging server collates finished actions into processes.
Finished actions which do not contribute process information are pushed to

### helao.servers.action.dbpack_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.diapump_server module

A FastAPI service definition for a diaphragm pump server.

### helao.servers.action.diapump_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.galil_io module

## helao.servers.action.galil_motion module

## helao.servers.action.gamry_server module

## helao.servers.action.gamry_server2 module

## helao.servers.action.gpsim_server module

## helao.servers.action.kinesis_server module

Kinesis motor server

### helao.servers.action.kinesis_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.mfc_server module

Serial MFC server

### helao.servers.action.mfc_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.nidaqmx_server module

### helao.servers.action.nidaqmx_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.o2sensor_server module

## helao.servers.action.pal_server module

### helao.servers.action.pal_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.spec_server module

Spectrometer server

Spec server handles setup and configuration for spectrometer devices. Hardware triggers
are the preferred method for synchronizing spectral capture with illumination source.

### helao.servers.action.spec_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.syringe_server module

A FastAPI service definition for a syringe pump server.

### helao.servers.action.syringe_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.tec_server module

Thermoelectric cooler server

### helao.servers.action.tec_server.makeApp(confPrefix, server_key, helao_repo_root)

## helao.servers.action.ws_simulator module

Motion simulation server

FastAPI server host for the websocket simulator driver.

### helao.servers.action.ws_simulator.makeApp(confPrefix, server_key, helao_repo_root)

## Module contents
