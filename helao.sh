#!/usr/bin/env bash
HA_DIR=$(readlink -f $0 | xargs -0 dirname)
CONDA_DIR=$(echo $CONDA_EXE | xargs -0 dirname | xargs -0 dirname)
source $CONDA_DIR/etc/profile.d/conda.sh
conda activate helao
# helao/core/servers was deleted from git; drop the leftover untracked copy (__pycache__)
if [ -d "$HA_DIR/helao/core/servers" ]; then rm -rf "$HA_DIR/helao/core/servers"; fi
python $HA_DIR/launch.py "$@"
