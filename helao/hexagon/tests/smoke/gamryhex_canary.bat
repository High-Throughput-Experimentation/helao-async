@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM Windows canary for the gamryhex hexagon cut-over: runtime /openapi.json diff.
REM
REM Launches the LEGACY gamry group and the HEXAGON gamryhex group in turn,
REM dumps each PSTAT server's live /openapi.json, and diffs them. An identical
REM route/schema surface proves the hexagon makeActionApp factory produces a
REM byte-parity action server for the first hte cut-over target.
REM
REM Why NOT parity_run.sh / harness.capture: that harness is hardcoded to the
REM golden SIM group topology (orch@8001, sim@8002, db@8010) and dispatches
REM sequences to an orchestrator. gamryhex is a 2-server group (PSTAT@8001 +
REM ACTVIS@5001) with NO orchestrator, so the GM-* scenarios cannot drive it.
REM The openapi diff is the topology-appropriate parity check.
REM
REM Both configs share root C:\INST_hlo and ports 8001/5001, so they MUST run
REM sequentially (this script does that) -- never launch both at once.
REM gamryhex is simulation:true, so no live potentiostat is required.
REM
REM Usage: gamryhex_canary.bat [root] [outdir]
REM   root   default C:\INST_hlo   (must match the configs' root: key)
REM   outdir default %TEMP%\gamryhex_canary
REM ---------------------------------------------------------------------------

set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=C:\INST_hlo"
set "OUTDIR=%~2"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\gamryhex_canary"

REM repo root = four levels up from this script (helao\hexagon\tests\smoke\)
pushd "%~dp0..\..\..\.." || exit /b 2
set "REPO=%CD%"

if not exist "%OUTDIR%" mkdir "%OUTDIR%"
set "LEGACY_JSON=%OUTDIR%\gamry_openapi.json"
set "HEX_JSON=%OUTDIR%\gamryhex_openapi.json"

call :run_one gamry     "%LEGACY_JSON%" || goto :fail
call :run_one gamryhex  "%HEX_JSON%"    || goto :fail

echo.
echo [canary] diffing openapi surfaces
conda run -n helao python "%~dp0openapi_diff.py" "%LEGACY_JSON%" "%HEX_JSON%"
set "DIFF_RC=!errorlevel!"
popd
if "%DIFF_RC%"=="0" (
  echo [canary] PASS -- gamryhex openapi surface matches legacy gamry
) else (
  echo [canary] DIFFS FOUND -- see output above; artifacts in %OUTDIR%
)
exit /b %DIFF_RC%

REM ---------------------------------------------------------------------------
:run_one
REM %1 = config prefix, %2 = output json path
set "PREFIX=%~1"
set "OUTJSON=%~2"
set "LAUNCHLOG=%OUTDIR%\%PREFIX%.launch.log"
set "WINTITLE=HELAO_CANARY_%PREFIX%"

echo.
echo [canary] === %PREFIX% ===
echo [canary] wiping fresh root %ROOT%
if exist "%ROOT%" rmdir /s /q "%ROOT%"

echo [canary] launching %PREFIX% (log: %LAUNCHLOG%)
start "%WINTITLE%" cmd /c "conda run -n helao python launch.py %PREFIX% --no-hot-reload > "%LAUNCHLOG%" 2>&1"

echo [canary] waiting for PSTAT port 8001
set "UP=0"
for /l %%i in (1,1,90) do (
  conda run -n helao python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',8001))==0 else 1)" 2>nul
  if !errorlevel! equ 0 ( set "UP=1" & goto :got_port )
  timeout /t 2 /nobreak >nul
)
:got_port
if not "%UP%"=="1" (
  echo [canary] FAIL %PREFIX% port 8001 never came up; launch tail:
  powershell -NoProfile -Command "if (Test-Path '%LAUNCHLOG%') { Get-Content -Tail 40 '%LAUNCHLOG%' }"
  call :kill_one
  exit /b 2
)
timeout /t 3 /nobreak >nul

echo [canary] fetching /openapi.json -> %OUTJSON%
conda run -n helao python -c "import urllib.request,sys; open(sys.argv[2],'wb').write(urllib.request.urlopen('http://127.0.0.1:8001/openapi.json',timeout=30).read())" x "%OUTJSON%"
set "FETCH_RC=!errorlevel!"

echo [canary] killing %PREFIX%
call :kill_one

if not "%FETCH_RC%"=="0" (
  echo [canary] FAIL %PREFIX% openapi fetch rc=%FETCH_RC%
  exit /b 2
)
exit /b 0

REM ---------------------------------------------------------------------------
:kill_one
conda run -n helao python helao\hexagon\tests\smoke\kill_group.py "%ROOT%" "%PREFIX%"
taskkill /FI "WINDOWTITLE eq %WINTITLE%*" /T /F >nul 2>&1
goto :eof

REM ---------------------------------------------------------------------------
:fail
popd
echo [canary] ABORTED -- a launch/fetch step failed; see logs in %OUTDIR%
exit /b 2
