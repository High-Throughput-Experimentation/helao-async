@echo off
call conda activate helao
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0 nolive"
%windir%\System32\timeout.exe 45 /nobreak
python multi_orch_demo_helper.py demo0 50
%windir%\System32\timeout.exe 30 /nobreak
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0 liveonly"
%windir%\System32\timeout /t 30 /nobreak
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo1"
%windir%\System32\timeout /t 30 /nobreak
python multi_orch_demo_helper.py demo1 5
%windir%\System32\timeout /t 300 /nobreak
python multi_orch_demo_helper.py demo1 5