@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the galil_motion hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL GALIL MOTION CONTROLLER (READ-ONLY QUERY, NO MOTION). ***
REM The galil controller must be POWERED ON and reachable at galil_ip_str
REM before running this script. query_positions (encoder read via TP/PA ?)
REM never issues a motion command -- the stage does NOT move -- but
REM Galil.connect() still needs a live gclib TCP connection to produce any
REM position data; see helao\hexagon\tests\smoke\golden_capture_galil.py's
REM docstring.
REM
REM Launches galilgold (legacy) then galilgoldhex (hexagon), each against a
REM FRESH throwaway root, drives one POST /MOTOR/query_positions per launch
REM via golden_capture_galil.py, snapshots the resulting RUNS tree, and diffs
REM the two captures with harness.parity. Mirrors the conventions already
REM proven in golden_diff.bat (call conda / ping sleeps / cmdline-scoped
REM Stop-Process / persisted results + pause) -- see that script's header for
REM why harness.capture/parity_run.sh cannot drive this orch-less, db-less
REM 2-server topology (no ORCH, no DB -- see golden_capture_galil.py for the
REM RUNS_ACTIVE-only settle this uses instead of quiesce()).
REM
REM Usage: galil_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture
REM            root, fully wiped before EACH capture (see :wipe_caproot).
REM            NEVER point this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\galil_golden -- capture sets + parity report
REM            land here (outdir\galil, outdir\galilhex,
REM            outdir\parity-report.json, outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\galil_golden"
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
call :run_one galilgold    "%OUTDIR%\galil"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one galilgoldhex "%OUTDIR%\galilhex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\galil" --candidate "%OUTDIR%\galilhex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The 'position' hlo column is masked via the capture manifest's
REM masked_hlo_columns (see golden_capture_galil.py) since it is a live
REM encoder reading, not deterministic sim data -- so parity rc=0 is a
REM genuine PASS and rc!=0 means a REAL hexagon-vs-legacy diff. The full
REM report is printed and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- galilhex RUNS-tree matches legacy galil ^(query_positions, masked^)
    echo [golden] artifacts: %OUTDIR%\galil, %OUTDIR%\galilhex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The 'position' hlo column
    echo [golden]   is masked, so anything shown here is a genuine
    echo [golden]   hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\galil, %OUTDIR%\galilhex, %OUTDIR%\parity-report.json
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
REM because golden_capture_galil.py's assert_fresh() refuses a root that
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
REM own 127.0.0.1:8003 (or its co-located ZMQ RPC sibling 18003); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8003
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8003/18003 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for MOTOR port 8003
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8003))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8003 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing query_positions -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_galil --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
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
REM to the controller) and cancels the aligner IO task. A hard kill skips
REM this. Best-effort (server dies mid-response); then wait for release.
REM Snapshot the group's PIDs (servers + launch.py monitor) BEFORE the
REM graceful /shutdown, so teardown / a removed pickle can't defeat the
REM kill and the launch.py console window is closed by PID (see kill_group.py).
call conda run -n helao python "%~dp0kill_group.py" "%CAPROOT%" "%PREFIX%" --snapshot "%TEMP%\helao_pids_%PREFIX%.json"
call conda run -n helao python "%~dp0graceful_shutdown.py" 8003
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python "%~dp0kill_group.py" --from-snapshot "%TEMP%\helao_pids_%PREFIX%.json"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "galilgold" cannot match
REM "galilgoldhex" (no space follows "galilgold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
