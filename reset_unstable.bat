@echo off
call "%~dp0activate_helao.bat"

echo resetting helao-async and pulling updates
cd /d "%~dp0" || (pause & exit /b 1)
git switch main || (pause & exit /b 1)
git branch -D unstable
git fetch --prune --all && git reset --hard && git pull
git switch unstable
echo[
