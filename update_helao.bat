@echo off
call conda activate base
cd %~dp0..\helao-core
git reset --hard
git pull
cd %~dp0
git reset --hard
git pull