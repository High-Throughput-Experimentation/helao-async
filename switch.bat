@echo off
call conda activate helao
cd ..\helao-core
git fetch
if %~1=="main" (
    git switch main
) else (
    git switch unstable
)
git switch %1
cd ..\helao-async
git fetch
git switch %1