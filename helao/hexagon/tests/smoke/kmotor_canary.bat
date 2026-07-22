@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Windows canary for the kmotorhex hexagon cut-over: runtime /openapi.json diff.
REM
REM Launches the LEGACY kmotor group and the HEXAGON kmotorhex group in turn,
REM dumps each KMOTOR server's live /openapi.json, and diffs them. An identical
REM route/schema surface proves the hexagon makeActionApp factory produces a
REM byte-parity action server for the kinesis_server (Thorlabs Kinesis Z-motor)
REM cut-over target.
REM
REM OPENAPI-ONLY canary (no runtime golden diff). hispec.yml's KMOTOR block
REM declares a single axis `z`; every action route kinesis_server.py registers
REM under a configured axis -- kmove (commands motion, even a 0.0mm relative
REM move still issues a real move command), cancel_kmove (stops/cancels a move
REM executor), and set_velocity (writes live velocity/acceleration parameters
REM to the device) -- either drives the stage or mutates its hardware state.
REM There is no position/status QUERY action analogous to galil_motion's
REM query_positions (the poller samples position internally via
REM get_lbuf/live_dict, but that is not exposed as a callable action route), so
REM there is no SAFE non-perturbing read action to dispatch as a canary -- and
REM no kmotor_diff.bat runtime counterpart. The openapi diff is the topology-
REM and safety-appropriate parity check (mirrors ni_canary.bat exactly).
REM
REM Why NOT parity_run.sh / harness.capture: that harness is hardcoded to the
REM golden SIM group topology (orch@8001, sim@8002, db@8010) and dispatches
REM sequences to an orchestrator. kmotorhex is a 1-server group (KMOTOR@8015)
REM with NO orchestrator, so the GM-* scenarios cannot drive it.
REM
REM Both configs share root C:\INST_hlo and port 8015, so they MUST run
REM sequentially (this script does that) -- never launch both at once.
REM NOTE: kmotor.yml's simulation:true is cosmetic (banner color) -- Kinesis
REM has no sim/dummy data path. KinesisMotor.connect() opens a real pylablib
REM Thorlabs.KinesisMotor handle per configured axis against `serial_no`; the
REM device must be attached and powered so the server boots and serves
REM /openapi.json (a failed connect() leaves `driver.dev_kinesis` unset, which
REM raises AttributeError when kinesis_dyn_endpoints registers the axis-typed
REM route signatures, so the app never boots at all -- this is why the REAL
REM hispec serial_no/scale params are baked into kmotor.yml/kmotorhex.yml
REM verbatim rather than placeholders).
REM
REM Usage: kmotor_canary.bat [root] [outdir]
REM   root   default C:\INST_hlo   (must match the configs' root: key)
REM   outdir default %TEMP%\kmotor_canary
REM ---------------------------------------------------------------------------

set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\kmotor_canary"

REM Guard: refuse an unsafe root (drive/fs anchor, or a root that contains the
REM code repo) BEFORE anything touches it. safe_root.py is the single choke
REM point; %ROOT% is only ever used read-only in this script, but the check is
REM defense in depth against a mis-set root: key. See safe_root.py.
REM NOTE: `conda` is conda.bat on Windows -- every conda call in this script's
REM own flow MUST be prefixed with `call`, else the parent batch terminates when
REM conda.bat returns (silent exit). Only the conda inside `start ... cmd /c` is
REM exempt (it runs in a separate child shell).
call conda run -n helao python "%~dp0safe_root.py" check "%ROOT%"
if not "%errorlevel%"=="0" (
  echo [canary] ABORT -- root %ROOT% failed the safety guard; see message above
  exit /b 2
)

REM repo root = four levels up from this script (helao\hexagon\tests\smoke\)
pushd "%~dp0..\..\..\.." || exit /b 2
set "REPO=%CD%"

if not exist "%OUTDIR%" mkdir "%OUTDIR%"
set "LEGACY_JSON=%OUTDIR%\kmotor_openapi.json"
set "HEX_JSON=%OUTDIR%\kmotorhex_openapi.json"

call :run_one kmotor     "%LEGACY_JSON%" || goto :fail
call :run_one kmotorhex  "%HEX_JSON%"    || goto :fail

echo.
echo [canary] diffing openapi surfaces
REM Persist diff output to a file too, so the result survives the window closing.
call conda run -n helao python "%~dp0openapi_diff.py" "%LEGACY_JSON%" "%HEX_JSON%" > "%OUTDIR%\openapi_diff.txt" 2>&1
set "DIFF_RC=!errorlevel!"
type "%OUTDIR%\openapi_diff.txt"
popd
echo.
if "%DIFF_RC%"=="0" (
  echo [canary] PASS -- kmotorhex openapi surface matches legacy kmotor> "%OUTDIR%\canary_result.txt"
) else (
  echo [canary] DIFFS FOUND rc=%DIFF_RC% -- see openapi_diff.txt> "%OUTDIR%\canary_result.txt"
)
type "%OUTDIR%\canary_result.txt"
echo [canary] artifacts + result saved in: %OUTDIR%
echo.
REM Keep the window open so the result is readable when double-clicked. `pause`
REM is a no-op if stdin is redirected (non-interactive run), which is fine --
REM the result is also in %OUTDIR%\canary_result.txt regardless.
pause
exit /b %DIFF_RC%

REM ---------------------------------------------------------------------------
:run_one
REM %1 = config prefix, %2 = output json path
set "PREFIX=%~1"
set "OUTJSON=%~2"
set "LAUNCHLOG=%OUTDIR%\%PREFIX%.launch.log"
set "WINTITLE=HELAO_CANARY_%PREFIX%"

echo.
echo [canary] === %PREFIX% ===
REM NEVER wipe %ROOT%. An openapi diff reads the live server's /openapi.json and
REM produces no output tree, so no "fresh root" is needed. On a station %ROOT%
REM (e.g. C:\INST_hlo) holds production RUN data, calibration matrices, and may
REM contain the code repo itself -- deleting it is catastrophic and unrecoverable
REM (rmdir /s /q bypasses the Recycle Bin). %ROOT% is used read-only here, only
REM to locate the pid pickle for kill_group.py.

echo [canary] launching %PREFIX% (log: %LAUNCHLOG%)
REM Pre-launch guard: refuse to launch onto a still-bound HTTP/RPC port. A
REM stale binder from a previous leg or a prior *_canary/_diff run can still
REM own 127.0.0.1:8015 (or its co-located ZMQ RPC sibling 18015); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8015
if not "%errorlevel%"=="0" (
  echo [canary] ABORT %PREFIX% -- ports 8015/18015 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py "%~dp0configs\%PREFIX%.yml" --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [canary] waiting for KMOTOR port 8015
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8015))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [canary] FAIL %PREFIX% port 8015 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [canary] fetching /openapi.json -> %OUTJSON%
call conda run -n helao python -c "import urllib.request,sys; open(sys.argv[2],'wb').write(urllib.request.urlopen('http://127.0.0.1:8015/openapi.json',timeout=30).read())" x "%OUTJSON%"
set "FETCH_RC=!errorlevel!"

echo [canary] killing %PREFIX%
call :kill_one

if not "%FETCH_RC%"=="0" (
  echo [canary] FAIL %PREFIX% openapi fetch rc=%FETCH_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the Kinesis driver's shutdown() runs:
REM KinesisMotor.disconnect() calls kmotor.close() for every configured axis
REM (releases the pylablib handle on the Thorlabs device). A hard kill skips
REM this and may leave the device's USB/serial handle reserved for the next
REM launch -- best-effort (server dies mid-response); then wait.
REM Snapshot the group's PIDs (servers + launch.py monitor) BEFORE the
REM graceful /shutdown, so teardown / a removed pickle can't defeat the
REM kill and the launch.py console window is closed by PID (see kill_group.py).
call conda run -n helao python "%~dp0kill_group.py" "%ROOT%" "%PREFIX%" --snapshot "%TEMP%\helao_pids_%PREFIX%.json"
call conda run -n helao python "%~dp0graceful_shutdown.py" 8015
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python "%~dp0kill_group.py" --from-snapshot "%TEMP%\helao_pids_%PREFIX%.json"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit the canary console.
REM `taskkill /T /F` by window title was removed: /T tree-kills and can cascade
REM through a shared conhost.exe and close the main canary window.
REM The match includes ".yml" so prefix "kmotor" cannot match "kmotorhex".
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py*%PREFIX%.yml*--no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the KMOTOR server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18015) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (kmotor vs kmotorhex) starts while a stale
REM listener still owns 127.0.0.1:18015, the KMOTOR "Address in use" fallback
REM fires AND a dispatch_action RPC-first call would reach the STALE binder --
REM the action is ACK'd but never runs on the live server. Poll both ports
REM until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8015) or c(18015)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :kmotor_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:kmotor_ports_free
if not "!RELEASED!"=="1" echo [canary] WARNING %PREFIX% ports 8015/18015 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [canary] ABORTED -- a launch/fetch step failed; see logs in %OUTDIR%
echo [canary] ABORTED -- see %PREFIX%.launch.log in %OUTDIR%> "%OUTDIR%\canary_result.txt"
pause
exit /b 2
