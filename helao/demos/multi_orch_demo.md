# Multi-orchestrator demonstration

The multi-orchestrator demo launches two instrumentation groups, each with their own orchestrator and simulated measurement server. The first group additionally contains a compute server for predicting OER overpotentials on the loaded composition spaces available for measurement. The compute server fits measured overpotentials to composition using a gaussian process regressor which yields prediction uncertainties to be included in the acquisition of the next measurement.

| file name                 | file description                                                                |
| ------------------------- | ------------------------------------------------------------------------------- |
| multi_orch_demo.bat       | windows cmd batch script for launching multi-orchestrator, shared resource demo |
| multi_orch_demo_helper.py | python wrapper for launching helao with demo configurations                     |
| HelaoData_example.ipynb   | example notebook for parsing helao data structures                              |

## Usage
1. Setup the helao environment per [readme.md](../../readme.md), hardware drivers are not required for this simulator demo.
2. Modify `config['root']` in both `helao\configs\demo0.py` and `helao\configs\demo1.py` to change where instrument logs and data are saved.
3. From helao-async repo root, change directory to demos: ```cd helao\demos```
4. Run: ```multi_orch_demo.bat```

## Description
The `multi_orch_demo.bat` batch script will launch the first orchestrator along with a simulated CP measurement server and compute server, then wait 30 seconds before queueing and starting a command sequence of 100 active learning measure-acquire iterations for the composition library loaded on the measurement server. After 15 seconds, the second orchestrator and simulated CP measurement servers will start, and this orchestrator will share the compute server already running in the first group. Another set of 100 active learning iterations will be queued and started on the second group.
