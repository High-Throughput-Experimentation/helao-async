# HELAO-async

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles. This repository contains instrument drivers, API server configurations, experiment sequences, and models. As of version 2025.07.07, it no longer depends on the [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) package.

## Requirements

- Windows is required for Galil (gclib) and Gamry (comtypes) drivers. (Tested with Windows 10 x64)
- [miniconda](https://docs.conda.io/en/latest/miniconda.html); the `helao` env pins Python 3.14 (see `helao_dev_*.yml`); its pip packages are in `requirements.txt` and `setup_env.*` installs them with `uv` after conda.

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

The `launch.py` script is used to validate configuration, launch, and shutdown all servers belonging to an orchestration group. Orchestration groups are defined by the YAML files in `helao/deploy/*/configs/`; launch one by its file-name prefix with `helao.bat <prefix>` (Windows) or `./helao.sh <prefix>` (Linux). See the launch section of [CLAUDE.md](CLAUDE.md) for options, and for what happens when servers from an earlier launch are still running.

## Description of launch scripts and utilities

| file name | file description |
| --- | --- |
| helao.bat | windows batch script for activating `helao` conda environment and running `python launch.py` with args |
| helao.sh | linux bash script for activating `helao` conda environment and running `python launch.py` with args |
| launch.py | main launcher script, requires config prefix or config path as first argument |
| setup_env.bat | windows batch script, creates the `helao` conda environment if missing, installs `requirements.txt` with uv, and sets its PYTHONPATH environment variable |
| setup_env.sh | linux bash script, creates the `helao` conda environment if missing, installs `requirements.txt` with uv, and sets its PYTHONPATH environment variable |
| switch.bat | windows batch utility script for switching `helao-async` and deployment branches |
| update.bat | windows batch utility script for updating `helao-async` and the nested deployment repos |

## Development notes

As of HELAO-async release 2023.09.28, new development branches will first be merged into "unstable" for stress testing prior to merging into "main". The "main" branch will only be used for stable releases.
