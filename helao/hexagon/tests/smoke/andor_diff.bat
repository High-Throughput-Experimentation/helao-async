@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the andor_server hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL ANDOR ZYLA CAMERA + ATSPECTROGRAPH (SOFTWARE-TRIGGERED,
REM NON-PERTURBING SPECTRUM STREAM). ***
REM The Andor camera + spectrograph must be ATTACHED (Windows, vendor
REM pyAndorSDK3 / pyAndorSpectrograph runtimes present) before running this
REM script. `acquire` streams a short burst of spectra off the detector -- it
REM drives nothing -- but AndorDriver.connect() still needs the live devices to
REM produce any data; see
REM helao\hexagon\tests\smoke\golden_capture_andor.py's docstring. The capture
REM dispatches external_trigger=False (SOFTWARE trigger) so frames flow without
REM an external 5V TTL source.
REM
REM Launches andorgold (legacy) then andorgoldhex (hexagon), each against a FRESH
REM throwaway root, drives one POST /ANDOR/acquire per launch via
REM golden_capture_andor.py, snapshots the resulting RUNS tree, and diffs the two
REM captures with harness.parity. Mirrors the conventions already proven in
REM spec_diff.bat / co2_diff.bat / galil_diff.bat (call conda / ping sleeps /
REM cmdline-scoped Stop-Process / persisted results + pause) -- see those scripts
REM for why harness.capture/parity_run.sh cannot drive this orch-less, db-less
REM 2-server topology.
REM
REM Usage: andor_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture root,
REM            fully wiped before EACH capture (see :wipe_caproot). NEVER point
REM            this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\andor_golden -- capture sets + parity report land
REM            here (outdir\andor, outdir\andorhex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\andor_golden"
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
call :run_one andorgold    "%OUTDIR%\andor"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one andorgoldhex "%OUTDIR%\andorhex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\andor" --candidate "%OUTDIR%\andorhex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The acquire .hlo body columns (tick_time / ch_NNNN) are masked via the
REM capture manifest's masked_hlo_columns and the row count compared within
REM hlo_row_count_tolerance (poll-paced stream), and the per-run
REM action_params.action_path is masked via masked_meta_keys (see
REM golden_capture_andor.py) -- so parity rc=0 is a genuine PASS and rc!=0 means
REM a REAL hexagon-vs-legacy diff. The .hlo header `wl` (pixel->wavelength table)
REM + column_headings are config-deterministic and compared unmasked. The full
REM report is printed and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- andorgoldhex RUNS-tree matches legacy andorgold ^(acquire, masked^)
    echo [golden] artifacts: %OUTDIR%\andor, %OUTDIR%\andorhex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The acquire .hlo data
    echo [golden]   columns + action_path are masked, so anything shown here is a
    echo [golden]   genuine hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\andor, %OUTDIR%\andorhex, %OUTDIR%\parity-report.json
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
REM because golden_capture_andor.py's assert_fresh() refuses a root that already
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
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for ANDOR port 8011
set "UP=0"
for /l %%i in (1,1,90) do (
  call conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8011))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  REM sleep ~2s via ping; `timeout` errors when stdin is not an interactive console
  ping -n 3 -w 1000 127.0.0.1 >nul
)
:got_port
if not "%UP%"=="1" (
  echo [golden] FAIL %PREFIX% port 8011 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
REM settle ~3s (ping, not timeout, to survive redirected stdin)
ping -n 4 -w 1000 127.0.0.1 >nul

echo [golden] capturing acquire -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_andor --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the Andor camera handle release before the next launch reopens it --
REM killing the python server does not instantly guarantee the vendor SDK
REM released the device. ~5s margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the AndorDriver's shutdown() runs:
REM AndorDriver.shutdown() disconnects the camera (cam.close()), releasing the
REM vendor SDK handle. A hard kill skips this and may leave the device claimed
REM for the next launch. Best-effort (server dies mid-response); then wait.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8011
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%CAPROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "andorgold" cannot match
REM "andorgoldhex" (no space follows "andorgold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the ANDOR server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18011) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (andorgold vs andorgoldhex) -- or a preceding
REM andor_canary run on the same ports -- leaves a stale listener owning
REM 127.0.0.1:18011, a dispatch_action RPC-first call reaches the STALE binder:
REM the action is ACK'd but never runs on the live server, yielding an empty
REM capture (statuses={}). Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8011) or c(18011)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :andor_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:andor_ports_free
if not "!RELEASED!"=="1" echo [golden] WARNING %PREFIX% ports 8011/18011 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
