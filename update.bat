@echo off
call conda activate helao
cd ..\helao-core
git fetch --prune --all
git reset --hard
git pull
cd ..\helao-async
git fetch --prune --all
git reset --hard
git pull