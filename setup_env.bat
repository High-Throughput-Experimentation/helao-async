@echo off
set HA_DIR=%~dp0..\helao-async
set HC_DIR=%~dp0..\helao-core
if not exist %HC_DIR% (
    echo %HC_DIR% does not exist, cloning...
    git clone https://github.com/High-Throughput-Experimentation/helao-core %HC_DIR%
)
conda env list | findstr /r /c:"envs\\helao$"
if ERRORLEVEL 1 (
    echo 'helao' conda environment was not found, creating it now...
    conda env create -f helao_pinned_win-64.yml -n helao
)
echo.
call conda activate helao
echo setting PYTHONPATH in 'helao' conda environment vars
call conda env config vars set PYTHONPATH=%HA_DIR%;%HC_DIR%
call conda env config vars set HELAOLAUNCH=%HA_DIR%\helao.bat
call conda deactivate
echo.
echo 'helao' environment setup is complete