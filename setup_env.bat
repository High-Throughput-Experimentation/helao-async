@echo off
setlocal
set "HA_DIR=%~dp0"
if "%HA_DIR:~-1%"=="\" set "HA_DIR=%HA_DIR:~0,-1%"
if not defined HELAO_ENV_MODE set HELAO_ENV_MODE=setup
set "PIXI="
for /f "delims=" %%P in ('where pixi 2^>nul') do if not defined PIXI set "PIXI=%%P"
if not defined PIXI if exist "%USERPROFILE%\.pixi\bin\pixi.exe" set "PIXI=%USERPROFILE%\.pixi\bin\pixi.exe"
if defined PIXI goto :havepixi
echo pixi not found; installing it to %USERPROFILE%\.pixi ...
powershell -ExecutionPolicy ByPass -c "irm -useb https://pixi.sh/install.ps1 | iex" || exit /b 1
set "PIXI=%USERPROFILE%\.pixi\bin\pixi.exe"
:havepixi
set "WS=%HA_DIR%\.helao-env"
if exist "%WS%\pixi.toml" goto :haveenv
if not exist "%WS%" mkdir "%WS%" || exit /b 1
copy /y "%HA_DIR%\pixi.toml" "%WS%\" >nul || exit /b 1
copy /y "%HA_DIR%\pixi.lock" "%WS%\" >nul || exit /b 1
:haveenv
"%PIXI%" run --frozen --manifest-path "%WS%\pixi.toml" python "%HA_DIR%\helao_env.py" %HELAO_ENV_MODE% %*
if ERRORLEVEL 1 exit /b 1
echo.
echo 'helao' environment %HELAO_ENV_MODE% is complete
