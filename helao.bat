@echo off
call conda activate helao
set PYTHONPATH=%~dp0.;%~dp0..\helao-core
python %~dp0helao.py %1
