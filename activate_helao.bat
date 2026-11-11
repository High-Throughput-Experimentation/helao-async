@echo off
rem Activate the helao environment in the calling cmd. Use:
rem     call "%HA_DIR%\activate_helao.bat" || exit /b 1
rem Prefers the pixi workspace <repo>\.helao-env; falls back to a conda env
rem named helao while hosts move over.
set "_HELAO_WS=%~dp0.helao-env\pixi.toml"
set "_HELAO_PIXI="
for /f "delims=" %%P in ('where pixi 2^>nul') do if not defined _HELAO_PIXI set "_HELAO_PIXI=%%P"
if not defined _HELAO_PIXI if exist "%USERPROFILE%\.pixi\bin\pixi.exe" set "_HELAO_PIXI=%USERPROFILE%\.pixi\bin\pixi.exe"
set "_HELAO_LOCK=%~dp0.helao-env\pixi.lock"
if not exist "%_HELAO_WS%" goto :conda
if not exist "%_HELAO_LOCK%" goto :conda
if not defined _HELAO_PIXI (
    echo ERROR: %_HELAO_WS% exists but pixi is not on PATH or in %%USERPROFILE%%\.pixi\bin; run setup_env.bat to install it 1>&2
    exit /b 1
)
set "_HELAO_HOOK=%TEMP%\helao_activate_%RANDOM%%RANDOM%.bat"
"%_HELAO_PIXI%" shell-hook --frozen --manifest-path "%_HELAO_WS%" --shell cmd > "%_HELAO_HOOK%" || exit /b 1
call "%_HELAO_HOOK%"
del "%_HELAO_HOOK%" >nul 2>&1
exit /b 0
:conda
conda env list 2>nul | findstr /r /c:"envs\\helao$" >nul
if ERRORLEVEL 1 (
    echo ERROR: no helao environment; run setup_env.bat ^<config prefix^> ... 1>&2
    exit /b 1
)
echo WARNING: helao is still on conda; run setup_env.bat to move to pixi 1>&2
call conda activate helao
exit /b 0
