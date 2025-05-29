@echo off
call conda activate helao

echo switching helao-async branch
cd ..\helao-async
git fetch --all && git switch main && git branch -D unstable && git switch unstable && git switch %1
echo[ 