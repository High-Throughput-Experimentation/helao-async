@echo off
call conda activate helao

echo resetting helao-async and pulling updates
cd ..\helao-async
git fetch --prune --all && git reset --hard && git pull
echo[ 