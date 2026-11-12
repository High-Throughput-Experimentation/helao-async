@echo off
call "%~dp0activate_helao.bat" || exit /b 1
ipython
