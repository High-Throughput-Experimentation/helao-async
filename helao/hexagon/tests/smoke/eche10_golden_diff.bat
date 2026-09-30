@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Station golden diff for eche10_hex: the legacy-layout run on the freeze
REM branch against the same sequence on the unified-layout branch under test.
REM Steps 1 and 6 of docs\superpowers\notes\2026-08-15-B5-station-gate-runbook.md.
REM
REM Usage:
REM   eche10_golden_diff.bat capture pre  SEQNAME [goldens]
REM   eche10_golden_diff.bat capture post SEQNAME [goldens]
REM   eche10_golden_diff.bat diff [goldens]
REM     SEQNAME       the sequence directory name, e.g. 131415__GMTEST__golden
REM                   (no .zip, no path; found under RUNS, DIAG, RUNS_FINISHED,
REM                   RUNS_SYNCED, RUNS_NOSYNC, RUNS_DIAG)
REM     goldens       default C:\INST_hlo_goldens\eche10 -- holds pre, post,
REM                   parity-report.json and golden_result.txt
REM   Production root is C:\INST_hlo\DATA and config prefix is eche10_hex; edit
REM   the two set lines below to change either.
REM
REM Workflow, in this order:
REM  (a) Copy this file and station_golden_capture.py out of the repo, to the
REM      same folder anywhere, so capture still works on a checkout that lacks
REM      them; or switch back to feat/parity-legacy-layout-remap to run capture.
REM      capture uses only the python standard library.
REM  (b) PRE: check out freeze/pre-legacy-removal_2608, launch eche10_hex, run
REM      the station smoke sequence, and let it fully drain and sync with SYNC
REM      idle. Then: eche10_golden_diff.bat capture pre SEQNAME
REM      capture refuses a sequence still under RUNS_ACTIVE.
REM  (c) POST: check out the branch under test, launch, run the same sequence
REM      on the same hardware, drain, sync. Then:
REM      eche10_golden_diff.bat capture post SEQNAME
REM  (d) DIFF: check out feat/parity-legacy-layout-remap, and run
REM      eche10_golden_diff.bat diff
REM      from that checkout's copy of this script. The legacy-layout flag is
REM      added automatically when pre holds a legacy RUNS_* tree.
REM
REM capture only READS the production root; every write goes under goldens.
REM Results are also saved to goldens\capture_pre.txt, capture_post.txt and
REM golden_result.txt.
REM ---------------------------------------------------------------------------

set "ROOT=C:\INST_hlo\DATA"
set "PREFIX=eche10_hex"
set "DEFAULT_GOLDENS=C:\INST_hlo_goldens\eche10"

if /I "%~1"=="capture" goto :do_capture
if /I "%~1"=="diff" goto :do_diff
goto :usage

REM ---------------------------------------------------------------------------
:usage
echo Usage: %~nx0 capture pre^|post ^<seq dir name^> [goldens]
echo        %~nx0 diff [goldens]
echo See the comment block at the top of this file for the workflow.
pause
exit /b 2

REM ---------------------------------------------------------------------------
:do_capture
set "WHICH=%~2"
set "SEQ=%~3"
set "GOLDENS=%~4"
if "%GOLDENS%"=="" set "GOLDENS=%DEFAULT_GOLDENS%"
REM absolute path first, so the guard below sees the real location
for %%I in ("%GOLDENS%") do set "GOLDENS=%%~fI"
if /I "%WHICH%"=="pre" goto :which_ok
if /I "%WHICH%"=="post" goto :which_ok
goto :usage
:which_ok
if "%SEQ%"=="" goto :usage

REM Never write under the production root: refuse a goldens path containing it.
set "STRIPPED=!GOLDENS:%ROOT%=!"
if not "!STRIPPED!"=="%GOLDENS%" (
  echo [golden] ABORT -- goldens dir %GOLDENS% is under the production root %ROOT%
  pause
  exit /b 2
)

if not exist "%GOLDENS%" mkdir "%GOLDENS%"
set "OUT=%GOLDENS%\%WHICH%"
set "CAPLOG=%GOLDENS%\capture_%WHICH%.txt"

REM NOTE: `conda` is conda.bat on Windows -- every conda call MUST be prefixed
REM with `call`, else this batch terminates when conda.bat returns.
echo [golden] capturing %SEQ% from %ROOT% -^> %OUT%
call conda run -n helao python "%~dp0station_golden_capture.py" --root "%ROOT%" --seq "%SEQ%" --out "%OUT%" --config-prefix %PREFIX% > "%CAPLOG%" 2>&1
set "CAPTURE_RC=!errorlevel!"
type "%CAPLOG%"
echo.
if "%CAPTURE_RC%"=="0" (
  echo [golden] capture %WHICH% OK -- %OUT%
) else (
  echo [golden] capture %WHICH% FAILED rc=%CAPTURE_RC% -- see the message above, saved in %CAPLOG%
)
pause
exit /b %CAPTURE_RC%

REM ---------------------------------------------------------------------------
:do_diff
set "GOLDENS=%~2"
if "%GOLDENS%"=="" set "GOLDENS=%DEFAULT_GOLDENS%"
REM absolute path, so the pushd below cannot change what it means
for %%I in ("%GOLDENS%") do set "GOLDENS=%%~fI"

if not exist "%GOLDENS%\pre\provenance.yml" (
  echo [golden] ABORT -- no %GOLDENS%\pre\provenance.yml; run capture pre first
  pause
  exit /b 2
)
if not exist "%GOLDENS%\post\provenance.yml" (
  echo [golden] ABORT -- no %GOLDENS%\post\provenance.yml; run capture post first
  pause
  exit /b 2
)

REM repo root = four levels up from this script (helao\hexagon\tests\smoke\)
pushd "%~dp0..\..\..\.." || exit /b 2

set "HELPLOG=%GOLDENS%\parity_help.txt"
call conda run -n helao python -m harness.parity --help > "%HELPLOG%" 2>&1
findstr /C:"--remap-legacy-layout" "%HELPLOG%" >nul
if errorlevel 1 (
  popd
  echo [golden] ABORT -- harness.parity here lacks --remap-legacy-layout: run diff from the feat/parity-legacy-layout-remap checkout
  pause
  exit /b 2
)

REM Remap only when the pre golden is in the legacy layout.
set "REMAP="
for %%D in (RUNS_FINISHED RUNS_SYNCED RUNS_NOSYNC RUNS_DIAG) do if exist "%GOLDENS%\pre\root\%%D\" set "REMAP=--remap-legacy-layout"
echo [golden] running parity diff !REMAP!
REM a stale report from an earlier run must not pass for this run's
if exist "%GOLDENS%\parity-report.json" del /q "%GOLDENS%\parity-report.json"
call conda run -n helao python -m harness.parity --golden "%GOLDENS%\pre" --candidate "%GOLDENS%\post" --report "%GOLDENS%\parity-report.json" !REMAP! > "%GOLDENS%\parity_stdout.txt" 2>&1
set "PARITY_RC=!errorlevel!"
popd
type "%GOLDENS%\parity_stdout.txt"

echo.
echo [golden] full parity report (also saved to %GOLDENS%\parity-report.json):
if exist "%GOLDENS%\parity-report.json" type "%GOLDENS%\parity-report.json"

echo.
if "%PARITY_RC%"=="0" (
  (
    echo [golden] PASS -- post matches pre for eche10_hex
    echo [golden] artifacts: %GOLDENS%\pre, %GOLDENS%\post, %GOLDENS%\parity-report.json
  ) > "%GOLDENS%\golden_result.txt"
) else if not exist "%GOLDENS%\parity-report.json" (
  echo [golden] CRASHED rc=%PARITY_RC% -- no report; see parity_stdout.txt> "%GOLDENS%\golden_result.txt"
) else (
  (
    echo [golden] FAIL rc=%PARITY_RC% -- rc 1 is a real diff, rc 2 is a usage or golden-set error
    echo [golden] open %GOLDENS%\parity-report.json: tree_diffs / file_diffs list each differing member and key
    echo [golden] artifacts: %GOLDENS%\pre, %GOLDENS%\post, %GOLDENS%\parity-report.json
  ) > "%GOLDENS%\golden_result.txt"
)
type "%GOLDENS%\golden_result.txt"
echo.
REM Keep the window open so the result is readable when double-clicked. `pause`
REM is a no-op if stdin is redirected; the result is in golden_result.txt anyway.
pause
exit /b %PARITY_RC%
