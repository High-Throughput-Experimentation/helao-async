@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Windows smoke test for launcher orphan containment (helao.helpers.win_job).
REM
REM Launches a group, force-kills the launcher the way a crash or Task Manager
REM would, and asserts that nothing survives: no fast_launcher/bokeh_launcher/
REM reflex_launcher process, and none of the group's ports still LISTENING.
REM
REM WHY THIS EXISTS AT ALL. On Linux each server arms prctl(PR_SET_PDEATHSIG)
REM and dies with its launcher; that path is verified by unit tests plus a live
REM `kill -9` on the golden group. Windows has no PDEATHSIG, so it gets a Job
REM Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE instead: launch.py joins the
REM job and every server it spawns inherits membership, so the kernel terminates
REM the group when the launcher's handle closes. THAT MECHANISM HAS NEVER BEEN
REM CONFIRMED ON WINDOWS -- it was written and unit-tested on Linux against a
REM fake kernel32. This script is how it gets confirmed at a station.
REM
REM The stakes are higher here than a held port: the Windows-only drivers are
REM Galil (gclib) and Gamry (comtypes), and an orphaned Gamry server still owns
REM GamryCOM and the potentiostat, so the next launch cannot acquire the
REM instrument at all.
REM
REM All judgement is in helao.core.tests.win_orphan_check, which is unit-tested
REM on Linux (test_win_orphan_check.py). This file only collects evidence and
REM checks an errorlevel -- deliberately, because a .bat cannot be tested from
REM the development machine.
REM
REM USAGE:  launch_orphan_win.bat [config_prefix] [port ...]
REM         launch_orphan_win.bat                  -> golden, ports 5001 5002 5003
REM         launch_orphan_win.bat clad 5110 5111   -> a station config
REM
REM Run it on a station that is IDLE. It force-kills a launcher and expects the
REM whole group to die; do not run it against a group executing a sequence. It
REM launches its own group and does not touch an existing one -- but the
REM stale-group guard means it will refuse to start if one is already running,
REM which is the correct outcome and is reported as such.
REM ---------------------------------------------------------------------------

REM Repo root, resolved BEFORE any `shift`. This must stay above the argument
REM parsing: SHIFT moves %1 into %0, so %~dp0 read afterwards is the path of an
REM *argument*, not of this script. That bug sent `pushd` to C:\ and the launcher
REM then failed with "can't open file 'launch.py'", which surfaced as the
REM pre-check reporting no group -- a correct message about the wrong cause.
set REPO=%~dp0..\..\..\..
for %%I in ("%REPO%") do set REPO=%%~fI

REM Default to failure. Every success path sets this to 0 explicitly, so an exit
REM route nobody thought about reports FAIL rather than a silent PASS.
set RC=1

set CONFIG=%1
if "%CONFIG%"=="" set CONFIG=golden
if not "%1"=="" shift

set PORTS=
:collect_ports
if "%1"=="" goto ports_done
set PORTS=!PORTS! %1
shift
goto collect_ports
:ports_done
if "!PORTS!"=="" set PORTS= 5001 5002 5003

pushd "%REPO%"
if errorlevel 1 (
    echo FAIL: could not enter the repo root "%REPO%".
    exit /b 1
)
echo     repo root: %REPO%

set OUT=%TEMP%\helao_orphan_smoke
if not exist "%OUT%" mkdir "%OUT%"
set PROCS=%OUT%\procs.txt
set LAUNCHLOG=%OUT%\launch.log

echo [1/5] launching %CONFIG% ...
REM `start` so this script keeps control; the launcher gets its own window, which
REM is also what gives it a real console -- the CTRL_BREAK path in kill_server is
REM only meaningful for a child that has one.
REM
REM Short (8.3) paths for the `cd` target and the redirect, because a redirect
REM inside an already-quoted `cmd /c` string cannot itself be quoted reliably --
REM `cmd /c "... > "%LOG%" 2>&1"` is four quotes and cmd's own de-quoting rules
REM decide what that means. A short path contains no spaces, so it needs no
REM quoting at all. (If 8.3 generation is disabled on the volume, %%~sI returns
REM the long path unchanged; that is still correct for any path without spaces,
REM which both of these are on a station.)
for %%I in ("%REPO%") do set REPOS=%%~sI
for %%I in ("%OUT%") do set OUTS=%%~sI
start "helao-orphan-smoke" /MIN cmd /c "cd /d %REPOS% && python launch.py %CONFIG% > %OUTS%\launch.log 2>&1"

echo [2/5] waiting for a launcher child to appear (up to 180s) ...
REM Polled, not a fixed sleep. A cold start is ~30s on Linux and slower on a
REM station, and a fixed wait either fails a healthy launch or wastes minutes.
set /a TRIES=0
:wait_loop
set /a TRIES+=1
REM No `sleep` on stock Windows; a pingable loopback delay is the usual stand-in.
ping -n 6 127.0.0.1 >nul
call :snapshot_procs
REM Two chained findstr calls, because `findstr "a b"` searches for a OR b --
REM one call would match any python process once the config name appeared
REM anywhere on its line.
findstr /i /c:"_launcher.py" "%PROCS%" | findstr /i /c:"%CONFIG%" >nul 2>&1
if not errorlevel 1 goto group_is_up
if %TRIES% LSS 36 goto wait_loop

echo     FAIL: no launcher child is running for %CONFIG% after 180s.
echo     The group has to be up for this test to mean anything -- a silent bind
echo     failure or a stale-group refusal would otherwise look like a pass.
echo.
echo     ---- last 40 lines of %LAUNCHLOG% ----
REM Printed here rather than left for the operator to find: this is the failure
REM mode that actually happened first, and the cause is always in this log.
if exist "%LAUNCHLOG%" (
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LAUNCHLOG%' -Tail 40" 2>nul
) else (
    echo     [no log file: the launcher never started - check the cwd above]
)
echo     --------------------------------------
goto cleanup

:group_is_up
echo     group is up after ~%TRIES%0s.

echo [3/5] force-killing the launcher (no cooperative shutdown) ...
REM /F is the point: TerminateProcess with no chance to run any teardown, which
REM is what a crash or an End Task looks like. Only the monitor is killed -- the
REM job object is what must take the children with it.
REM PowerShell does the killing itself rather than feeding pids to `taskkill`
REM through `for /f`. Inside a backquoted `for /f`, cmd hands the string to the
REM shell verbatim, so the `^|` that a bare pipe needs elsewhere arrives at
REM PowerShell as a literal caret and it refuses the whole command
REM ("A positional parameter cannot be found that accepts argument '^'"). That
REM failed silently in the sense that mattered: the monitor was never killed, the
REM children were still parented and alive, and the check duly reported them as
REM orphans -- a FAIL that said nothing about the job object.
REM
REM `Stop-Process -Force` is TerminateProcess, the same abrupt kill `taskkill /F`
REM performs, which is the point: no cooperative shutdown.
REM
REM `*launch.py %CONFIG%*` matches only the monitor. A child's command line is
REM `fast_launcher.py <config>`, and "launcher.py" does not contain "launch.py"
REM -- the characters after "launch" are "er.py", not ".py".
REM Restricted to python processes. Matching on the command line alone also hit
REM the `cmd /c` wrapper `start` created -- its own command line contains
REM "launch.py <config>" too -- so the script reported "killing monitor pid" two
REM or three times and it was unclear which process was the launcher. Killing the
REM wrapper is harmless but it is not the thing under test, and the job object
REM belongs to the python process regardless.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*launch.py %CONFIG%*' } | ForEach-Object { Write-Host ('    killing monitor pid ' + $_.ProcessId + ': ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force }"

echo     waiting 20s for the kernel to tear the job down ...
ping -n 21 127.0.0.1 >nul

echo [4/5] collecting evidence ...
call :snapshot_procs
netstat -ano > "%OUT%\netstat_after.txt"

echo [5/5] verdict:
python -m helao.core.tests.win_orphan_check "%PROCS%" "%OUT%\netstat_after.txt" !PORTS! --prefix %CONFIG%
if errorlevel 1 (
    echo.
    echo RESULT: FAIL -- orphan containment is NOT working on this machine.
    echo Evidence in %OUT%
    set RC=1
) else (
    echo.
    echo RESULT: PASS -- the job object terminated the whole group.
    set RC=0
)

:cleanup
REM Belt and braces: if the test failed, the group may still be running and
REM holding hardware. Leave nothing behind either way.
REM Kill the monitor and every child by command line, in one PowerShell call --
REM same reason as above, and it must not be a `for /f`. Note what is NOT
REM sufficient here: `taskkill /F /FI "WINDOWTITLE eq helao-orphan-smoke*"` only
REM reaches the `cmd` wrapper `start` created. Killing that wrapper leaves
REM `python launch.py` running (Windows has no parent-death signal, which is the
REM very gap this test exists for), and the wrapper's death does not close the
REM job handle either -- the job belongs to launch.py, not to cmd. A cleanup that
REM relied on the window title therefore left a live group holding hardware.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*launch.py %CONFIG%*' -or $_.CommandLine -like '*_launcher.py %CONFIG%*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq helao-orphan-smoke*" >nul 2>&1
popd
exit /b %RC%

REM ---------------------------------------------------------------------------
:snapshot_procs
REM Write "<command line> <pid>" per process, pid last -- the shape
REM win_orphan_check.surviving_launchers parses.
REM
REM PowerShell/CIM rather than `wmic`: WMIC is deprecated and is absent on
REM current Windows builds, where it fails silently and leaves an EMPTY file.
REM An empty process list reads as "no launcher survived", which would turn this
REM test into one that always passes. `wmic` is kept only as a fallback for older
REM stations, and is used only when PowerShell produced nothing.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | ForEach-Object { '{0} {1}' -f $_.CommandLine, $_.ProcessId }" > "%PROCS%" 2>nul
for %%S in ("%PROCS%") do if %%~zS GTR 0 goto :eof
wmic process get CommandLine,ProcessId > "%PROCS%" 2>nul
for %%S in ("%PROCS%") do if %%~zS GTR 0 goto :eof
echo     WARNING: could not enumerate processes (neither PowerShell CIM nor wmic
echo     produced output). This check cannot detect orphans on this machine.
goto :eof
