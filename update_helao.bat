@echo off
call conda activate base
cd C:\INST_hlo\CODE\helao-core
git reset --hard
git pull
cd C:\INST_hlo\CODE\helao-async
git reset --hard
git pull