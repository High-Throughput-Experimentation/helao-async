@echo off
call conda activate base
SETLOCAL
set hdir = %~dp0
cd %hdir%..\helao-core
git fetch
git switch %1
cd %hdir%
git fetch
git switch %1
ENDLOCAL