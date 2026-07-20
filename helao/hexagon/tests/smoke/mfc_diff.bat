@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the mfc_server hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL ALICAT MFC (TELEMETRY READ, NON-PERTURBING). ***
REM The Alicat mass flow controller must be ATTACHED on COM9 (Windows, pyserial)
REM before running this script. acquire_flowrate is dispatched with
REM flowrate_sccm=None, so the MFC valve is NEVER opened and NO flow is commanded
REM -- it only READS live telemetry and ends by holding the valve CLOSED (safe).
REM AliCatMFC.connect() still needs the live device to buffer any data; see
REM helao\hexagon\tests\smoke\golden_capture_mfc.py's docstring.
REM
REM Launches mfcgold (legacy) then mfcgoldhex (hexagon), each against a FRESH
REM throwaway root, drives one POST /MFC/acquire_flowrate per launch via
REM golden_capture_mfc.py, snapshots the resulting RUNS tree, and diffs the two
REM captures with harness.parity. Mirrors the conventions already proven in
REM galil_diff.bat / golden_diff.bat / spec_diff.bat (call conda / ping sleeps /
REM cmdline-scoped Stop-Process / persisted results + pause) -- see those scripts
REM for why harness.capture/parity_run.sh cannot drive this orch-less, db-less
REM 2-server topology.
REM
REM Usage: mfc_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture root,
REM            fully wiped before EACH capture (see :wipe_caproot). NEVER point
REM            this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\mfc_golden -- capture sets + parity report land
REM            here (outdir\mfc, outdir\mfchex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\mfc_golden"
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
call :run_one mfcgold    "%OUTDIR%\mfc"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one mfcgoldhex "%OUTDIR%\mfchex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\mfc" --candidate "%OUTDIR%\mfchex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The acquire_flowrate .hlo body columns (epoch_s / acquire_time / pressure /
REM temperature / volumetric_flow / mass_flow / setpoint / total flow) are masked
REM via the capture manifest's masked_hlo_columns, and action_params.total_scc
REM (integrated live flow) via masked_meta_keys (see golden_capture_mfc.py), since
REM they are live device readings, not deterministic sim data -- so parity rc=0 is
REM a genuine PASS and rc!=0 means a REAL hexagon-vs-legacy diff. The categorical
REM columns gas / control_point are config-deterministic and compared unmasked.
REM Row counts are poll-paced and compared within hlo_row_count_tolerance. The
REM full report is printed and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- mfcgoldhex RUNS-tree matches legacy mfcgold ^(acquire_flowrate, masked^)
    echo [golden] artifacts: %OUTDIR%\mfc, %OUTDIR%\mfchex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The acquire_flowrate .hlo data
    echo [golden]   columns + total_scc are masked, so anything shown here is a
    echo [golden]   genuine hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\mfc, %OUTDIR%\mfchex, %OUTDIR%\parity-report.json
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
REM because golden_capture_mfc.py's assert_fresh() refuses a root that already
REM contains run artifacts. This rmdir is safe ONLY because %CAPROOT% just
REM passed safe_root.py's check (repo not underneath it, not a drive/fs anchor)
REM AND the equality guard below proves it is not production C:\INST_hlo -- it
REM must NEVER run against a root that could hold real station data (run output,
REM DATABASE, USER_CONFIG).
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
REM own 127.0.0.1:8009 (or its co-located ZMQ RPC sibling 18009); the new
REM server then fails to bind and falls back to the 0.0.0.0 wildcard while the
REM stale binder keeps the loopback port, so the RPC-first action dispatch
REM reaches the STALE binder (ACK'd but never executed) -> a silent capture
REM hang. Wait for both ports to release before launching (mirrors :kill_one).
call conda run -n helao python "%~dp0wait_ports_free.py" 8009
if not "%errorlevel%"=="0" (
  echo [golden] ABORT %PREFIX% -- ports 8009/18009 still bound before launch; kill the stale holder and retry
  exit /b 2
)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for MFC port 8009
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8009))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8009 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing acquire_flowrate -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_mfc --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the Alicat COM port release before the next launch reopens it -- killing
REM the python server does not instantly guarantee pyserial released COM9. ~5s
REM margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the AliCatMFC driver's async_shutdown() runs:
REM it stops polling, closes all valves (safe state -- no gas flow), then closes
REM every serial connection, releasing the COM port for the next launch. A hard
REM kill skips this and may leave COM9 claimed / a valve latched.
REM Best-effort (server dies mid-response); then wait for release.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8009
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%CAPROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "mfcgold" cannot match
REM "mfcgoldhex" (no space follows "mfcgold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the MFC server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18009) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (mfcgold vs mfcgoldhex) -- or a preceding
REM mfc_canary run on the same ports -- leaves a stale listener owning
REM 127.0.0.1:18009, a dispatch_action RPC-first call reaches the STALE binder:
REM the action is ACK'd but never runs on the live server, yielding an empty
REM capture (statuses={}). Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8009) or c(18009)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :mfc_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:mfc_ports_free
if not "!RELEASED!"=="1" echo [golden] WARNING %PREFIX% ports 8009/18009 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
