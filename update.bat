@echo off
set HA_DIR=%~dp0
@REM call conda activate helao

echo resetting helao-async and pulling updates
cd %HA_DIR%
git fetch --prune --all && git reset --hard && git pull
cd helao\deploy
for /d %%d in (*) do (
    if /i not "%%d"=="test" (
        if /i not "%%d"=="base" (
            if /i not "%%d"=="__pycache__" (
                if exist "%%d\.git" (
                    echo --- updating "%%d" ---
                    cd "%%d"
                    git fetch --prune --all && git reset --hard && git pull
                    cd ..
                ) else (
                    echo --- skipping "%%d": not a git repo, run update_env ---
                )
            )
        )
    )
)
cd %HA_DIR%
echo[ 