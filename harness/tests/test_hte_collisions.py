from pathlib import Path

from harness.hte_collisions import scan_collisions

HTE = Path(__file__).resolve().parents[2] / "helao/deploy/hte"
EXP = HTE / "experiments"
SEQ = HTE / "sequences"


def test_known_seq_collision_detected():
    cols = scan_collisions(SEQ)
    # ECHEUVIS_postseq defined in both ECHEUVIS_seq.py and HISPEC_seq.py
    assert "ECHEUVIS_postseq" in cols
    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])


def test_exp_collision_detected_in_synthetic_pair(tmp_path):
    for mod in ("twin_a_exp", "twin_b_exp"):
        (tmp_path / f"{mod}.py").write_text(
            "def shared_sub_exp():\n    return []\n", encoding="utf-8"
        )
    assert scan_collisions(tmp_path) == {
        "shared_sub_exp": ["twin_a_exp.py", "twin_b_exp.py"]
    }


def test_hte_exp_libraries_have_no_collisions():
    assert scan_collisions(EXP) == {}


def test_exp_collision_detected_in_real_dir_copy(tmp_path):
    # non-vacuity: a copy of the real library plus one duplicate def must be caught
    import shutil

    shutil.copytree(EXP, tmp_path / "e")
    (tmp_path / "e" / "zz_exp.py").write_text(
        "def CCSI_sub_drain():\n    return []\n", encoding="utf-8"
    )
    assert "CCSI_sub_drain" in scan_collisions(tmp_path / "e")
