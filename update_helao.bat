@echo off
call conda activate base
cd C:\INST_hlo\CODE\helao-core
git fetch
git reset --hard
git pull
cd C:\INST_hlo\CODE\helao-async
git fetch
git reset --hard
git pull