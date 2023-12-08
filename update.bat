@echo off
call conda activate helao
cd ..\helao-core
echo cd
for /f "delims=" %%i in ('git branch --show-current') do set corebranch=%%i
git reset --hard
git fetch --prune
git switch main
git branch -D unstable
git pull
git switch %corebranch%
git pull
cd ..\helao-async
echo cd
for /f "delims=" %%i in ('git branch --show-current') do set asyncbranch=%%i
git reset --hard
git fetch --prune
git switch main
git branch -D unstable
echo %asyncbranch%
echo %asyncbranch%
git pull
git switch %asyncbranch%
git pull