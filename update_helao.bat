@echo off
call conda activate base
SETLOCAL
set hdir = %~dp0
cd %hdir%..\helao-core
git reset --hard
git pull
cd %hdir%
git reset --hard
git pull
ENDLOCAL