@echo off
call conda activate helao
cd ..\helao-core
git fetch
git switch main
git switch %1
cd ..\helao-async
git fetch
git switch %1