@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Windows canary for the camhex hexagon cut-over: runtime /openapi.json diff.
REM
REM Launches the LEGACY cam group and the HEXAGON camhex group in turn, dumps
REM each CAM server's live /openapi.json, and diffs them. An identical
REM route/schema surface proves the hexagon makeActionApp factory produces a
REM byte-parity action server for the cam_server (Axis IP webcam) cut-over
REM target.
REM
REM OPENAPI-CANARY ONLY: there is no spec_diff.bat-style runtime golden diff for
REM cam. Its acquire_image action writes per-frame timestamped JPEG files
REM (cam_NNNNNN_<%%y%%m%%d.%%H%%M%%S>.jpg) whose filenames AND binary content
REM both vary run-to-run; the parity harness has no manifest-only lever to
REM normalize a per-frame-timestamped filename in the tree member set
REM (normalize_name collapses only the §5.1 dir/meta timestamp grammar, not
REM arbitrary aux filenames), so a byte-parity runtime diff would need harness
REM code changes. The openapi surface diff fully proves the makeActionApp
REM route/schema factory parity, which is the cut-over gate -- matching the
REM dbpack/analysis openapi-only precedent.
REM
REM Why NOT parity_run.sh / harness.capture: that harness is hardcoded to the
REM golden SIM group topology (orch@8001, sim@8002, db@8010) and dispatches
REM sequences to an orchestrator. camhex is a 2-server group (CAM@8013 +
REM ACTVIS@5001) with NO orchestrator (mirrors galil_canary.bat exactly).
REM
REM Both configs share root C:\INST_hlo and ports 8013/5001, so they MUST run
REM sequentially (this script does that) -- never launch both at once.
REM NOTE: AxisCam.connect() opens no network connection (returns success
REM unconditionally), so this canary boots and serves /openapi.json even without
REM the camera reachable at axis_ip -- a reachable camera is only needed to
REM actually acquire an image, which this canary never does.
REM
REM Usage: cam_canary.bat [root] [outdir]
REM   root   default C:\INST_hlo   (must match the configs' root: key)
REM   outdir default %TEMP%\cam_canary
REM ---------------------------------------------------------------------------

set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=C:\INST_hlo"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\cam_canary"

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
set "LEGACY_JSON=%OUTDIR%\cam_openapi.json"
set "HEX_JSON=%OUTDIR%\camhex_openapi.json"

call :run_one cam     "%LEGACY_JSON%" || goto :fail
call :run_one camhex  "%HEX_JSON%"    || goto :fail

echo.
echo [canary] diffing openapi surfaces
REM Persist diff output to a file too, so the result survives the window closing.
call conda run -n helao python "%~dp0openapi_diff.py" "%LEGACY_JSON%" "%HEX_JSON%" > "%OUTDIR%\openapi_diff.txt" 2>&1
set "DIFF_RC=!errorlevel!"
type "%OUTDIR%\openapi_diff.txt"
popd
echo.
if "%DIFF_RC%"=="0" (
  echo [canary] PASS -- camhex openapi surface matches legacy cam> "%OUTDIR%\canary_result.txt"
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
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [canary] waiting for CAM port 8013
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
REM 0) GRACEFUL shutdown FIRST so the cam driver's shutdown() runs cleanly.
REM AxisCam holds no persistent hardware handle (HTTP-per-frame), but this
REM matches every other canary's kill sequence -- best-effort (server dies
REM mid-response); then wait.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8013
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%ROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit the canary console.
REM `taskkill /T /F` by window title was removed: /T tree-kills and can cascade
REM through a shared conhost.exe and close the main canary window.
REM The match includes " --no-hot-reload" so prefix "cam" cannot match "camhex".
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the CAM server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18013) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (cam vs camhex) starts while a stale listener
REM still owns 127.0.0.1:18013, the next launch's "Address in use" fallback
REM fires and a dispatch_action RPC-first call would reach the STALE binder.
REM (cam is openapi-only so it never dispatches an action, but the wait keeps
REM the kill path uniform and prevents a stale binder leaking into any later
REM run on these ports.) Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8013) or c(18013)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :cam_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:cam_ports_free
if not "!RELEASED!"=="1" echo [canary] WARNING %PREFIX% ports 8013/18013 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [canary] ABORTED -- a launch/fetch step failed; see logs in %OUTDIR%
echo [canary] ABORTED -- see %PREFIX%.launch.log in %OUTDIR%> "%OUTDIR%\canary_result.txt"
pause
exit /b 2
