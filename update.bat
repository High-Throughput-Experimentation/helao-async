@echo off
call conda activate helao
cd C:\INST_hlo\CODE\helao-core
git fetch --prune
git reset --hard
git pull
cd C:\INST_hlo\CODE\helao-async
git fetch --prune
git reset --hard
git pull