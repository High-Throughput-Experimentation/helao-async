@echo off
set HA_DIR=%~dp0..\helao-async
set HC_DIR=%~dp0..\helao-core
if not exist %HC_DIR% (
    echo "%HC_DIR% does not exist, cloning..."
    git clone https://github.com/High-Throughput-Experimentation/helao-core %HC_DIR%
)
conda env list | findstr /c:"helao"
if ERRORLEVEL 1(
    echo "'helao' conda environment was not found, creating it now..."
    conda env create -f helao_pinned_win-64.yml -n helao
)
echo ""
echo ""
call conda activate helao
echo "setting PYTHONPATH in 'helao' conda environment vars"
conda env config vars set PYTHONPATH=%HA_DIR%;%HC_DIR%
call conda deactivate
call conda activate helao
echo ""