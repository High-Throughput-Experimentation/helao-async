#!/usr/bin/env bash
TERMGUI=/usr/bin/alacritty
CONDA_DIR=$(echo $CONDA_EXE | xargs -0 dirname | xargs -0 dirname)
source $CONDA_DIR/etc/profile.d/conda.sh
conda activate helao

$TERMGUI -e "$HELAOLAUNCH demo0 actionvis"
sleep 35
python multi_orch_demo_helper.py demo0 50
sleep 30 
start %TERMGUI% /k "$HELAOLAUNCH demo0 gpvis"
sleep 30 
start %TERMGUI% /k "$HELAOLAUNCH demo1"
sleep 30 
python multi_orch_demo_helper.py demo1 5
sleep 300 
python multi_orch_demo_helper.py demo1 30