#!/usr/bin/env bash
HA_DIR=$(readlink -f $0 | xargs -0 dirname)
# conda activate helao

echo "resetting helao-async and pulling updates"
cd "$HA_DIR" || exit
git fetch --prune --all && git reset --hard && git pull
cd "helao/deploy" || exit

for dir in */; do
    # Check if the directory is not "test" and not "hte"
    if [[ "$dir" != "test/" && "$dir" != "hte/" && "$dir" != "__pycache__/" ]]; then
        echo "--- updating ${dir%/} ---"
        cd "$dir" || exit
        git pull
        cd ..
        echo ""
    fi
done
cd "$HA_DIR" || exit