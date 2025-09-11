@echo off
HA_DIR=%~dp0
call conda activate helao

echo resetting helao-async and pulling updates
cd %HA_DIR%
git fetch --prune --all && git reset --hard && git pull
cd %HA_DIR%\helao\deploy
for /d %%d in (*) do (
    rem Check if the directory name is not "test" and not "hte"
    if /i not "%%d"=="test" (
        if /i not "%%d"=="hte" (
            echo --- updating "%%d" ---
            cd "%%d"
            git fetch --prune --all && git reset --hard && git pull
            cd ..
        )
    )
)
echo[ 