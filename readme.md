# HELAO-async

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles. This repository contains instrument drivers, API server configurations, and experiment sequences intended for use with the [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) package.

## Requirements

- Windows is required for Galil (gclib) and Gamry (comtypes) drivers. (Tested with Windows 10 x64)
- The [multi-orchestrator demo](helao/demos/multi_orch_demo.md) was tested on Windows 10 and Linux (Ubuntu 22.04), however the launch.py launch script will produce errors in Linux when attempting to close server processes before exiting.
- [miniconda](https://docs.conda.io/en/latest/miniconda.html) (Tested with Python 3.11.7)
- [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) (Installed by setup script)

## Installation

From miniconda prompt or PowerShell with an active conda profile run the following commands.
#### Windows

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    setup_env.bat
#### Linux

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    bash setup_env.sh

## Usage

The `launch.py` script is used to validate configuration, launch, and shutdown all servers belonging to an orchestration group. Orchestration groups are defined as in the `helao/config` folder.

The following example will validate and launch servers with parameters defined in `helao/config/demo0.yml`, while also writing all monitored process IDs to `pids_world.pck` in the root directory:
```
helao.bat demo0
```

Exercise caution when running multiple server groups as there is currently no check for ports that are currently in-use between different config files.

## Description of launch scripts and utilities

| file name | file description |
| --- | --- |
| helao.bat | windows batch script for activating `helao` conda environment and running `python launch.py` with args |
| helao.sh | linux bash script for activating `helao` conda environment and running `python launch.py` with args |
| launch.py | main launcher script, requires config prefix or config path as first argument |
| setup_env.bat | windows batch script, sets PYTHONPATH environment variable for `helao` conda environment, and clones `helao-core` repo if not colocated alongside `helao-async` in parent directory |
| setup_env.sh | linux bash script, sets PYTHONPATH environment variable for `helao` conda environment, and clones `helao-core` repo if not colocated alongside `helao-async` in parent directory |
| switch.bat | windows batch utility script for switching `helao-core` and `helao-async` branches |
| update.bat | windows batch utility script for updating `helao-core` and `helao-async` simultaneously |

## Development notes

As of HELAO-async release 2023.09.28, new development branches will first be merged into "unstable" for stress testing prior to merging into "main". The "main" branch will only be used for stable releases.
