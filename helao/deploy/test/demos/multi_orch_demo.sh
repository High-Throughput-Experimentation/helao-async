#!/usr/bin/env bash
TERMGUI=/usr/bin/alacritty
source "$(dirname "$0")/../../../../activate_helao.sh"
$TERMGUI -e $HELAOLAUNCH demo0 actionvis &
sleep 35
python multi_orch_demo_helper.py demo0 50
sleep 30 
$TERMGUI -e $HELAOLAUNCH demo0 gpvis &
sleep 30 
$TERMGUI -e $HELAOLAUNCH demo1 &
sleep 30 
python multi_orch_demo_helper.py demo1 5
sleep 300 
python multi_orch_demo_helper.py demo1 30