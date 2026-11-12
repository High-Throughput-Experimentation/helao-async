#!/usr/bin/env bash
HA_DIR=$(dirname "$(readlink -f "$0")")
source "$HA_DIR/activate_helao.sh" || exit 1
# helao/core/servers was deleted from git; drop the leftover untracked copy (__pycache__)
if [ -d "$HA_DIR/helao/core/servers" ]; then rm -rf "$HA_DIR/helao/core/servers"; fi
python "$HA_DIR/launch.py" "$@"
