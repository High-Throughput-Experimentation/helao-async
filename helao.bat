@echo off
for %%A IN ("%~dp0.") do set REPO_PARENT_FOLDER=%%~dpA
set HA_DIR=%REPO_PARENT_FOLDER%helao-async
call conda activate helao
rem helao\core\servers was deleted from git; drop the leftover untracked copy (__pycache__)
if exist "%HA_DIR%\helao\core\servers" rmdir /s /q "%HA_DIR%\helao\core\servers"
python %HA_DIR%\launch.py %*
