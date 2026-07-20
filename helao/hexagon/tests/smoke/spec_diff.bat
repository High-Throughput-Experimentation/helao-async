@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Runtime golden-diff driver for the spec_server hexagon canary (P3a
REM special-split).
REM
REM *** DRIVES THE REAL SM303 SPECTROMETER (SINGLE READ, NON-PERTURBING). ***
REM The SM303 spectrometer must be ATTACHED (Windows, vendor SPdbUSBm.dll
REM present) before running this script. acquire_spec reads ONE spectrum off the
REM detector -- it drives nothing -- but SM303.connect() still needs the live
REM device to produce any data; see
REM helao\hexagon\tests\smoke\golden_capture_spec.py's docstring.
REM
REM Launches specgold (legacy) then specgoldhex (hexagon), each against a FRESH
REM throwaway root, drives one POST /SPEC/acquire_spec per launch via
REM golden_capture_spec.py, snapshots the resulting RUNS tree, and diffs the two
REM captures with harness.parity. Mirrors the conventions already proven in
REM galil_diff.bat/golden_diff.bat (call conda / ping sleeps / cmdline-scoped
REM Stop-Process / persisted results + pause) -- see those scripts for why
REM harness.capture/parity_run.sh cannot drive this orch-less, db-less 2-server
REM topology.
REM
REM Usage: spec_diff.bat [caproot] [outdir]
REM   caproot default C:\INST_hlo_golden -- a DEDICATED THROWAWAY capture root,
REM            fully wiped before EACH capture (see :wipe_caproot). NEVER point
REM            this at C:\INST_hlo or any root holding real data.
REM   outdir  default %TEMP%\spec_golden -- capture sets + parity report land
REM            here (outdir\spec, outdir\spechex, outdir\parity-report.json,
REM            outdir\golden_result.txt).
REM ---------------------------------------------------------------------------

set "CAPROOT=%~1"
if "%CAPROOT%"=="" set "CAPROOT=C:\INST_hlo_golden"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\spec_golden"
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
call :run_one specgold    "%OUTDIR%\spec"    || goto :fail
call :wipe_caproot || goto :fail
call :run_one specgoldhex "%OUTDIR%\spechex" || goto :fail

echo.
echo [golden] running parity diff
call conda run -n helao python -m harness.parity --golden "%OUTDIR%\spec" --candidate "%OUTDIR%\spechex" --report "%OUTDIR%\parity-report.json" > "%OUTDIR%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
type "%OUTDIR%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %OUTDIR%\parity-report.json):
type "%OUTDIR%\parity-report.json"

popd
echo.
REM The acquire_spec .hlo body columns (epoch_s / ch_NNNN / error_code /
REM peak_intensity) are masked via the capture manifest's masked_hlo_columns
REM (see golden_capture_spec.py) since they are live detector readings, not
REM deterministic sim data -- so parity rc=0 is a genuine PASS and rc!=0 means a
REM REAL hexagon-vs-legacy diff. The .hlo header `wl` (pixel->wavelength table)
REM is config-deterministic and compared unmasked. The full report is printed
REM and persisted above either way for inspection.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- specgoldhex RUNS-tree matches legacy specgold ^(acquire_spec, masked^)
    echo [golden] artifacts: %OUTDIR%\spec, %OUTDIR%\spechex, %OUTDIR%\parity-report.json
  ) > "%OUTDIR%\golden_result.txt"
) else (
  (
    echo [golden] DIFFS FOUND rc=%PARITY_RC% -- REAL regression, inspect the report
    echo [golden] open %OUTDIR%\parity-report.json: tree_diffs / file_diffs list
    echo [golden]   every differing member and key. The acquire_spec .hlo data
    echo [golden]   columns are masked, so anything shown here is a genuine
    echo [golden]   hexagon-vs-legacy difference.
    echo [golden] artifacts: %OUTDIR%\spec, %OUTDIR%\spechex, %OUTDIR%\parity-report.json
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
REM because golden_capture_spec.py's assert_fresh() refuses a root that already
REM contains run artifacts. This rmdir is safe ONLY because %CAPROOT% just
REM passed safe_root.py's check (repo not underneath it, not a drive/fs anchor)
REM AND the equality guard below proves it is not production C:\INST_hlo -- it
REM must NEVER run against a root that could hold real station data (run output,
REM DATABASE, USER_CONFIG calibration matrices).
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

echo [golden] waiting for SPEC port 8011
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

echo [golden] capturing acquire_spec -^> %CAPOUT%
call conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_spec --config-prefix %PREFIX% --root "%CAPROOT%" --out "%CAPOUT%" > "%OUTDIR%\%PREFIX%.capture.log" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%OUTDIR%\%PREFIX%.capture.log"

echo [golden] killing %PREFIX%
call :kill_one
REM Let the SM303 device handle release before the next launch reopens it --
REM killing the python server does not instantly guarantee the vendor DLL
REM released the device. ~5s margin between our two sequential captures.
ping -n 6 -w 1000 127.0.0.1 >nul

if not "%CAPTURE_RC%"=="0" (
  echo [golden] FAIL %PREFIX% capture rc=%CAPTURE_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
REM 0) GRACEFUL shutdown FIRST so the SM303 driver's shutdown() runs:
REM SM303.shutdown() releases the vendor SPdbUSBm.dll device handle. A hard kill
REM skips this and may leave the device claimed for the next launch.
REM Best-effort (server dies mid-response); then wait for release.
call conda run -n helao python "%~dp0graceful_shutdown.py" 8011
ping -n 5 -w 1000 127.0.0.1 >nul
REM 1) kill the action/vis servers via their pid pickle (any that didn't exit).
call conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%CAPROOT%" "%PREFIX%"
REM 2) kill the launch.py monitor (+ its conda/cmd wrapper) for THIS prefix by
REM matching its command line -- precise, so it can never hit this console.
REM `taskkill /T /F` by window title is NEVER used: /T tree-kills and can
REM cascade through a shared conhost.exe and close the main window.
REM The match includes " --no-hot-reload" so "specgold" cannot match
REM "specgoldhex" (no space follows "specgold" in that cmdline).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %PREFIX% --no-hot-reload*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [golden] ABORTED -- a launch/capture step failed; see logs in %OUTDIR%
echo [golden] ABORTED -- see %OUTDIR%\*.launch.log / *.capture.log> "%OUTDIR%\golden_result.txt"
pause
exit /b 2
