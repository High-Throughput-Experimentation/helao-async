@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the tec_server hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL MEERSTETTER TEC CONTROLLER (READ-ONLY TELEMETRY, NO
REM SETPOINT/ENABLE CHANGE). ***
REM The Meerstetter controller must be POWERED ON and reachable at the
REM configured serial `port` (COM5) before running this script. record_tec
REM (TECMonExec) never calls set_temp/enable/disable -- the controller's
REM setpoint and enable state are NOT touched -- but MeerstetterTEC's MeCom
REM session must still be open (lazily, via the poller's first get_data())
REM to produce any real telemetry; see
REM helao\hexagon\tests\smoke\golden_capture_tec.py's docstring.
REM
REM Launches tecgold (legacy) then tecgoldhex (hexagon), each against a FRESH
REM throwaway root, drives one POST /TEC/record_tec per launch via
REM golden_capture_tec.py, snapshots the resulting RUNS tree, and diffs the
REM two captures with harness.parity. Mirrors the conventions already proven
REM in golden_diff.bat / galil_diff.bat (call conda / ping sleeps /
REM cmdline-scoped Stop-Process / persisted results + pause) -- see those
REM scripts' headers for why harness.capture/parity_run.sh cannot drive this
REM orch-less, db-less 2-server topology (no ORCH, no DB -- see
REM golden_capture_tec.py for the RUNS_ACTIVE-only settle this uses instead
REM of quiesce()).
REM
REM Usage: tec_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture
REM            root, fully wiped before EACH capture (see :wipe_caproot).
REM            NEVER point this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\tec_golden -- capture sets + parity report land
REM            here (outdir\tec, outdir\techex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\tec_golden"
set "PROD_ROOT=C:\INST_hlo"

REM NOTE: `conda` is conda.bat on Windows -- every conda call in this script's
REM own flow MUST be prefixed with `call`, else the parent batch terminates
REM when conda.bat returns (silent exit). Only the conda inside
REM `start ... cmd /c` (in :run_one below) is exempt -- it runs in a separate
REM child shell.
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
call :run_one tecgold    "%OUTDIR%\tec"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one tecgoldhex "%OUTDIR%\techex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\tec" --candidate "%OUTDIR%\techex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The tec_vals columns + epoch_s are masked via the capture manifest's
REM masked_hlo_columns (see golden_capture_tec.py) since they are live device
REM readings, not deterministic sim data -- so parity rc=0 is a genuine PASS
REM and rc!=0 means a REAL hexagon-vs-legacy diff. The full report is printed
REM and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- techex RUNS-tree matches legacy tec ^(record_tec, masked^)
    echo [golden] artifacts: %OUTDIR%\tec, %OUTDIR%\techex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The tec_vals + epoch_s
    echo [golden]   columns are masked, so anything shown here is a genuine
    echo [golden]   hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\tec, %OUTDIR%\techex, %OUTDIR%\parity-report.json
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
REM Full-wipe the throwaway capture root before each capture -- required
REM because golden_capture_tec.py's assert_fresh() refuses a root that
REM already contains run artifacts. This rmdir is safe ONLY because
REM %CAPROOT% just passed safe_root.py's check (repo not underneath it, not a
REM drive/fs anchor) AND the equality guard below proves it is not
REM production C:\INST_hlo -- it must NEVER run against a root that could
REM hold real station data (run output, DATABASE, USER_CONFIG calibration
REM matrices).
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
REM own 127.0.0.1:8008 (or its co-located ZMQ RPC sibling 18008); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8008
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8008/18008 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for TEC port 8008
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8008))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8008 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin) -- also gives
REM the poller a moment to complete its first (lazy-connect) get_data() call
REM before golden_capture_tec.py's verify_device_open checks /get_status.
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing record_tec -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_tec --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the MeCom serial session release before the next launch reopens it --
REM killing the python server does not instantly guarantee the OS-level
REM serial port handle is torn down. ~5s margin between our two sequential
REM captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the TEC driver's shutdown() runs:
REM MeerstetterTEC.async_shutdown() disables the control loop (safe state)
REM then closes the MeCom serial session. A hard kill skips this. Best-effort
REM (server dies mid-response); then wait for release.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8008
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%CAPROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "tecgold" cannot match
REM "tecgoldhex" (no space follows "tecgold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
