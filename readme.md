# HELAO-async

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles. This repository contains instrument drivers, API server configurations, experiment sequences, and models. As of version 2025.07.07, it no longer depends on the [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) package.

## Requirements

- Windows is required for Galil (gclib) and Gamry (comtypes) drivers. (Tested with Windows 10 x64)
- [miniconda](https://docs.conda.io/en/latest/miniconda.html); the `helao` env pins Python 3.14 (see `helao_dev_*.yml`); its pip packages are in `requirements.txt` and `setup_env.*` installs them with `uv` after conda.

## Installation

From a miniconda prompt or PowerShell with an active conda profile:

#### Windows

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    setup_env.bat
#### Linux

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    bash setup_env.sh

`setup_env` creates the `helao` env from `helao_dev_<platform>.yml` if it is missing, activates it and checks that `helao` is the active env, installs `requirements.txt` with `uv pip install`, and sets `PYTHONPATH` (the repo root) and `HELAOLAUNCH` in the env.

To pick up changed env files later, run `update_env.bat` / `bash update_env.sh`. It does the same, after a `conda env update` from the yml. `update_env.bat` sets `PYTHONPATH` and `HELAOLAUNCH` to `<parent folder>\helao-async`, so on Windows the clone folder must be named `helao-async`.

An env built before 2026-10-16 has no `uv`, so `setup_env` fails at the uv step. Run `update_env` once instead; it adds `uv` from the yml.

`helao_pinned_<platform>.yml` and `requirements_pinned_<platform>.txt` are the exact-version variants of the dev yml and `requirements.txt`; the setup and update scripts do not read them. Regenerate them with:

    python repin_envs.py            # report only
    python repin_envs.py --write    # rewrite the pinned files

Private deployments may ship their own env files and setup scripts; see each deployment's readme.

## Usage

The `launch.py` script validates a configuration, launches all servers in an orchestration group, and shuts them down. Orchestration groups are the YAML files in `helao/deploy/*/configs/` (for example `helao/deploy/hte/configs` and `helao/deploy/test/configs`); launch one by its file-name prefix, from the repo root:

    helao.bat <prefix>      # Windows
    ./helao.sh <prefix>     # Linux

Both activate the `helao` env and run `launch.py`. On Linux, always launch through `helao.sh`: running `launch.py` with another python starts the servers on the wrong interpreter.

`launch.bat <prefix>` runs `python launch.py` in whatever env is already active, without activating one. It is for deployments that use a different env: activate it first. Like `update_env.bat` and `hipy.bat`, it assumes the repo folder is named `helao-async`.

See the launch section of [CLAUDE.md](CLAUDE.md) for the flags, and for what happens when servers from an earlier launch are still running.

## Description of launch scripts and utilities

| file name | file description |
| --- | --- |
| helao.bat / helao.sh | activate the `helao` conda env and run `python launch.py` with args |
| launch.bat | windows: run `python launch.py` with args in the active env, no activation |
| launch.py | main launcher script, requires config prefix or config path as first argument |
| setup_env.bat / setup_env.sh | create the `helao` env if missing, install `requirements.txt` with uv, set `PYTHONPATH` and `HELAOLAUNCH` |
| update_env.bat / update_env.sh | as `setup_env`, plus `conda env update` from the yml (adds `uv` to an older env) |
| repin_envs.py | regenerate the pinned yml and requirements files from fresh solves |
| update.bat / update.sh | **discards uncommitted changes to tracked files** in `helao-async` (`git reset --hard`), then pulls; `update.bat` does the same in every nested deployment repo, `update.sh` only pulls them (`hte` and `test` are skipped) |
| switch.bat / switch.sh | **force-deletes the local `unstable` and re-creates it from the remote first** (unpushed commits on it are lost), then switches `helao-async` and every nested deployment repo to a branch; nested repos fall back to their default branch, `helao-async` does not; `switch <deploy-folder> <branch>` switches one nested repo |
| reset_unstable.bat | windows: re-create the local `unstable` from the remote; **discards uncommitted changes and unpushed `unstable` commits** |
| hipy.bat | windows: activate `helao`, set `PYTHONPATH`, start ipython |

## Development notes

As of HELAO-async release 2023.09.28, new development branches will first be merged into "unstable" for stress testing prior to merging into "main". The "main" branch will only be used for stable releases.
