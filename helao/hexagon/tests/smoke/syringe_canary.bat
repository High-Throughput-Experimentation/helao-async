@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Windows canary for the syringehex hexagon cut-over: runtime /openapi.json
REM diff.
REM
REM Launches the LEGACY syringe group and the HEXAGON syringehex group in turn,
REM dumps each WORKSYRINGE server's live /openapi.json, and diffs them. An
REM identical route/schema surface proves the hexagon makeActionApp factory
REM produces a byte-parity action server for the syringe_server (KD Scientific
REM Legato syringe pump) cut-over target.
REM
REM Why NOT parity_run.sh / harness.capture: that harness is hardcoded to the
REM golden SIM group topology (orch@8001, sim@8002, db@8010) and dispatches
REM sequences to an orchestrator. syringehex is a 1-server group
REM (WORKSYRINGE@8013) with NO orchestrator, so the GM-* scenarios cannot
REM drive it. The openapi diff is the topology-appropriate parity check
REM (mirrors spec_canary.bat / galil_canary.bat / gamryhex_canary.bat exactly).
REM See syringe_diff.bat for the runtime get_present_volume golden diff, the
REM topology-appropriate DATA check.
REM
REM Both configs share root C:\INST_hlo and port 8013, so they MUST run
REM sequentially (this script does that) -- never launch both at once.
REM NOTE: syringe.yml's simulation:true is cosmetic (banner color) -- KDS100 has
REM no sim/dummy driver swap. KDS100.connect() opens the pyserial COM5 port at
REM startup, but it CATCHES a connect failure (no raise), so the server boots
REM and serves /openapi.json even with the pump detached (the openapi surface is
REM built from the registered routes, independent of the serial connection). A
REM data-producing action additionally does NOT require the pump (see
REM syringe_diff.bat) because get_present_volume reads a software counter.
REM
REM Usage: syringe_canary.bat [root] [outdir]
REM   root   default C:\INST_hlo   (must match the configs' root: key)
REM   outdir default %TEMP%\syringe_canary
REM ---------------------------------------------------------------------------

set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\syringe_canary"

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
set "LEGACY_JSON=%OUTDIR%\syringe_openapi.json"
set "HEX_JSON=%OUTDIR%\syringehex_openapi.json"

call :run_one syringe     "%LEGACY_JSON%" || goto :fail
call :run_one syringehex  "%HEX_JSON%"    || goto :fail

echo.
echo [canary] diffing openapi surfaces
REM Persist diff output to a file too, so the result survives the window closing.
call conda run -n helao python "%~dp0openapi_diff.py" "%LEGACY_JSON%" "%HEX_JSON%" > "%OUTDIR%\openapi_diff.txt" 2>&1
set "DIFF_RC=!errorlevel!"
type "%OUTDIR%\openapi_diff.txt"
popd
echo.
if "%DIFF_RC%"=="0" (
  echo [canary] PASS -- syringehex openapi surface matches legacy syringe> "%OUTDIR%\canary_result.txt"
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
REM (e.g. C:\INST_hlo) holds production RUN data and may contain the code repo
REM itself -- deleting it is catastrophic and unrecoverable (rmdir /s /q bypasses
REM the Recycle Bin). %ROOT% is used read-only here, only to locate the pid
REM pickle for kill_group.py.

echo [canary] launching %PREFIX% (log: %LAUNCHLOG%)
REM Pre-launch guard: refuse to launch onto a still-bound HTTP/RPC port. A
REM stale binder from a previous leg or a prior *_canary/_diff run can still
REM own 127.0.0.1:8013 (or its co-located ZMQ RPC sibling 18013); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8013
if not "%errorlevel%"=="0" (
  echo [canary] ABORT %PREFIX% -- ports 8013/18013 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py "%~dp0configs\%PREFIX%.yml" --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [canary] waiting for WORKSYRINGE port 8013
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8013))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [canary] FAIL %PREFIX% port 8013 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [canary] fetching /openapi.json -> %OUTJSON%
call conda run -n helao python -c "import urllib.request,sys; open(sys.argv[2],'wb').write(urllib.request.urlopen('http://127.0.0.1:8013/openapi.json',timeout=30).read())" x "%OUTJSON%"
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
REM 0) GRACEFUL shutdown FIRST so the KDS100 driver's async_shutdown() runs:
REM async_shutdown() returns the pump to a safe idle state and closes the
REM pyserial COM5 handle. A hard kill skips this and may leave the serial port
REM claimed for the next launch -- best-effort (server dies mid-response); then
REM wait.
REM Snapshot the group's PIDs (servers + launch.py monitor) BEFORE the
REM graceful /shutdown, so teardown / a removed pickle can't defeat the
REM kill and the launch.py console window is closed by PID (see kill_group.py).
call conda run -n helao python "%~dp0kill_group.py" "%ROOT%" "%PREFIX%" --snapshot "%TEMP%\helao_pids_%PREFIX%.json"
call conda run -n helao python "%~dp0graceful_shutdown.py" 8013
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python "%~dp0kill_group.py" --from-snapshot "%TEMP%\helao_pids_%PREFIX%.json"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit the canary console.
REM `taskkill /T /F` by window title was removed: /T tree-kills and can cascade
REM through a shared conhost.exe and close the main canary window.
REM The match includes ".yml" so prefix "syringe" cannot match
REM "syringehex" ("syringe.yml" is a distinct filename, so no collision).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py*%PREFIX%.yml*--no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the WORKSYRINGE server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18013) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (syringe vs syringehex) starts while a stale
REM listener still owns 127.0.0.1:18013, the WORKSYRINGE "Address in use"
REM fallback fires AND a dispatch_action RPC-first call would reach the STALE
REM binder -- the action is ACK'd but never runs on the live server, yielding an
REM empty capture (statuses={}). Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8013) or c(18013)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :syringe_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:syringe_ports_free
if not "!RELEASED!"=="1" echo [canary] WARNING %PREFIX% ports 8013/18013 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [canary] ABORTED -- a launch/fetch step failed; see logs in %OUTDIR%
echo [canary] ABORTED -- see %PREFIX%.launch.log in %OUTDIR%> "%OUTDIR%\canary_result.txt"
pause
exit /b 2
