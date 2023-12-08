@echo off
call conda activate helao
cd ..\helao-core
for /f "delims=" %%i in ('git branch --show-current') do set corebranch=%%i
git reset --hard
git fetch --prune
..\helao-async\switch.bat main
git branch -D unstable
git pull
..\helao-async\switch.bat %corebranch%
git pull
cd ..\helao-async
for /f "delims=" %%i in ('git branch --show-current') do set asyncbranch=%%i
git reset --hard
git fetch --prune
switch.bat main
git branch -D unstable
echo %asyncbranch%
echo %asyncbranch%
git pull
switch.bat %asyncbranch%
git pull