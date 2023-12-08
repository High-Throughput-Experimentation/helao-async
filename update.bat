@echo off
call conda activate helao
cd ..\helao-core
for /f "delims=" %%i in ('git branch --show-current') do set corebranch=%%i
echo %corebranch%
git reset --hard
git fetch --prune
git switch main
git branch -D unstable
git pull
git switch %corebranch%
git pull
cd ..\helao-async
for /f "delims=" %%i in ('git branch --show-current') do set asyncbranch=%%i
echo %asyncbranch%
git reset --hard
git fetch --prune
git switch main
git branch -D unstable
git pull
git switch %asyncbranch%
git pull