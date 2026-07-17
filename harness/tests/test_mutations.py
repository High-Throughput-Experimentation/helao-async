"""Over-normalization guard: every mutation class must be CAUGHT by the gate."""

from harness.mutate import MUTATIONS, run_self_test
from harness.tests.synthtree import attach_manifest, build_tree


def test_all_mutations_are_caught(tmp_path):
    gdir = tmp_path / "golden"
    build_tree(gdir / "root", seed=0)
    attach_manifest(gdir)
    result = run_self_test(gdir, tmp_path / "work")
    assert result["sanity_pass"] is True
    assert set(result["caught"]) == set(MUTATIONS)
    assert all(result["caught"].values()), result
    assert result["ok"] is True
