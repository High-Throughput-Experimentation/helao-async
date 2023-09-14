@echo off
call conda activate helao
cd ..\helao-core
git fetch --prune
git reset --hard
git pull
cd ..\helao-async
git fetch --prune
git reset --hard
git pull