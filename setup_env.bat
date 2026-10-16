@echo off
set HA_DIR=%~dp0
if "%HA_DIR:~-1%"=="\" set HA_DIR=%HA_DIR:~0,-1%
conda env list | findstr /r /c:"^helao.*envs\\helao$"
if ERRORLEVEL 1 (
    echo 'helao' conda environment was not found, creating it now...
    call conda env create --solver=rattler -f helao_dev_win-64.yml -n helao || exit /b 1
)
echo.
call conda activate helao
if /I not "%CONDA_DEFAULT_ENV%"=="helao" (
    echo ERROR: expected conda env 'helao', got '%CONDA_DEFAULT_ENV%'
    exit /b 1
)
uv pip install --python "%CONDA_PREFIX%\python.exe" -r "%~dp0requirements.txt"
if ERRORLEVEL 1 exit /b 1
echo setting PYTHONPATH in 'helao' conda environment vars
call conda env config vars set PYTHONPATH=%HA_DIR%
call conda env config vars set HELAOLAUNCH=%HA_DIR%\helao.bat
call conda deactivate
echo.
echo 'helao' environment setup is complete