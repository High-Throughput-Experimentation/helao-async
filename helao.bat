@echo off
call conda activate helao
set PYTHONPATH=C:\INST_hlo\CODE\helao-async;C:\INST_hlo\CODE\helao-core
python C:\INST_hlo\CODE\helao-async\helao.py %1
