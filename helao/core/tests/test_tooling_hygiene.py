"""Tooling hygiene: run_tests discovery under ``.claude/``; clean-clone schema check."""

from pathlib import Path

import run_tests
from helao.core.tests import unit_test_status_transitions as ust


def test_discovery_works_when_checkout_is_under_dot_claude(monkeypatch, tmp_path):
    root = tmp_path / ".claude" / "worktrees" / "wt"
    test_file = root / "helao" / "hexagon" / "tests" / "test_x.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_x():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "REPO_ROOT", root)
    assert [p for _, p in run_tests.discover_files()] == [test_file]
    # a skip part *inside* the checkout is still skipped
    assert run_tests._skipped(root / "node_modules" / "test_y.py")


class _Reporter:
    ok = None

    def check(self, desc, fn):
        self.ok = fn()


def test_schema_freeze_fails_when_tracked_baseline_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ust, "SCHEMA_BASELINE_PATH", tmp_path / "absent.json")
    r = _Reporter()
    ust._check_schema_freeze(r)
    assert r.ok is False


def test_schema_baseline_is_tracked_under_tests_tree():
    assert ust.SCHEMA_BASELINE_PATH.is_file()


REPO = Path(__file__).resolve().parents[3]


def test_test_configs_carry_no_user_home_root():
    bad = [
        p.name
        for p in (REPO / "helao/deploy/test/configs").glob("*.yml")
        if any(
            line.startswith("root: /home/")
            for line in p.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert not bad, bad


def test_smoke_canary_configs_carry_no_alert_config_path():
    cfgs = list((REPO / "helao/hexagon/tests/smoke/configs").glob("*.yml"))
    assert cfgs
    bad = [c.name for c in cfgs if "alert_config_path" in c.read_text(encoding="utf-8")]
    assert not bad, bad


def test_launch_unit_gate_failure_exits_nonzero():
    src = (REPO / "launch.py").read_text(encoding="utf-8")
    assert "if run_all_unit_tests() != 0:\n            sys.exit(1)" in src
