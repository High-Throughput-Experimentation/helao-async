@echo off
for %%A IN ("%~dp0.") do set REPO_PARENT_FOLDER=%%~dpA
set HA_DIR=%REPO_PARENT_FOLDER%helao-async
call conda activate helao
python %HA_DIR%\launch.py %*
