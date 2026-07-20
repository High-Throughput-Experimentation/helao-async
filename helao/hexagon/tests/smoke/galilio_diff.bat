@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the galil_io hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL GALIL IO CONTROLLER (READ-ONLY DIGITAL INPUT, NO
REM ACTUATION). *** The galil controller must be POWERED ON and reachable at
REM galil_ip_str before running this script. get_digital_in (digital input
REM read via MG @IN[n]) never writes to any dev_do output -- no pump, valve,
REM or LED is actuated -- but Galil.connect() still needs a live gclib TCP
REM connection to produce any reading at all (and, per galil_io.py's
REM endpoint gating, for the /IO/get_digital_in route to even exist); see
REM helao\hexagon\tests\smoke\golden_capture_galil_io.py's docstring.
REM
REM Launches galiliogold (legacy) then galiliogoldhex (hexagon), each against
REM a FRESH throwaway root, drives one POST /IO/get_digital_in per launch via
REM golden_capture_galil_io.py, snapshots the resulting RUNS tree, and diffs
REM the two captures with harness.parity. Mirrors the conventions already
REM proven in galil_diff.bat (call conda / ping sleeps / cmdline-scoped
REM Stop-Process / persisted results + pause) -- see that script's header for
REM why harness.capture/parity_run.sh cannot drive this orch-less, db-less
REM 2-server topology (no ORCH, no DB -- see golden_capture_galil_io.py for
REM the RUNS_ACTIVE-only settle this uses instead of quiesce()).
REM
REM Usage: galilio_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture
REM            root, fully wiped before EACH capture (see :wipe_caproot).
REM            NEVER point this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\galilio_golden -- capture sets + parity report
REM            land here (outdir\galilio, outdir\galiliohex,
REM            outdir\parity-report.json, outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\galilio_golden"
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
call :run_one galiliogold    "%OUTDIR%\galilio"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one galiliogoldhex "%OUTDIR%\galiliohex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\galilio" --candidate "%OUTDIR%\galiliohex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The 'value' hlo column is masked via the capture manifest's
REM masked_hlo_columns (see golden_capture_galil_io.py) since it is a live
REM digital-input reading, not deterministic sim data -- so parity rc=0 is a
REM genuine PASS and rc!=0 means a REAL hexagon-vs-legacy diff. The full
REM report is printed and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- galiliohex RUNS-tree matches legacy galilio ^(get_digital_in, masked^)
    echo [golden] artifacts: %OUTDIR%\galilio, %OUTDIR%\galiliohex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The 'value' hlo column
    echo [golden]   is masked, so anything shown here is a genuine
    echo [golden]   hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\galilio, %OUTDIR%\galiliohex, %OUTDIR%\parity-report.json
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
REM because golden_capture_galil_io.py's assert_fresh() refuses a root that
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
REM own 127.0.0.1:8005 (or its co-located ZMQ RPC sibling 18005); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8005
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8005/18005 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for IO port 8005
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8005))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8005 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing get_digital_in -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_galil_io --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the gclib TCP connection release before the next launch reopens it --
REM killing the python server does not instantly guarantee the controller-side
REM socket is torn down. ~5s margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the galil driver's shutdown() runs:
REM Galil.shutdown() calls self.g.GClose() (releases the gclib TCP connection
REM to the controller). A hard kill skips this. Best-effort (server dies
REM mid-response); then wait for release.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8005
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%CAPROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "galiliogold" cannot match
REM "galiliogoldhex" (no space follows "galiliogold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
