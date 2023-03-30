@echo off
call conda activate helao
set PYTHONPATH=%~dp0..\helao-async;%~dp0..\helao-core
ipython
