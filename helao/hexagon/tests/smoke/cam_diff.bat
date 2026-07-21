@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the cam_server hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL AXIS WEBCAM (fetches one live JPEG frame). ***
REM The Axis webcam must be REACHABLE at axis_ip before running this script.
REM acquire_image (duration=0) fetches ONE frame; see
REM helao\hexagon\tests\smoke\golden_capture_cam.py's docstring.
REM
REM Launches camgold (legacy) then camgoldhex (hexagon), each against a FRESH
REM throwaway root, drives one POST /CAM/acquire_image per launch via
REM golden_capture_cam.py, snapshots the resulting RUNS tree, and diffs the two
REM captures with harness.parity. Mirrors spec_diff.bat/galil_diff.bat exactly
REM (call conda / ping sleeps / cmdline-scoped Stop-Process / RPC-port-release
REM wait / persisted results + pause).
REM
REM cam's runtime diff is possible because harness.classify.normalize_name has a
REM cam-frame grammar rule (RE_CAM_IMG) that collapses the volatile
REM cam_NNNNNN_<%%y%%m%%d.%%H%%M%%S>.jpg timestamp to cam_NNNNNN_TS.jpg on both
REM sides; the .jpg bytes are content-masked "skip" and the .hlo epoch_s/filename
REM columns are value-masked (see golden_capture_cam.py). Without that rule the
REM two captures' JPEGs would land at different tree members (spurious fail).
REM
REM Usage: cam_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture root,
REM            fully wiped before EACH capture (see :wipe_caproot). NEVER point
REM            this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\cam_golden -- capture sets + parity report land
REM            here (outdir\cam, outdir\camhex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\cam_golden"
set "PROD_ROOT=C:\INST_hlo"

REM NOTE: `conda` is conda.bat on Windows -- every conda call in this script's
REM own flow MUST be prefixed with `call`, else the parent batch terminates when
REM conda.bat returns (silent exit). Only the conda inside `start ... cmd /c` (in
REM :run_one below) is exempt -- it runs in a separate child shell.
call conda run -n helao python "%~dp0safe_root.py" check "%CAPROOT%"
if not "%errorlevel%"=="0" (
  echo [golden] ABORT -- caproot %CAPROOT% failed the safety guard; see message above
  exit /b 2
)
if /I "%CAPROOT%"=="%PROD_ROOT%" (
  echo [golden] ABORT -- caproot equals production root %PROD_ROOT%; refusing to run
  exit /b 2
)

REM repo root = four levels up from this script (helao\hexagon\tests\smoke\)
pushd "%~dp0..\..\..\.." || exit /b 2
set "REPO=%CD%"

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

call :wipe_caproot || goto :fail
call :run_one camgold    "%OUTDIR%\cam"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one camgoldhex "%OUTDIR%\camhex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\cam" --candidate "%OUTDIR%\camhex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The .jpg frame bytes are content-masked "skip" and the .hlo epoch_s/filename
REM columns are value-masked via the capture manifest (see golden_capture_cam.py);
REM the .jpg tree path + -act.yml file_name normalize via the RE_CAM_IMG grammar
REM rule -- so parity rc=0 is a genuine PASS and rc!=0 means a REAL
REM hexagon-vs-legacy diff. The full report is printed and persisted above either
REM way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- camgoldhex RUNS-tree matches legacy camgold ^(acquire_image, masked^)
    echo [golden] artifacts: %OUTDIR%\cam, %OUTDIR%\camhex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The .jpg bytes + .hlo data
    echo [golden]   columns are masked and the frame filename is grammar-
    echo [golden]   normalized, so anything shown here is a genuine
    echo [golden]   hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\cam, %OUTDIR%\camhex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
)
type "%OUTDIR%\golden_result.txt"
echo.
REM Keep the window open so the result is readable when double-clicked. `pause`
REM is a no-op if stdin is redirected (non-interactive run), which is fine --
REM the result is also in %OUTDIR%\golden_result.txt regardless.
pause
exit /b %PARITY_RC%

REM ---------------------------------------------------------------------------
:wipe_caproot
REM Full-wipe the throwaway capture root before each capture -- required because
REM golden_capture_cam.py's assert_fresh() refuses a root that already contains
REM run artifacts. This rmdir is safe ONLY because %CAPROOT% just passed
REM safe_root.py's check (repo not underneath it, not a drive/fs anchor) AND the
REM equality guard below proves it is not production C:\INST_hlo -- it must NEVER
REM run against a root that could hold real station data (run output, DATABASE,
REM USER_CONFIG calibration matrices).
if /I "%CAPROOT%"=="%PROD_ROOT%" (
  echo [golden] ABORT -- refusing to wipe production root %PROD_ROOT%
  exit /b 2
)
call conda run -n helao python "%~dp0safe_root.py" check "%CAPROOT%"
if not "%errorlevel%"=="0" (
  echo [golden] ABORT -- caproot %CAPROOT% failed the safety guard before wipe
  exit /b 2
)
if exist "%CAPROOT%" (
  echo [golden] wiping throwaway caproot %CAPROOT%
  rmdir /s /q "%CAPROOT%"
)
exit /b 0

REM ---------------------------------------------------------------------------
:run_one
REM %1 = config prefix, %2 = capture out dir
set "PREFIX=%~1"
set "CAPOUT=%~2"
set "LAUNCHLOG=%OUTDIR%\%PREFIX%.launch.log"
set "WINTITLE=HELAO_GOLDEN_%PREFIX%"

echo.
echo [golden] === %PREFIX% ===
echo [golden] launching %PREFIX% (log: %LAUNCHLOG%)
REM Pre-launch guard: refuse to launch onto a still-bound HTTP/RPC port. A
REM stale binder from a previous leg or a prior *_canary/_diff run can still
REM own 127.0.0.1:8013 (or its co-located ZMQ RPC sibling 18013); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8013
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8013/18013 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for CAM port 8013
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8013))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8013 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing acquire_image -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_cam --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the cam driver's shutdown() runs cleanly.
REM AxisCam holds no persistent hardware handle (HTTP-per-frame), but this
REM matches every other canary's kill sequence -- best-effort (server dies
REM mid-response); then wait.
REM Snapshot the group's PIDs (servers + launch.py monitor) BEFORE the
REM graceful /shutdown, so teardown / a removed pickle can't defeat the
REM kill and the launch.py console window is closed by PID (see kill_group.py).
call conda run -n helao python "%~dp0kill_group.py" "%CAPROOT%" "%PREFIX%" --snapshot "%TEMP%\helao_pids_%PREFIX%.json"
call conda run -n helao python "%~dp0graceful_shutdown.py" 8013
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python "%~dp0kill_group.py" --from-snapshot "%TEMP%\helao_pids_%PREFIX%.json"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can cascade
REM through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "camgold" cannot match "camgoldhex".
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the CAM server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18013) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (camgold vs camgoldhex) -- or a preceding
REM cam_canary run on the same ports -- leaves a stale listener owning
REM 127.0.0.1:18013, a dispatch_action RPC-first call reaches the STALE binder:
REM the action is ACK'd but never runs on the live server, yielding an empty
REM capture (statuses={}). Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8013) or c(18013)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :cam_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:cam_ports_free
if not "!RELEASED!"=="1" echo [golden] WARNING %PREFIX% ports 8013/18013 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
