@echo off
call conda activate helao
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0"
%windir%\System32\timeout.exe 15 /nobreak
python multi_orch_demo_helper.py plate0
%windir%\System32\timeout.exe 15 /nobreak
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo1"
%windir%\System32\timeout /t 15 /nobreak
@REM python multi_orch_demo_helper.py plate1
%windir%\System32\timeout.exe 15 /nobreak
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo2"
%windir%\System32\timeout /t 15 /nobreak
@REM python multi_orch_demo_helper.py plate2