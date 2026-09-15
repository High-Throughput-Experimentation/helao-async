"""A record whose parent yml is not on disk yet defers instead of syncing.

A post-hoc converter writes an experiment's ``-act.yml`` files into
RUNS_FINISHED one at a time and writes the ``-exp.yml`` only after the last
one, so SYNC's startup sweep of RUNS_FINISHED can land mid-conversion.
"""

import asyncio
from pathlib import Path

import pytest

from helao.core.drivers.data.sync_driver import HelaoYml, SyncDriver
from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver


def _orphan_action(tmp_path: Path) -> Path:
    """An action under RUNS_FINISHED whose experiment yml has not been written."""
    act_dir = (
        tmp_path
        / "RUNS_FINISHED"
        / "26.35"
        / "0828"
        / "seqdir"
        / "expdir"
        / "0__0__SIM__do_thing"
    )
    act_dir.mkdir(parents=True)
    act = act_dir / "260828.120001000000-act.yml"
    act.write_text(
        "action_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\n"
        "action_order: 0\n"
        "process_contrib:\n- files\n"
    )
    return act


def test_parent_yml_is_none_when_the_experiment_yml_is_missing(tmp_path):
    assert HelaoYml(_orphan_action(tmp_path)).parent_yml is None


def test_parent_path_raises_instead_of_indexing_an_empty_list(tmp_path):
    with pytest.raises(FileNotFoundError):
        HelaoYml(_orphan_action(tmp_path)).parent_path


def test_sync_yml_defers_an_orphan_action_and_leaves_it_in_finished(tmp_path):
    act = _orphan_action(tmp_path)

    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        uploads = []
        driver.to_s3 = lambda *a, **k: uploads.append(a)  # must never be reached
        try:
            return await driver.sync_yml(yml_path=act), uploads
        finally:
            await teardown_driver(driver)

    result, uploads = asyncio.run(_run())
    assert result is False
    assert uploads == [], "an orphan must not be uploaded"
    assert act.exists(), "an orphan must stay in RUNS_FINISHED"


def test_an_action_with_its_experiment_present_still_syncs_past_the_gate(tmp_path):
    act = _orphan_action(tmp_path)
    exp_dir = act.parent.parent
    (exp_dir / "260828.120000000000-exp.yml").write_text(
        "experiment_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    assert HelaoYml(act).parent_yml is not None
