@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the gamry hexagon canary (P3a special-split).
REM
REM *** DRIVES THE REAL POTENTIOSTAT. THIS IS NOT A SIMULATION. ***
REM ATTACH A DUMMY CELL / CALIBRATION RESISTOR to the potentiostat BEFORE
REM running this script. run_OCV (open-circuit monitoring, CellMon) never
REM actively drives the cell, but GamryDriver has no sim/dummy data path --
REM see helao\hexagon\tests\smoke\golden_capture.py's docstring -- every run
REM makes real GamryCOM calls and needs a live device to produce any data.
REM
REM Launches gamrygold (legacy) then gamrygoldhex (hexagon), each against a
REM FRESH throwaway root, drives one POST /PSTAT/run_OCV per launch via
REM golden_capture.py, snapshots the resulting RUNS tree, and diffs the two
REM captures with harness.parity. Mirrors the conventions already proven in
REM gamryhex_canary.bat (call conda / ping sleeps / cmdline-scoped
REM Stop-Process / persisted results + pause) -- see that script's header for
REM why harness.capture/parity_run.sh cannot drive this orch-less, db-less
REM 2-server topology (no ORCH, no DB -- see golden_capture.py for the
REM RUNS_ACTIVE-only settle this uses instead of quiesce()).
REM
REM Usage: golden_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture
REM            root, fully wiped before EACH capture (see :wipe_caproot).
REM            NEVER point this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\gamry_golden -- capture sets + parity report
REM            land here (outdir\gamry, outdir\gamryhex,
REM            outdir\parity-report.json, outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\gamry_golden"
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
call :run_one gamrygold    "%OUTDIR%\gamry"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one gamrygoldhex "%OUTDIR%\gamryhex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\gamry" --candidate "%OUTDIR%\gamryhex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The data-derived run_OCV -act.yml action_params (t_s__mean_final,
REM Ewe_V__mean_final, has_bubble) are masked via the capture manifest's
REM masked_meta_keys (see golden_capture.py), so parity rc=0 is a genuine PASS
REM and rc!=0 means a REAL hexagon-vs-legacy diff. The full report is printed
REM and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- gamryhex RUNS-tree matches legacy gamry ^(run_OCV, masked^)
    echo [golden] artifacts: %OUTDIR%\gamry, %OUTDIR%\gamryhex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The three data-derived
    echo [golden]   run_OCV action_params keys are masked, so anything shown
    echo [golden]   here is a genuine hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\gamry, %OUTDIR%\gamryhex, %OUTDIR%\parity-report.json
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
REM because golden_capture.py's assert_fresh() refuses a root that already
REM contains run artifacts. This rmdir is safe ONLY because %CAPROOT% just
REM passed safe_root.py's check (repo not underneath it, not a drive/fs
REM anchor) AND the equality guard below proves it is not production
REM C:\INST_hlo -- it must NEVER run against a root that could hold real
REM station data (run output, DATABASE, USER_CONFIG calibration matrices).
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
REM own 127.0.0.1:8001 (or its co-located ZMQ RPC sibling 18001); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8001
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8001/18001 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for PSTAT port 8001
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8001))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8001 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing run_OCV -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the exclusive GamryCOM device handle release before the next launch
REM opens dev_id again -- killing the python server does not instantly free the
REM out-of-process GamryCOM lock ('CGamryPstat - In use by another script').
REM ~5s margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the gamry driver's shutdown() runs:
REM disconnect() closes the pstat (releases the exclusive GamryCOM device) and
REM kill_gamrycom() terminates GamryCOM.exe. A hard kill skips this and LEAKS
REM the device lock -> the next launch fails 'CGamryPstat - In use by another
REM script'. Best-effort (server dies mid-response); then wait for release.
REM Snapshot the group's PIDs (servers + launch.py monitor) BEFORE the
REM graceful /shutdown, so teardown / a removed pickle can't defeat the
REM kill and the launch.py console window is closed by PID (see kill_group.py).
call conda run -n helao python "%~dp0kill_group.py" "%CAPROOT%" "%PREFIX%" --snapshot "%TEMP%\helao_pids_%PREFIX%.json"
call conda run -n helao python "%~dp0graceful_shutdown.py" 8001
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python "%~dp0kill_group.py" --from-snapshot "%TEMP%\helao_pids_%PREFIX%.json"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "gamrygold" cannot match
REM "gamrygoldhex" (no space follows "gamrygold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
