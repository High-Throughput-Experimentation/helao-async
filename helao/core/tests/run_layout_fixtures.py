"""A minimal finished action on disk, for layout and movement assertions."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from helao.core.models.helaodirs import HelaoDirs
from helao.helpers.premodels import Action

TS = datetime(2026, 9, 25, 9, 41, 2)


def finished_action(tmp_path: Path):
    """Return ``(action, base)`` with the action's tree already written.

    ``init_seq``/``init_exp`` are called before ``init_act`` because the three
    ``*_output_dir`` fields chain: ``get_action_dir()`` reads
    ``experiment_output_dir``, which reads ``sequence_output_dir``. Skipping
    them yields a literal ``None/`` path segment rather than an error.
    """
    root = tmp_path
    dirs = HelaoDirs(
        root=root,
        save_root=root / "RUNS",
        states_root=root / "STATES",
    )
    act = Action(action_name="do_thing", action_server_name="SIM")
    act.sequence_timestamp = TS
    act.experiment_timestamp = TS
    act.action_timestamp = TS
    act.sequence_name = "seq"
    act.sequence_label = "noLabel"
    act.experiment_name = "exp"
    act.orch_submit_order = 0
    act.action_split = 0
    act.manual_action = False
    act.sync_data = True
    act.init_seq()
    act.init_exp()
    act.init_act()

    act_dir = Path(str(dirs.save_root)) / act.get_action_dir()
    act_dir.mkdir(parents=True)
    (act_dir / "260925.094102000000-act.yml").write_text(
        "action_name: do_thing\n", encoding="utf-8"
    )

    base = SimpleNamespace(
        helaodirs=dirs,
        world_cfg={"root": str(root), "servers": {}},
        run_journal=None,
    )
    return act, base


def finished_experiment(tmp_path: Path):
    """Return ``(experiment, base)`` with the experiment's tree written."""
    from helao.helpers.premodels import Experiment

    _, base = finished_action(tmp_path)
    exp = Experiment(experiment_name="exp")
    exp.sequence_timestamp = TS
    exp.experiment_timestamp = TS
    exp.sequence_name = "seq"
    exp.sequence_label = "noLabel"
    exp.manual_action = False
    exp.init_seq()
    exp.init_exp()
    return exp, base


def finished_sequence(tmp_path: Path):
    """Return ``(sequence, base)`` with the sequence's tree written."""
    from helao.helpers.premodels import Sequence

    _, base = finished_action(tmp_path)
    seq = Sequence(sequence_name="seq")
    seq.sequence_timestamp = TS
    seq.sequence_label = "noLabel"
    seq.init_seq()
    return seq, base
