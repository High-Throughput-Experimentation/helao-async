@echo off
HA_DIR=%~dp0
call conda activate helao

echo resetting helao-async and pulling updates
cd %HA_DIR
git fetch --prune --all && git reset --hard && git pull
cd helao\deploy
for /d %%d in (*) do (
    rem Check if the directory name is not "test" and not "hte"
    if /i not "%%d"=="test" (
        if /i not "%%d"=="hte" (
            if /i not "%%d"=="__pycache__" (
            echo --- updating "%%d" ---
            cd "%%d"
            git fetch --prune --all && git reset --hard && git pull
            cd ..
            )
        )
    )
)
cd %HA_DIR
echo[ 