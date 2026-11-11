# HELAO-async

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles. This repository contains the framework (models, server hosts, orchestrator, operator and visualizer UIs, data syncer), the shared framework services in `helao/deploy/base`, and the `test` deployment of simulators and demos. The HTE group's instrument drivers, station configs, experiments and sequences live in the public [`hte` deployment](https://github.com/High-Throughput-Experimentation/helao-hte-deployment), which the setup scripts install into `helao/deploy/hte` (see [Deployments](#deployments)). As of version 2025.07.07, it no longer depends on the [HELAO-core](https://github.com/High-Throughput-Experimentation/helao-core) package.

## Requirements

- Windows is required for Gamry (comtypes) drivers. Galil (gclib) drivers run on Windows and Linux. (Tested with Windows 10 x64)
- [pixi](https://pixi.sh) (setup_env installs it into ~/.pixi if missing); the env pins Python 3.14 (see pixi.toml).

## Installation

From a terminal (Windows: cmd or PowerShell):

#### Windows

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    setup_env.bat
#### Linux

    git clone https://github.com/High-Throughput-Experimentation/helao-async.git
    cd helao-async
    bash setup_env.sh

`setup_env` also installs the public `hte` deployment into `helao/deploy/hte`; see [Deployments](#deployments).

`setup_env` installs pixi if it is missing, creates the host workspace `.helao-env/` from the tracked `pixi.toml` and `pixi.lock` (base env, installed straight from the lock), then composes the station's server packages into it and runs `pixi install`. With no arguments that is the whole install: the base env. For a station, add its config prefixes (`setup_env.bat <prefix> ...` / `bash setup_env.sh <prefix> ...`) to also install the packages its servers need and record the prefixes for later `update_env` runs.

To pick up changed env files later, run `update_env.bat` / `bash update_env.sh`. With no arguments it replays the recorded station prefixes. A host moving from the old conda env must run `setup_env <prefix> ...` once: its record lived in the conda env.

`pixi.lock` pins every base package for `linux-64` and `win-64` (a third `linux-64-cuda` platform lets CUDA hosts share those pins); to move the pins, run `pixi update` in the repo root and commit the lock. A lock merge conflict is resolved by re-locking (`.gitattributes` marks it `merge=binary`).

If the checkout is on a `noexec` mount, run `pixi config set --global detached-environments true` once before `setup_env`; pixi then keeps the env under `~/.cache` instead of `.helao-env/.pixi`.

Private deployments may ship their own env files and setup scripts; see each deployment's readme.

## Deployments

Each folder under `helao/deploy/` is a deployment: configs, server folders, drivers, experiments and sequences for one group of instruments. `launch.py` finds a config by its prefix in any of them.

| deployment | where it lives | how it gets there |
| --- | --- | --- |
| `base` | tracked in this repo | framework services every group launches (orchestrator, operator, visualizers, data syncer, shared Reflex panels) |
| `test` | tracked in this repo | simulators and demo configs; runs without hardware |
| `hte` | its own public repo, [helao-hte-deployment](https://github.com/High-Throughput-Experimentation/helao-hte-deployment) | cloned in place by `setup_env` / `update_env` |
| private deployments | their own git repos, nested in place | cloned by hand; `.gitignore` keeps them out of this repo |

`hte` is a plain nested git repo, not a submodule. The parent repo ignores `helao/deploy/hte`, so commit `hte` changes inside that folder with its own git (`git -C helao/deploy/hte ...`).

### Automatic `hte` install and update

`setup_env` and `update_env` manage `helao/deploy/hte` before they install anything:

- **Missing `hte`:** cloned from `https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git`. A run with no prefix clones it. A run whose config prefix is not found in any present deployment (an `hte` station config such as `eche10`) clones it, then looks the prefix up again. A no-argument `update_env` clones it before replaying the recorded station prefixes.
- **`hte` is a git repo:** always pulled with `git pull --ff-only`, whatever the configs. Tracked files that are missing from the clone (for example after checking out an older parent commit) are restored first. If the pull fails (local edits in the way, a diverged branch, no network), the run stops only when a requested config uses `hte` or a prefix was not found; otherwise it warns and carries on.
- **`hte` is a plain folder** (left over from a checkout made before the split): the new repo is cloned first. The old folder is then moved to `STATES/hte_leftover_<time>/`, and its file list is written to `STATES/hte_leftover_<time>.txt`. Nothing is deleted; remove the archive once you have copied out anything you need.
- **Server packages:** when a station config uses `hte` servers, `setup_env <prefix>` installs the packages listed in those server folders' `environment.yml` / `requirements.txt` (composed into the host's pixi workspace), like any other deployment.

Any git failure leaves `helao/deploy/hte` as it was. To install `hte` by hand, move a leftover folder aside, then run:

    git clone https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git helao/deploy/hte

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
| helao.bat / helao.sh | activate the `helao` env (`activate_helao.*`) and run `python launch.py` with args |
| activate_helao.bat / activate_helao.sh | the one activation: `pixi shell-hook` on `.helao-env/`, or a conda `helao` env during the move |
| launch.bat | windows: run `python launch.py` with args in the active env, no activation |
| launch.py | main launcher script, requires config prefix or config path as first argument |
| setup_env.bat / setup_env.sh | install pixi if missing, create `.helao-env/`, compose station packages, `pixi install` |
| update_env.bat / update_env.sh | `setup_env` in update mode (replays recorded prefixes) |
| pixi.toml / pixi.lock | base packages and their pins for linux-64 and win-64 |
| update.bat / update.sh | **discards uncommitted changes to tracked files** in `helao-async` (`git reset --hard`), then pulls; `update.bat` resets and pulls every nested deployment repo; `update.sh` pulls them; `test` and `base` are tracked here and skipped; a deployment folder without `.git` is skipped with a message |
| switch.bat / switch.sh | **force-deletes the local `unstable` and re-creates it from the remote first** (unpushed commits on it are lost), then switches `helao-async` and every nested deployment repo to a branch; nested repos fall back to their default branch, `helao-async` does not; `switch <deploy-folder> <branch>` switches one nested repo |
| reset_unstable.bat | windows: re-create the local `unstable` from the remote; **discards uncommitted changes and unpushed `unstable` commits** |
| hipy.bat | windows: activate the helao env, start ipython |

## Upgrading a station across the `hte` split (2026-11)

1. Stop the group (`CTRL-x`). Otherwise the hot-reload watcher sees a pull that deletes every `hte` module.
2. Run `git -C <repo> status --short --ignored helao/deploy/hte`. Local edits to tracked `hte` files make `git pull` refuse; copy them out first (`update.sh`/`update.bat` discard them with `reset --hard`). Untracked and ignored station files in the folder are not lost: `update_env` archives the whole leftover under `<root>/STATES/hte_leftover_<time>/` (file list in `hte_leftover_<time>.txt` beside it).
3. Pull the parent **and every private deployment repo** (`update.bat`/`update.sh` do both). A private repo still pinning `deployment: hte` on a framework service, or importing `helao.deploy.hte.servers.reflex`, breaks until it is pulled too.
4. Run `update_env` (no arguments replays the recorded configs). It logs the leftover `helao/deploy/hte` folder, moves it to `STATES/hte_leftover_<time>/` and clones the new repo. If `update_env` fails before it reaches `hte`, do this by hand: move the leftover folder aside, then run `git clone https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git helao/deploy/hte`.
5. Relaunch. The Reflex bundle rebuilds once, because its module paths changed.

Rollback: move the `hte` clone aside first (for example to `STATES/`), then pull the revert: the revert re-tracks `hte` and overwrites the clone. Rolling forward again empties the clone; `update_env` restores it.

Switching branches or commits: `switch.sh`, `switch.bat` and `reset_unstable.bat` pass through `main`, which still tracks `hte` until the next release. Checking out a commit that tracks `hte` empties the `hte` clone (its tracked files are deleted). Run `update_env` afterwards: it restores the deleted tracked files and leaves modified and untracked files alone.

## Development notes

As of HELAO-async release 2023.09.28, new development branches will first be merged into "unstable" for stress testing prior to merging into "main". The "main" branch will only be used for stable releases.
