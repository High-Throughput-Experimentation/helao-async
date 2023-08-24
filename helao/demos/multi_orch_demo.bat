@echo off
call conda activate helao

@REM 1. Start the first instrument group containing an orchestrator, simulated measurement server, and gaussian process modeling server.
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0 actionvis"

@REM 2. Wait 35 seconds for full server initialization.
%windir%\System32\timeout.exe 35 /nobreak

@REM 3. Queue a sequence of 50 active learning iterations on the plate library loaded in the first instrument group.
python multi_orch_demo_helper.py demo0 50

@REM 4. Wait 30 seconds while the first instrument group performs acquire-measure-model iterations.
%windir%\System32\timeout.exe 30 /nobreak

@REM 5. Start a visualizer for the gaussian process modeling server as an independent observer.
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo0 gpvis"

@REM 6. Wait 30 seconds while the first instrument group continues iterations, and the modeling visualizer plots the latest distributions of predicted Eta and the acquired ground truth.
%windir%\System32\timeout /t 30 /nobreak

@REM 7. Start a second instrument group containing an orchestrator and simulated measurement server. This group will share the existing gaussian process modeling server and leverage the existing acquisition set.
start %windir%\System32\cmd.exe /k "cd %dp0&cd..&cd..&helao.bat demo1"

@REM 8. Wait 30 seconds for server initialization.
%windir%\System32\timeout /t 30 /nobreak

@REM 9. Queue a sequence of 5 active learning iterations on a different plate library loaded in the second instrument group.
python multi_orch_demo_helper.py demo1 5

@REM 10. Wait 300 seconds, by which point the second instrument group would be idle after completeing the 5-iteration sequence.
%windir%\System32\timeout /t 300 /nobreak

@REM 11. Queue a sequence of 30 active learning itterations on the second instrument group.
python multi_orch_demo_helper.py demo1 30