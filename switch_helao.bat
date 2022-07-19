@echo off
call conda activate base
cd C:\INST_hlo\CODE\helao-core
git fetch
git switch %1
cd C:\INST_hlo\CODE\helao-async
git fetch
git switch %1