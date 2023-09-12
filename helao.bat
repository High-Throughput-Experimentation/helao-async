@echo off
set HA_DIR=%~dp0..\helao-async
call conda activate helao
python %HA_DIR%helao.py %*
