"""Readers resolve a -prc.yml from either location, exactly once."""

import zipfile
from pathlib import Path

import pytest

PRC_A = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
BODY_A = "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\ntechnique_name: SIM_exp\n"


def _zip_with_prc(tmp_path: Path) -> Path:
    """A synced sequence zip carrying its own -prc.yml, plus an empty mirror."""
    synced = tmp_path / "RUNS_SYNCED" / "26.35" / "0828"
    synced.mkdir(parents=True)
    zpath = synced / "115959__SIM_seq__golden.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("260828.115959000000-seq.yml", "sequence_name: SIM_seq\n")
        zf.writestr(
            "260828.120000__exp/260828.120000000000-exp.yml",
            "experiment_name: SIM_exp\n",
        )
        zf.writestr(f"260828.120000__exp/{PRC_A}", BODY_A)
    (tmp_path / "PROCESSES").mkdir()
    return zpath


def test_a_prc_inside_a_zip_is_read_from_the_zip(tmp_path):
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    zpath = _zip_with_prc(tmp_path)
    loader = LocalLoader(str(zpath))
    prc_paths = loader._yml_paths["prc"]
    assert len(prc_paths) == 1, f"expected one process, got {prc_paths}"
    meta = loader.get_yml(prc_paths[0])
    assert meta["process_uuid"] == "06a5a2d6-b26c-7019-8000-4c2d967e5df1"


def test_a_process_present_in_both_places_is_indexed_once(tmp_path):
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    zpath = _zip_with_prc(tmp_path)
    # LocalLoader derives process_dir itself: for a zip it replaces the
    # RUNS_<state> segment with PROCESSES and drops the .zip suffix, so the
    # mirror for this zip is PROCESSES/26.35/0828/115959__SIM_seq__golden/.
    mirror = (
        tmp_path
        / "PROCESSES"
        / "26.35"
        / "0828"
        / "115959__SIM_seq__golden"
        / "260828.120000__exp"
    )
    mirror.mkdir(parents=True)
    (mirror / PRC_A).write_text(BODY_A)
    loader = LocalLoader(str(zpath))
    assert len(loader._yml_paths["prc"]) == 1, "the same process must not appear twice"


def test_helao_data_picks_the_record_yml_not_the_process(tmp_path):
    from helao.helpers.helao_data import HelaoData

    exp_dir = tmp_path / "RUNS_SYNCED" / "26.35" / "0828" / "seq" / "260828.120000__exp"
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / PRC_A).write_text(BODY_A)  # sorts first under a bare glob
    hd = HelaoData(str(exp_dir))
    assert hd.ymlpath.endswith("-exp.yml")
    assert hd.type == "exp"


def test_processors_picks_the_experiment_yml_not_the_process(tmp_path):
    """HloPostProcessor is abstract, so subclass it to instantiate."""
    from helao.core.models.file import FileInfo
    from helao.helpers.premodels import Action
    from helao.helpers.processors import HloPostProcessor

    rel = Path("26.35") / "0828" / "seq" / "260828.120000__exp"
    exp_dir = tmp_path / "RUNS_ACTIVE" / rel
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / PRC_A).write_text(BODY_A)  # sorts first under a bare glob
    (exp_dir.parent / "260828.115959000000-seq.yml").write_text(
        "sequence_name: SIM_seq\n"
    )

    class _Proc(HloPostProcessor):
        def process(self) -> list[FileInfo]:
            return []

    action = Action(
        action_name="do_thing",
        action_output_dir=str(rel / "0__0__SIM__do_thing"),
    )
    proc = _Proc(action, str(tmp_path / "RUNS_ACTIVE"))
    assert proc.exp_yml_path.endswith("-exp.yml")
    assert proc.seq_yml_path.endswith("-seq.yml")
