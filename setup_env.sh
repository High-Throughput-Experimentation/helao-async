#!/usr/bin/env bash
HA_DIR=$(readlink -f $0 | xargs -0 dirname)
CONDA_DIR=$(echo $CONDA_EXE | xargs -0 dirname | xargs -0 dirname)
source $CONDA_DIR/etc/profile.d/conda.sh
if [[ ! $(conda env list | grep "^helao.*envs/helao$") ]]
then
    echo "'helao' conda environment was not found, creating it now..."
    conda env create -f helao_pinned_linux-64.yml -n helao
fi
echo ""
echo ""
echo "setting PYTHONPATH in 'helao' conda environment vars"
conda activate helao
conda env config vars set PYTHONPATH=$HA_DIR > /dev/null
conda env config vars set HELAOLAUNCH="$HA_DIR/helao.sh" > /dev/null
chmod +x $HA_DIR/helao.sh
conda deactivate
echo ""
echo "'helao' environment setup is complete"