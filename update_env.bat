@echo off
for %%A IN ("%~dp0.") do set REPO_PARENT_FOLDER=%%~dpA
set HA_DIR=%REPO_PARENT_FOLDER%helao-async
set HC_DIR=%REPO_PARENT_FOLDER%helao-core
if not exist %HC_DIR% (
    echo %HC_DIR% does not exist, cloning...
    git clone https://github.com/High-Throughput-Experimentation/helao-core %HC_DIR%
)
conda env list | findstr /r /c:"^helao.*envs\\helao$"
if ERRORLEVEL 1 (
    echo 'helao' conda environment was not found, creating it now...
    conda env create -f helao_dev_win-64.yml -n helao
)
conda env update -f helao_dev_win-64.yml
echo.
call conda activate helao
echo setting PYTHONPATH in 'helao' conda environment vars
call conda env config vars set PYTHONPATH=%HA_DIR%;%HC_DIR%
call conda env config vars set HELAOLAUNCH=%HA_DIR%\helao.bat
call conda deactivate
echo.
echo 'helao' environment update is complete