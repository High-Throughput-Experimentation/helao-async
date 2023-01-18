@echo off
call conda activate helao
cd C:\INST_hlo\CODE\helao-core
git fetch
git switch main
git switch %1
cd C:\INST_hlo\CODE\helao-async
git fetch
git switch %1