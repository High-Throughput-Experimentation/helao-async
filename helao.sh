#!/usr/bin/env bash
HA_DIR=$(readlink -f $0 | xargs -0 dirname)
CONDA_DIR=$(echo $CONDA_EXE | xargs -0 dirname | xargs -0 dirname)
source $CONDA_DIR/etc/profile.d/conda.sh
conda activate helao
python $HA_DIR/launch.py $1