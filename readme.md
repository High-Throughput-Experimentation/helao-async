# HELAO-dev repository
Helao is deploys Hierachical Experimental Laboratory Orchestration


## getting started

## environment setup
- install miniconda[https://docs.conda.io/en/latest/miniconda.html], python 3 only
- clone git repository
- from repo directory, setup conda environment using `conda env create -f helao.yml`
- update environment with `conda env update -f helao.yml`
- for Galil install gclib with: `python "c:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`


## launch script
- `helao.py` script can validate server configuration parameters, launch a group of servers, and shutdown all servers beloning to a group
- server groups may be defined as .py files in the `helao/config/` folder (see `helao/config/world.py` as an example)
- launch syntax: `python helao.py world` will validate and launch servers with parameters defined in `helao/config/world.py`, while also writing all monitored process IDs to `pids_world.pck` in the root directory
- exercise caution when running multiple server groups as there is currently no check for ports that are currently in-use between different config files

## design

![helao](helao_figures.png)
