from pathlib import Path
from harness.hte_collisions import scan_collisions

EXP = Path("helao/deploy/hte/experiments")
SEQ = Path("helao/deploy/hte/sequences")


def test_known_seq_collision_detected():
    cols = scan_collisions(SEQ)
    # ECHEUVIS_postseq defined in both ECHEUVIS_seq.py and HISPEC_seq.py
    assert "ECHEUVIS_postseq" in cols
    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])


def test_known_exp_collision_detected():
    cols = scan_collisions(EXP)
    # CSIL_exp.py forks CCSI_sub_* names from CCSI_exp.py
    ccsi_dupes = {n: m for n, m in cols.items() if n.startswith("CCSI_sub_")}
    assert ccsi_dupes, "expected CCSI_sub_* forks across CCSI_exp.py/CSIL_exp.py"
    for mods in ccsi_dupes.values():
        assert {"CCSI_exp.py", "CSIL_exp.py"} <= set(mods)
