#!/usr/bin/env bash
HA_DIR=$(readlink -f $0 | xargs -0 dirname)
# conda activate helao

echo "resetting helao-async and pulling updates"
cd "$HA_DIR" || exit
git fetch --prune --all && git reset --hard && git pull
cd "helao/deploy" || exit

for dir in */; do
    # test/ and base/ are tracked here; every other deployment is its own git repo
    if [[ "$dir" != "test/" && "$dir" != "base/" && "$dir" != "__pycache__/" ]]; then
        if [[ ! -e "$dir/.git" ]]; then
            echo "--- skipping ${dir%/}: not a git repo (run update_env to clone or replace it) ---"
            continue
        fi
        echo "--- updating ${dir%/} ---"
        cd "$dir" || exit
        git pull
        cd ..
        echo ""
    fi
done
cd "$HA_DIR" || exit