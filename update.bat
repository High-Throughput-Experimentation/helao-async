@echo off
call conda activate helao
for /f "delims=" %%i in ('git branch --show-current') do set currentbranch=%%i
git reset --hard
git switch main
git branch -D unstable
git fetch --prune
git checkout %currentbranch%
git pull
cd ..\helao-core
git reset --hard
git switch main
git branch -D unstable
git fetch --prune
git checkout %currentbranch%
git pull