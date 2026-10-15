@echo off
set HA_DIR=%~dp0
if "%HA_DIR:~-1%"=="\" set HA_DIR=%HA_DIR:~0,-1%
call conda activate helao
rem helao\core\servers was deleted from git; drop the leftover untracked copy (__pycache__)
if exist "%HA_DIR%\helao\core\servers" rmdir /s /q "%HA_DIR%\helao\core\servers"
python %HA_DIR%\launch.py %*
