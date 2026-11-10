# hte split: root env audit

Input to Task 6 of `2026-11-10-hte-nested-repo.md`. Changes no code. Base commit `7a4ff2af`.

## Method

`env_audit.py` (scratch, untracked) lists every package in `helao_dev_linux-64.yml`, `helao_dev_win-64.yml` (conda and pip sections) and `requirements.txt`, maps each distribution to its import names with `importlib.metadata.packages_distributions()`, and parses every `.py` under `helao/`, `harness/` and the repo-root scripts with `ast`. Each import is filed under the zone of the importing file: `framework` (anything outside `helao/deploy/`), `base`, `test`, `hte-shared` (hte code outside `servers/<folder>/`), `hte-server:<folder>`, or `private` (every other deployment; named only as `private` here). Distribution names that did not map (`UNMAPPED`: not installed here, or not a Python distribution) and packages with no importer (`none`) were resolved by hand with grep, `importlib.metadata` reverse dependencies and the existing server env files; the "note" column records how. Classes were applied in this order: (1) imported by framework, base or test: `framework` or `base`; (2) imported only by `hte-server:<folder>` zones: that folder; (3) imported by `hte-shared` and not by framework/base/test or private: `hte-shared`; (4) imported by `private` and not by framework/base/test: `private-only` (OQ-4, stays in root), or `shared-with-private` when hte code also imports it (controller ruling, same reasoning; stays in root); (5) no importer: `unused` (stays; removal is out of scope). Tools that are not imported are `tooling` and stay. Pins are copied from `helao_pinned_<platform>.yml` (conda) and `requirements_pinned_<platform>.txt` (pip) per R8; `Ln` is the line number in that pinned file (R6: Task 6 deletes those lines as a text edit and never re-solves).

Scan limits: dynamic imports and string-loaded plug-ins are invisible to the AST scan. Those cases were found by hand (see notes), not guessed.

## Table

| package | source file | import names | used by | class | destination | pin linux-64 | pin win-64 | note |
|---|---|---|---|---|---|---|---|---|
| aioboto3 | dev-linux, dev-win | `aioboto3` | private | private-only | root (stays) | 15.5.0 (L7) | 15.5.0 (L6) |  |
| aiofiles | dev-linux, dev-win | `aiofiles` | framework, hte-server:cam, hte-server:pal, hte-server:xafs | framework | root | 25.1.0 (L9) | 25.1.0 (L8) |  |
| aiohttp | dev-linux, dev-win | `aiohttp` | framework, private | framework | root | 3.14.5 (L11) | 3.14.5 (L10) |  |
| anyio | dev-linux, dev-win | `anyio` | none | unused | root (stays) | 4.15.1 (L18) | 4.15.1 (L16) | no importer found by the AST scan or grep; transitive of starlette, httpx, asyncua |
| anywidget | dev-linux, dev-win | `anywidget` | none | unused | root (stays) | 0.11.0 (L19) | 0.11.0 (L17) | no importer found by the AST scan or grep; transitive of xy |
| asyncua | dev-linux, dev-win | `asyncua` | private | private-only | root (stays) | 2.1.0 (L25) | 2.1.0 (L23) |  |
| black | dev-linux, dev-win | `_black_version`, `black`, `blackd`, `blib2to3` | none | tooling | root | 26.10.1 (L49) | 26.10.1 (L47) | tool |
| bokeh | dev-linux, dev-win | `bokeh`, `typings` | base, framework, hte-server:biologic, hte-server:gamry, hte-server:nidaqmx, hte-server:sample, hte-server:spec, hte-server:tec, hte-shared, private, test | framework | root | 3.10.0 (L52) | 3.10.0 (L50) |  |
| boto3 | dev-linux, dev-win | `boto3` | framework, private | framework | root | 1.40.61 (L53) | 1.40.61 (L51) |  |
| botocore | dev-linux, dev-win | `botocore` | none | unused | root (stays) | 1.40.61 (L54) | 1.40.61 (L52) | no importer found by the AST scan or grep; transitive of boto3 |
| colorama | dev-linux, dev-win | `colorama` | framework | framework | root | 0.4.6 (L68) | 0.4.6 (L66) |  |
| colorlog | dev-linux, dev-win | `colorlog` | framework | framework | root | 6.12.0 (L69) | 6.12.0 (L67) |  |
| comtypes | dev-win | `UNMAPPED` | none | shared-with-private | root (stays) | absent | 1.4.16 (L69) | UNMAPPED on Linux (win-only, not installed); import `comtypes` matched by grep. imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| docformatter | dev-linux, dev-win | `docformatter` | none | tooling | root | 1.7.8 (L80) | 1.7.8 (L77) | tool |
| fastapi | dev-linux, dev-win | `fastapi` | base, framework, hte-server:biologic, hte-server:cam, hte-server:co2sensor, hte-server:galil_io, hte-server:galil_motion, hte-server:gamry, hte-server:mfc, hte-server:nidaqmx, hte-server:o2sensor, hte-server:pal, hte-server:sample, hte-server:spec, hte-server:tec, hte-server:xafs, hte-shared, private, test | framework | root | 0.162.0 (L87) | 0.162.0 (L84) |  |
| filelock | dev-linux, dev-win | `filelock` | framework, private | framework | root | 4.2.4 (L91) | 4.2.4 (L88) |  |
| fsspec | dev-linux, dev-win | `fsspec` | none | unused | root (stays) | 2026.9.0 (L105) | 2026.9.0 (L102) | no importer found by the AST scan or grep; transitive of s3fs |
| git | dev-linux, dev-win | `UNMAPPED` | none | tooling | root | 2.56.0 (L107) | 2.56.0 (L103) | tool (conda binary) |
| h5py | dev-linux, dev-win | `h5py` | private | private-only | root (stays) | absent | absent |  |
| httpx | dev-linux, dev-win | `httpx` | framework, hte-server:pdu, hte-server:xafs, private | framework | root | 0.28.1 (L123) | 0.28.1 (L115) |  |
| ipykernel | dev-linux, dev-win | `ipykernel`, `ipykernel_launcher` | none | tooling | root | 7.4.0 (L129) | 7.4.0 (L121) | tool |
| ipympl | dev-linux, dev-win | `ipympl` | none | unused | root (stays) | 0.10.0 (L130) | 0.10.0 (L122) | no importer found by the AST scan or grep; notebook widget, no importer |
| ipywidgets | dev-linux, dev-win | `ipywidgets` | none | unused | root (stays) | 8.1.9 (L133) | 8.1.9 (L125) | no importer found by the AST scan or grep; transitive of ipympl, anywidget |
| itables | dev-linux, dev-win | `itables`, `itables_for_dash` | none | unused | root (stays) | 2.9.1 (L135) | 2.9.1 (L127) | no importer found by the AST scan or grep; notebook widget, no importer |
| joblib | dev-linux, dev-win | `joblib` | none | unused | root (stays) | 1.6.0 (L140) | 1.6.0 (L132) | no importer found by the AST scan or grep; transitive of scikit-learn |
| jupyterlab | dev-linux, dev-win | `jupyterlab` | none | tooling | root | 4.6.4 (L153) | 4.6.4 (L145) | tool |
| matplotlib | dev-linux, dev-win | `__pycache__`, `matplotlib`, `mpl_toolkits`, `pylab` | hte-shared, private | shared-with-private | root (stays) | 3.11.2 (L264) | 3.11.2 (L222) | scan import names include a `__pycache__` artefact. imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| mendeleev | dev-linux, dev-win | `mendeleev` | framework, private | framework | root | 0.16.2 (L269) | 0.16.2 (L227) |  |
| mpltern | dev-linux, dev-win | `mpltern` | none | unused | root (stays) | 1.0.5 (L275) | 1.0.5 (L230) | no importer found by the AST scan or grep; no importer |
| msgspec | dev-linux, dev-win | `msgspec` | framework | framework | root | 0.22.0 (L277) | 0.22.0 (L232) |  |
| nidaqmx | requirements.txt | `nidaqmx` | hte-server:nidaqmx, hte-server:pal, private | shared-with-private | root (stays) | 1.7.0 (L7) | 1.7.0 (L7) | imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| nodejs | dev-linux, dev-win | `UNMAPPED` | none | tooling | root | 26.12.1 (L291) | 26.12.1 (L245) | tool (reflex build) |
| ntplib | dev-linux, dev-win | `ntplib` | framework | framework | root | 0.4.0 (L295) | 0.4.0 (L247) |  |
| numpy | dev-linux, dev-win | `numpy` | base, framework, hte-server:analysis, hte-server:andor, hte-server:biologic, hte-server:calc, hte-server:co2sensor, hte-server:galil_motion, hte-server:gamry, hte-server:mfc, hte-server:nidaqmx, hte-server:power_supply, hte-server:spec, hte-server:xafs, hte-shared, private, test | framework | root | 2.5.4 (L297) | 2.5.4 (L249) |  |
| orjson | dev-linux, dev-win | `orjson` | framework | framework | root | 3.13.0 (L304) | 3.13.0 (L254) |  |
| pandas | dev-linux, dev-win | `pandas` | framework, hte-server:analysis, hte-server:andor, hte-server:biologic, hte-server:gamry, hte-server:xafs, hte-shared, private | framework | root | 3.1.0 (L307) | 3.1.0 (L257) |  |
| panel | dev-linux, dev-win | `panel` | none | unused | root (stays) | 1.10.0 (L309) | 1.10.0 (L259) | no importer found by the AST scan or grep; no importer |
| paramiko | dev-linux, dev-win | `paramiko` | hte-server:pal | hte-server:pal | hte/servers/pal/environment.yml (already declared as `paramiko=3`; tighten to `paramiko=3.5.1`; remove from root) | 3.5.1 (L314) | 3.5.1 (L264) |  |
| pip | dev-linux, dev-win | `pip` | none | tooling | root | 26.2.2 (L322) | 26.2.2 (L270) | tool |
| plotly | dev-linux, dev-win | `_plotly_utils`, `plotly` | private | private-only | root (stays) | 7.1.0 (L325) | 7.1.0 (L273) |  |
| psutil | dev-linux, dev-win | `psutil` | framework, hte-server:gamry, hte-server:pal, hte-server:xafs | framework | root | 7.2.2 (L333) | 7.2.2 (L281) |  |
| psycopg2 | dev-linux, dev-win | `psycopg2` | none | framework | root | 2.9.13 (L334) | 2.9.13 (L282) | matched by string, not import: SQLAlchemy loads it from the `postgresql+psycopg2` scheme in helao/core/models/credentials.py |
| pyaml | dev-linux, dev-win | `pyaml` | none | unused | root (stays) | 26.7.0 (L340) | 26.7.0 (L285) | no importer found by the AST scan or grep; no importer |
| pyarrow | dev-linux, dev-win | `pyarrow` | framework, hte-shared, private, test | framework | root | 25.0.0 (L341) | 25.0.0 (L286) |  |
| pydantic | dev-linux, dev-win | `pydantic` | framework, hte-server:analysis, hte-server:pal, hte-server:xafs, private, test | framework | root | 2.14.1 (L347) | 2.14.1 (L292) |  |
| pydantic-core | dev-linux, dev-win | `pydantic_core` | framework | framework | root | 2.50.1 (L348) | 2.50.1 (L293) |  |
| pydantic-settings | dev-linux, dev-win | `pydantic_settings` | framework | framework | root | 2.16.1 (L350) | 2.16.1 (L295) |  |
| pydasher | requirements.txt | `pydasher` | framework | framework | root | 0.1.0 (L9) | 0.1.0 (L9) |  |
| pyfiglet | dev-linux, dev-win | `pyfiglet` | framework | framework | root | 1.0.4 (L351) | 1.0.4 (L296) |  |
| pyft232 | requirements.txt | `ft232` | none | hte-server:kinesis | hte/servers/kinesis/requirements.txt (already declared; tighten to pin; remove from root) | 0.12 (L10) | 0.12 (L10) | import name `ft232`, loaded dynamically by pylablib (the hte instrument-env test says so); matched by hand |
| pyftdi | dev-linux, dev-win | `pyftdi` | none | unused | root (stays) | 0.55.4 (L352) | 0.55.4 (L297) | no importer found by the AST scan or grep; no importer |
| pylablib | dev-linux, dev-win | `pylablib` | hte-server:kinesis, private | shared-with-private | root (stays) | 1.4.2 (L354) | 1.4.2 (L299) | imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| pymecom | requirements.txt | `UNMAPPED` | none | hte-server:tec | hte/servers/tec/requirements.txt (already declared; tighten to pin; remove from root) | URL (unversioned) (L35) | URL (unversioned) (L35) | import name `mecom`, imported by tec/mecom_driver.py; matched by hand |
| pymodbus | dev-linux, dev-win | `pymodbus` | private | private-only | root (stays) | 3.16.1 (L355) | 3.16.1 (L300) |  |
| pyright | dev-linux, dev-win | `pyright` | none | tooling | root | 1.1.414 (L361) | 1.1.414 (L306) | tool |
| pyserial | dev-linux, dev-win | `serial` | hte-server:co2sensor, hte-server:diapump, hte-server:mfc, hte-server:o2sensor, hte-server:syringe, hte-shared, private | shared-with-private | root (stays) | 3.5 (L362) | 3.5 (L307) | imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| pytest-asyncio | dev-linux, dev-win | `pytest_asyncio` | private | tooling | root | 1.4.1 (L366) | 1.4.1 (L311) | tool (brief lists it as tooling; also imported by private tests) |
| pytest-xdist | dev-linux, dev-win | `xdist` | none | tooling | root | 3.8.0 (L367) | 3.8.0 (L312) | tool |
| python | dev-linux, dev-win | `UNMAPPED` | none | tooling | root | 3.14.10 (L368) | 3.14.10 (L313) | tool |
| python-dotenv | dev-linux, dev-win | `dotenv` | none | unused | root (stays) | 1.2.4 (L370) | 1.2.4 (L315) | no importer found by the AST scan or grep; transitive of pydantic-settings |
| pyusb | dev-linux, dev-win | `usb` | none | unused | root (stays) | 1.3.1 (L380) | 1.3.1 (L326) | no importer found by the AST scan or grep; transitive of pyft232, pylablib, pyftdi |
| pyvisa | dev-linux, dev-win | `pyvisa` | hte-server:power_supply, private | shared-with-private | root (stays) | 1.16.2 (L381) | 1.16.2 (L327) | imported by hte code AND by private zones: stays in root (controller ruling, same reasoning as OQ-4); the hte server folders that already declare it keep their declarations unchanged |
| pyvisa-py | dev-linux, dev-win | `pyvisa_py` | none | unused | root (stays) | 0.8.1 (L382) | 0.8.1 (L328) | no importer; pyvisa backend plugin that pyvisa loads at run time; documented in hte-server:power_supply README; follows pyvisa |
| pyzmq | dev-linux, dev-win | `zmq` | framework | framework | root | 27.2.0 (L385) | 27.2.0 (L333) |  |
| pyzstd | dev-linux, dev-win | `pyzstd` | framework | framework | root | 0.20.0 (L386) | 0.20.0 (L334) |  |
| reflex | requirements.txt | `reflex` | base, framework, hte-server:andor, hte-server:nidaqmx, hte-server:power_supply, hte-server:sample, hte-server:spec, private, test | framework | root | 0.10.1 (L15) | 0.10.1 (L15) |  |
| requests | dev-linux, dev-win | `requests` | framework, hte-server:cam, hte-shared, private | framework | root | 2.34.2 (L393) | 2.34.2 (L340) |  |
| ruamel-yaml | dev-linux, dev-win | `ruamel` | framework, hte-server:calc, hte-shared, private | framework | root | 0.19.1 (L401) | 0.19.1 (L348) |  |
| s3fs | dev-linux, dev-win | `s3fs` | none | unused | root (stays) | 2026.9.0 (L404) | 2026.9.0 (L350) | no importer found by the AST scan or grep; no importer (pandas may load it for s3:// URLs at run time) |
| scikit-learn | dev-linux, dev-win | `sklearn` | test | framework | root | 1.9.1 (L406) | 1.9.1 (L352) | imported only by the `test` deployment zone (rule 1 counts `test`) |
| scipy | dev-linux, dev-win | `scipy` | base, framework, hte-server:analysis, hte-server:andor, hte-server:calc, hte-server:co2sensor, hte-server:mfc, hte-shared, private, test | framework | root | 1.18.1 (L407) | 1.18.1 (L353) |  |
| setuptools | dev-linux, dev-win | `_distutils_hack`, `pkg_resources`, `setuptools` | hte-server:xafs | tooling | root | 81.0.0 (L409) | 81.0.0 (L355) | tool (brief; also pkg_resources import in one hte server) |
| shortuuid | dev-linux, dev-win | `COPYING`, `shortuuid` | none | unused | root (stays) | 1.0.13 (L411) | 1.0.13 (L357) | no importer found by the AST scan or grep; no importer |
| sqlalchemy | dev-linux, dev-win | `sqlalchemy` | framework | framework | root | 2.1.6 (L419) | 2.1.6 (L365) |  |
| starlette | dev-linux, dev-win | `starlette` | framework, hte-shared, private | framework | root | 1.10.0 (L421) | 1.10.0 (L367) |  |
| statsmodels | dev-linux, dev-win | `statsmodels` | none | unused | root (stays) | 0.15.0 (L422) | 0.15.0 (L368) | no importer found by the AST scan or grep; no importer |
| tqdm | dev-linux, dev-win | `tqdm` | none | unused | root (stays) | 4.70.1 (L432) | 4.70.1 (L378) | no importer found by the AST scan or grep; no importer |
| uuid7 | requirements.txt | `uuid_extensions` | framework | framework | root | 0.1.0 (L32) | 0.1.0 (L32) |  |
| uv | dev-linux, dev-win | `UNMAPPED` | none | tooling | root | 0.13.6 (L443) | 0.13.6 (L390) | tool |
| uvicorn | dev-linux, dev-win | `uvicorn` | framework, hte-server:xafs, hte-shared, private | framework | root | 0.54.0 (L444) | 0.54.0 (L391) |  |
| websockets | dev-linux, dev-win | `websockets` | framework, hte-server:sample | framework | root | 17.3 (L455) | 17.3 (L404) |  |
| xy | requirements.txt | `reflex_xy`, `xy` | framework | framework | root | 0.0.8 (L34) | 0.0.8 (L34) |  |
| zeromq | dev-linux, dev-win | `UNMAPPED` | none | tooling | root | 4.3.5 (L485) | 4.3.5 (L412) | tool / libzmq for pyzmq |

Counts (83 packages): framework 36, unused 19, tooling 14, shared-with-private 6, private-only 5, hte-server:pal 1, hte-server:kinesis 1, hte-server:tec 1, hte-shared 0, base 0. `base` is 0 because every package used by `base` is also used by `framework`. Destinations: root 80, hte server folders 3.

UNMAPPED after hand resolution: none. The seven raw `UNMAPPED` rows were comtypes (win-only, not installed on Linux; matched by grep), git, nodejs, python, uv, zeromq (tools, not Python distributions) and pymecom (import name `mecom`; matched by hand).

## Moves

Only three packages leave the root env. Each moves into the server folder that imports it and keeps its exact pin (R8). Where the folder already lists the package more loosely, Task 6 tightens the folder's entry to the pin ("already listed" adds nothing new, but the version still follows R8). Task 6 removes the root line and the pinned lines below as text edits and never re-solves (R6).

| package | folder file | folder entry today | folder entry after Task 6 | root line to remove | pinned lines to remove (linux / win) |
|---|---|---|---|---|---|
| paramiko | `hte/servers/pal/environment.yml` (conda) | `paramiko=3` | tighten to `paramiko=3.5.1` | `helao_dev_linux-64.yml` and `helao_dev_win-64.yml`: `  - paramiko=3` | `helao_pinned_linux-64.yml` L314 `paramiko=3.5.1` / `helao_pinned_win-64.yml` L264 `paramiko=3.5.1` |
| pyft232 | `hte/servers/kinesis/requirements.txt` (pip) | `pyft232` | tighten to `pyft232==0.12` | `requirements.txt`: `pyft232` | `requirements_pinned_linux-64.txt` L10 `pyft232==0.12` / `requirements_pinned_win-64.txt` L10 `pyft232==0.12` |
| pymecom | `hte/servers/tec/requirements.txt` (pip) | the pyMeCom archive URL | unchanged; the pinned files carry the same URL and no version | `requirements.txt`: `https://github.com/meerstetter/pyMeCom/archive/master.zip` | `requirements_pinned_linux-64.txt` L35 / `requirements_pinned_win-64.txt` L35, the same URL line |

Stay in root, nothing deleted: all `framework`, `tooling`, `unused`, `private-only` and `shared-with-private` rows. The hte server folders that already declare comtypes, nidaqmx, pylablib, pyvisa, pyserial keep those declarations unchanged. The brief's assumption that comtypes moves to `environment_win-64.yml` is dropped.

## Deployment-root rule decision

hte-shared packages: 0; the `helao_env.py` deployment-root rule and the deployment-level env files are not needed (skipped).

## Notes

- Rule for packages imported by hte and by any private zone (matplotlib, pyserial, comtypes, nidaqmx, pylablib, pyvisa): they stay in root, because moving them would starve private stations' envs.
- The 19 `unused` packages stay in root; removing packages is out of scope. `pyvisa-py` in particular has no importer because it is pyvisa's run-time backend (pyvisa loads it when no VISA runtime is found), so it must stay with pyvisa.
- `pytest-asyncio` and `setuptools` are `tooling` and stay.
- `scikit-learn` is imported only by the `test` deployment; rule 1 keeps it in root.
