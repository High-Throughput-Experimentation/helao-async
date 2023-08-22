@echo off
call conda activate helao
start cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0"
timeout /t 30 /nobreak
@REM python multi_orch_demo_helper.py plate0
start cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo1"
timeout /t 30 /nobreak
@REM python multi_orch_demo_helper.py plate1
start cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo2"
timeout /t 30 /nobreak
@REM python multi_orch_demo_helper.py plate2