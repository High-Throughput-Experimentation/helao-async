@echo off
call conda activate helao
cd ..\helao-async
for /f "delims=" %%i in ('git branch --show-current') do set asyncbranch=%%i
echo %asyncbranch%
git switch main
git switch -D unstable
git fetch --prune
git reset --hard
git switch %asyncbranch%
git pull
cd ..\helao-core
for /f "delims=" %%i in ('git branch --show-current') do set corebranch=%%i
echo %corebranch%
git switch main
git branch -D unstable
git fetch --prune
git reset --hard
git switch %corebranch%
git pull