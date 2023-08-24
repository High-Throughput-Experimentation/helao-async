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
The `multi_orch_demo.bat` batch script will run the following commands:
1. Start the first instrument group containing an orchestrator, simulated measurement server, and gaussian process modeling server.
2. Wait 35 seconds for full server initialization.
3. Queue a sequence of 50 active learning iterations on the plate library loaded in the first instrument group.
4. Wait 30 seconds while the first instrument group performs acquire-measure-model iterations.
5. Start a visualizer for the gaussian process modeling server as an independent observer.
6. Wait 30 seconds while the first instrument group continues iterations, and the modeling visualizer plots the latest distributions of predicted Eta and the acquired ground truth.
7. Start a second instrument group containing an orchestrator and simulated measurement server. This group will share the existing gaussian process modeling server and leverage the existing acquisition set.
8. Wait 30 seconds for server initialization.
9. Queue a sequence of 5 active learning iterations on a different plate library loaded in the second instrument group.
10. Wait 300 seconds, by which point the second instrument group would be idle after completeing the 5-iteration sequence.
11. Queue a sequence of 30 active learning itterations on the second instrument group.

After an initial seed of 5 acquisitions, the demo0 Orchestrator acquires data on {} compositions with data on an additional {} compositions provided by the demo1 Orchestrator, resulting in N={} acquisitions at the end of the demo. After an initial seed of 5 acquisitions, the demo1 Orchestrator acquires data on {} compositions with data on an additional {} compositions provided by the demo0 Orchestrator, resulting in N={} acquisitions at the end of the demo.