@echo off
call conda activate base
cd %~dp0..\helao-core
git fetch
git switch %1
cd %~dp0
git fetch
git switch %1