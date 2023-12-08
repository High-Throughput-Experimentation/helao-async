@echo off
call conda activate helao
cd ..\helao-core
for /f "delims=" %%i in ('git branch --show-current') do set corebranch=%%i
git switch main
git branch -D unstable
git fetch --prune
git reset --hard
git pull
git switch %corebranch%
git pull
cd ..\helao-async
for /f "delims=" %%i in ('git branch --show-current') do set asyncbranch=%%i
git switch main
git switch -D unstable
git fetch --prune
git reset --hard
git pull
git switch %asyncbranch%
git pull