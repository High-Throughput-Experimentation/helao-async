@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the syringe_server hexagon canary (P3a
REM special-split).
REM
REM *** READS A SOFTWARE VOLUME COUNTER -- NON-PERTURBING, HARDWARE-INDEPENDENT. ***
REM get_present_volume reads the KDS100 driver's software-tracked
REM present_volume_ul attribute (0.0 on a fresh launch) -- it drives NOTHING
REM (no infuse/withdraw, the plunger does not move) and does NOT query the pump
REM over the wire, so this capture is deterministic and produces valid data even
REM with the KD Scientific Legato pump DETACHED. See
REM helao\hexagon\tests\smoke\golden_capture_syringe.py's docstring.
REM
REM Launches syringegold (legacy) then syringegoldhex (hexagon), each against a
REM FRESH throwaway root, drives one POST /WORKSYRINGE/get_present_volume per
REM launch via golden_capture_syringe.py, snapshots the resulting RUNS tree, and
REM diffs the two captures with harness.parity. Mirrors the conventions proven
REM in spec_diff.bat / galil_diff.bat / golden_diff.bat (call conda / ping sleeps
REM / cmdline-scoped Stop-Process / persisted results + pause) -- see those
REM scripts for why harness.capture/parity_run.sh cannot drive this orch-less,
REM db-less 2-server topology.
REM
REM Usage: syringe_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture root,
REM            fully wiped before EACH capture (see :wipe_caproot). NEVER point
REM            this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\syringe_golden -- capture sets + parity report land
REM            here (outdir\syringe, outdir\syringehex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\syringe_golden"
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
call :run_one syringegold    "%OUTDIR%\syringe"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one syringegoldhex "%OUTDIR%\syringehex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\syringe" --candidate "%OUTDIR%\syringehex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM get_present_volume writes a deterministic present_volume_ul (0.0 on a fresh
REM idle pump) into both the -act.yml action_params (_present_volume_ul) and a
REM single .hlo row (present_volume_ul / error_code). NOTHING is masked (see
REM golden_capture_syringe.py) because those values are config-deterministic, NOT
REM live device readings -- so parity rc=0 is a genuine PASS and ANY diff shown
REM is a REAL hexagon-vs-legacy difference. The full report is printed and
REM persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- syringegoldhex RUNS-tree matches legacy syringegold ^(get_present_volume, unmasked^)
    echo [golden] artifacts: %OUTDIR%\syringe, %OUTDIR%\syringehex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The get_present_volume values
    echo [golden]   are UNMASKED and deterministic, so anything shown here is a
    echo [golden]   genuine hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\syringe, %OUTDIR%\syringehex, %OUTDIR%\parity-report.json
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
REM because golden_capture_syringe.py's assert_fresh() refuses a root that
REM already contains run artifacts. This rmdir is safe ONLY because %CAPROOT%
REM just passed safe_root.py's check (repo not underneath it, not a drive/fs
REM anchor) AND the equality guard below proves it is not production
REM C:\INST_hlo -- it must NEVER run against a root that could hold real station
REM data (run output, DATABASE, USER_CONFIG).
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
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py "%~dp0configs\%PREFIX%.yml" --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [golden] waiting for WORKSYRINGE port 8013
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

echo [golden] capturing get_present_volume -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_syringe --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the KDS100 serial port release before the next launch reopens it --
REM killing the python server does not instantly guarantee the OS freed COM5.
REM ~5s margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the KDS100 driver's async_shutdown() runs:
REM async_shutdown() returns the pump to a safe idle state and closes the
REM pyserial COM5 handle. A hard kill skips this and may leave the serial port
REM claimed for the next launch. Best-effort (server dies mid-response); then
REM wait for release.
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
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes ".yml" so "syringegold" cannot match
REM "syringegoldhex" ("syringegold.yml" is a distinct filename, so no collision).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py*%PREFIX%.yml*--no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM 3) WAIT for the WORKSYRINGE server's HTTP + co-located ZMQ RPC ports (RPC =
REM HTTP+10000 = 18013) to actually RELEASE before returning. The RPC listener
REM is a thread inside the server process and lives as long as the process does;
REM if the next sequential launch (syringegold vs syringegoldhex) -- or a
REM preceding syringe_canary run on the same ports -- leaves a stale listener
REM owning 127.0.0.1:18013, a dispatch_action RPC-first call reaches the STALE
REM binder: the action is ACK'd but never runs on the live server, yielding an
REM empty capture (statuses={}). Poll both ports until free (~30s cap).
set "RELEASED=0"
for /l %%i in (1,1,30) do (
  call conda run -n helao python -c "import socket,sys; c=lambda p: socket.socket().connect_ex(('127.0.0.1',p))==0; sys.exit(1 if (c(8013) or c(18013)) else 0)" 2>nul
  if !errorlevel! equ 0 ( set "RELEASED=1" & goto :syringe_ports_free )
  ping -n 2 -w 1000 127.0.0.1 >nul
)
:syringe_ports_free
if not "!RELEASED!"=="1" echo [golden] WARNING %PREFIX% ports 8013/18013 still bound after wait -- next launch may hit a stale RPC binder
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
