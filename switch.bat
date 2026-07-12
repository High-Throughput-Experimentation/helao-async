@echo off
setlocal enabledelayedexpansion
call conda activate helao

if "%~1"=="" (
    echo usage: switch.bat ^<branch^>
    echo        switch.bat ^<deploy-folder^> ^<branch^>
    exit /b 1
)

cd /d "%~dp0"

if not "%~2"=="" (
    rem two-arg mode: switch only the named nested deploy repo
    set "TARGET=%~2"
    set "REPO=helao\deploy\%~1"
    if not exist "helao\deploy\%~1\.git" (
        echo no nested repo at helao\deploy\%~1
        endlocal
        exit /b 1
    )
    echo switching helao\deploy\%~1 branch
    call :switch_repo "helao\deploy\%~1"
    echo[
    endlocal
    exit /b 0
)

set "TARGET=%~1"

echo switching helao-async branch
git fetch --all && git switch main && git branch -D unstable && git switch unstable && git switch %TARGET%

for /d %%R in (helao\deploy\*) do (
    if exist "%%R\.git" (
        echo switching %%R branch
        call :switch_repo "%%R"
    )
)
echo[
endlocal
exit /b 0

:switch_repo
set "REPO=%~1"
git -C "%REPO%" fetch --all --quiet
git -C "%REPO%" show-ref --verify --quiet refs/heads/%TARGET%
if not errorlevel 1 goto do_switch
git -C "%REPO%" show-ref --verify --quiet refs/remotes/origin/%TARGET%
if not errorlevel 1 goto do_switch

rem target branch not found; resolve this repo's default branch
set "DEF="
for /f "delims=" %%b in ('git -C "%REPO%" symbolic-ref --short refs/remotes/origin/HEAD 2^>nul') do set "DEF=%%b"
if not defined DEF (
    git -C "%REPO%" remote set-head origin -a >nul 2>&1
    for /f "delims=" %%b in ('git -C "%REPO%" symbolic-ref --short refs/remotes/origin/HEAD 2^>nul') do set "DEF=%%b"
)
set "DEF=!DEF:origin/=!"
if not defined DEF (
    git -C "%REPO%" show-ref --verify --quiet refs/remotes/origin/main && set "DEF=main"
)
if not defined DEF (
    git -C "%REPO%" show-ref --verify --quiet refs/remotes/origin/master && set "DEF=master"
)
if not defined DEF (
    for /f "delims=" %%b in ('git -C "%REPO%" for-each-ref --format^="%%(refname:strip=3)" refs/remotes/origin/ 2^>nul') do (
        if not defined DEF if not "%%b"=="HEAD" set "DEF=%%b"
    )
)
if not defined DEF (
    echo   cannot resolve default branch; leaving as-is
    goto :eof
)
echo   '%TARGET%' not found; switching to default '!DEF!'
git -C "%REPO%" switch !DEF!
goto :eof

:do_switch
git -C "%REPO%" switch %TARGET%
goto :eof
