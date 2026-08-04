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
REM and dies with its launcher; that path is verified in CI-able unit tests plus
REM a live `kill -9` on the golden group. Windows has no PDEATHSIG, so it gets a
REM Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE instead: launch.py joins
REM the job and every server it spawns inherits membership, so the kernel
REM terminates the group when the launcher's handle closes. THAT MECHANISM HAS
REM NEVER BEEN RUN ON WINDOWS -- it was written and unit-tested on Linux against
REM a fake kernel32. This script is how it gets confirmed at a station, and it
REM should be run before trusting the behaviour on any instrument PC.
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
REM whole group to die; do not run it against a group that is executing a
REM sequence. It launches its own group and does not touch an existing one --
REM but the stale-group guard means it will refuse to start if one is running,
REM which is itself the correct outcome and is reported as such.
REM ---------------------------------------------------------------------------

REM Default to failure. Every success path sets this to 0 explicitly, so an exit
REM route nobody thought about reports FAIL rather than a silent PASS.
set RC=1

set CONFIG=%1
if "%CONFIG%"=="" set CONFIG=golden
shift

set PORTS=
:collect_ports
if "%1"=="" goto ports_done
set PORTS=!PORTS! %1
shift
goto collect_ports
:ports_done
if "!PORTS!"=="" set PORTS= 5001 5002 5003

set REPO=%~dp0..\..\..\..
pushd "%REPO%"

set OUT=%TEMP%\helao_orphan_smoke
if not exist "%OUT%" mkdir "%OUT%"

echo [1/5] launching %CONFIG% ...
REM `start` so this script keeps control; the launcher gets its own window, which
REM is also what gives it a console for the CTRL_BREAK path to be meaningful.
start "helao-orphan-smoke" /MIN cmd /c "python launch.py %CONFIG% > "%OUT%\launch.log" 2>&1"

echo     waiting 60s for the group to bind its ports ...
REM No `sleep` on stock Windows; a pingable loopback delay is the usual stand-in.
ping -n 61 127.0.0.1 >nul

echo [2/5] confirming the group came up ...
wmic process get CommandLine,ProcessId > "%OUT%\wmic_before.txt" 2>nul
netstat -ano > "%OUT%\netstat_before.txt"
REM A DIRECT check, not the orphan checker with its result inverted. Inverting it
REM would treat *any* non-zero exit as "the group is up", including the checker
REM failing to open a file or dying on a traceback -- so a broken pre-check would
REM read as a healthy group and the whole smoke test would pass without ever
REM having launched anything. This asks the one question that matters instead:
REM is a launcher child actually running for this config?
findstr /i "_launcher.py %CONFIG%" "%OUT%\wmic_before.txt" >nul 2>&1
if not errorlevel 1 goto group_is_up
echo     FAIL: no launcher child is running for %CONFIG%.
echo     The group has to be up for this test to mean anything -- a silent bind
echo     failure or a stale-group refusal would otherwise look like a pass.
echo     Check "%OUT%\launch.log".
set RC=1
goto cleanup
:group_is_up

echo [3/5] force-killing the launcher (no cooperative shutdown) ...
REM /F is the point: TerminateProcess with no chance to run any teardown, which
REM is what a crash or an End Task looks like. Only the monitor is killed -- the
REM job object is what must take the children with it.
for /f "tokens=2" %%p in ('wmic process where "CommandLine like '%%launch.py %CONFIG%%%'" get ProcessId^,CommandLine 2^>nul ^| findstr /i "launch.py"') do (
    echo     taskkill /F /PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo     waiting 20s for the kernel to tear the job down ...
ping -n 21 127.0.0.1 >nul

echo [4/5] collecting evidence ...
wmic process get CommandLine,ProcessId > "%OUT%\wmic_after.txt" 2>nul
netstat -ano > "%OUT%\netstat_after.txt"

echo [5/5] verdict:
python -m helao.core.tests.win_orphan_check "%OUT%\wmic_after.txt" "%OUT%\netstat_after.txt" !PORTS! --prefix %CONFIG%
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
REM Belt and braces: if the test failed, the group is still running and holding
REM hardware. Leave nothing behind either way.
taskkill /F /FI "WINDOWTITLE eq helao-orphan-smoke*" >nul 2>&1
for /f "tokens=2" %%p in ('wmic process where "CommandLine like '%%_launcher.py %CONFIG%%%'" get ProcessId^,CommandLine 2^>nul ^| findstr /i "_launcher.py"') do (
    taskkill /F /PID %%p >nul 2>&1
)
popd
exit /b %RC%
