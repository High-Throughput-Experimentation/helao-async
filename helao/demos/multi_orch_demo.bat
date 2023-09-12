@echo off
set TERMGUI=%windir%\System32\cmd.exe
set SLEEPCMD=%windir%\System32\timeout.exe
call conda activate helao
start %TERMGUI% /k ("%HELAOLAUNCH%" "demo0" "actionvis")
%SLEEPCMD% /t 35 /nobreak
python multi_orch_demo_helper.py demo0 50
%SLEEPCMD% /t 30 /nobreak
start %TERMGUI% /k ("%HELAOLAUNCH%" "demo0" "gpvis")
%SLEEPCMD% /t 30 /nobreak
start %TERMGUI% /k ("%HELAOLAUNCH%" "demo1")
%SLEEPCMD% /t 30 /nobreak
python multi_orch_demo_helper.py demo1 5
%SLEEPCMD% /t 300 /nobreak
python multi_orch_demo_helper.py demo1 30