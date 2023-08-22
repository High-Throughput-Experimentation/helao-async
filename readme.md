# HELAO-async

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles. This repository contains instrument drivers, API server configurations, and experiment sequences intended for use with the [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) package.


## Requirements

- Windows is required for Galil (gclib) and Gamry (comtypes) drivers. (Tested with Windows 7 and Windows 10 x64)
- The [multi-orchestrator demo](helao/demos/multi_orch_demo.md) was tested on Windows 10 and Linux (Ubuntu 22.04), however the helao.py launch script will produce errors in Linux when attempting close server processes before exiting.
- [miniconda](https://docs.conda.io/en/latest/miniconda.html) (Tested with Python 3.8)
- [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core)


### Environment setup

- hardware-specific: install Galil gclib, Gamry Framework, NI MAX drivers

- from miniconda command prompt or PowerShell with an active conda profile:
```
git clone https://github.com/High-Throughput-Experimentation/helao-async.git
git clone https://github.com/High-Throughput-Experimentation/helao-core.git
conda env create -f helao-async/helao.yml
conda activate helao
```

- additional setup for Galil gclib:
```
python "c:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install
```


## Running HELAO

The `helao.py` script is used to validate configuration, launch, and shutdown all servers belonging to an orchestration group. Orchestration groups are defined as in the `helao/config` folder.

The following example will validate and launch servers with parameters defined in `helao/config/adss_dev.py`, while also writing all monitored process IDs to `pids_world.pck` in the root directory:
```
helao adss_dev
```

Exercise caution when running multiple server groups as there is currently no check for ports that are currently in-use between different config files.

