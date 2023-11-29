@echo off
call conda activate helao
cd ..\helao-core
git switch main
git branch -D unstable
git fetch --prune
git reset --hard
git pull
cd ..\helao-async
git switch main
git switch -D unstable
git fetch --prune
git reset --hard
git pull