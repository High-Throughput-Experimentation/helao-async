@echo off
call conda activate helao
cd ..\helao-core
git fetch --all
if %~1=="main" (
    git switch main
) else (
    git switch unstable_2401
)
git switch %1
cd ..\helao-async
git fetch --all
git switch %1