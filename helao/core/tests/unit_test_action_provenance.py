"""An analysis must not pair a process with another record set's action.

The production case, on 2026-08-16. Two conversions of one source produced two
complete record sets that share a ``sequence_output_dir`` -- that name is
derived from the source timestamp, the sequence name and the label, with
nothing to distinguish the conversion, so a second conversion of the same
source is *guaranteed* to collide. Locally one conversion's files won the
directory; both uploaded their metadata.

The analyses located a dispatched action by substring-matching the tail of
``action_output_dir`` against ``action_localpath``. A path match cannot tell
two record sets apart, so a process from set A resolved to an action from set
B. Measured across one campaign: **333 of 348 analyses resolved an action whose
uuid was not the one their own process named.** The 15 that raised did so only
because the two conversions straddled a second boundary and the directory names
differed by a digit -- those were the honest signal, and the rest were silent.

``LocalLoader.resolve_action`` checks the uuid the caller already has. These
tests pin both halves: the match still works when the record set is intact, and
it raises rather than substituting when it is not.
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from helao.core.drivers.data.loaders.localfs import (  # noqa: E402
    ActionProvenanceError,
    LocalLoader,
)

SEQ_DIR = "26.21/0530/144602__XRFS_noStandards__ZrBiMn-101967"
EXP_DIR = "260530.144641__XRFS_sub_noStandards"
ACT_DIR = "0__0__XRFS__run_XRF"
REAL_UUID = "06a7bbb4-c1de-71f0-8000-0f077f446dde"
OTHER_UUID = "06a29f36-b4a5-764c-8000-95a474e7b70e"


class _FakeAct:
    def __init__(self, uuid):
        self.json = {"action_uuid": uuid}


class _Loader(LocalLoader):
    """A LocalLoader with the indexing skipped -- only the lookup is under test.

    ``actions`` is a REAL DataFrame, not a stub: ``resolve_action`` passes a
    query expression with an ``@reldir`` reference that pandas resolves from
    the calling frame, so a hand-rolled ``query`` would have to reverse-engineer
    that and would stop testing the expression actually shipped.
    """

    def __init__(self, paths, uuids):
        self.actions = pd.DataFrame({"action_localpath": list(paths)})
        self._uuids = list(uuids)

    def get_act(self, index=None, path=None):
        return _FakeAct(self._uuids[index])


def _paths(exp_dir=EXP_DIR):
    return [f"{exp_dir}/{ACT_DIR}/260530.144641000000-act.yml"]


def test_a_matching_record_set_resolves(tmp_path=None):
    loader = _Loader(_paths(), [REAL_UUID])
    act = loader.resolve_action(REAL_UUID, f"{SEQ_DIR}/{EXP_DIR}/{ACT_DIR}")
    assert act.json["action_uuid"] == REAL_UUID


def test_the_other_record_sets_action_is_refused_not_substituted(tmp_path=None):
    """The 333 silent mismatches, made loud.

    The path matches -- that is the whole problem -- and the action sitting
    there belongs to the other conversion. Before this check the analysis
    proceeded against it and attributed another run's data to this process.
    """
    loader = _Loader(_paths(), [REAL_UUID])
    try:
        loader.resolve_action(OTHER_UUID, f"{SEQ_DIR}/{EXP_DIR}/{ACT_DIR}")
    except ActionProvenanceError as exc:
        assert REAL_UUID in str(exc) and OTHER_UUID in str(exc)
    else:
        raise AssertionError("a foreign action was accepted")


def test_a_missing_record_set_says_so_distinctly(tmp_path=None):
    """The 15 loud failures. A different remedy, so a different message.

    "the files are not here" and "the wrong files are here" are not the same
    problem: the first wants the missing conversion synced, the second wants
    the duplicate metadata sorted out.
    """
    loader = _Loader(_paths("260530.144999__XRFS_sub_noStandards"), [REAL_UUID])
    try:
        loader.resolve_action(REAL_UUID, f"{SEQ_DIR}/{EXP_DIR}/{ACT_DIR}")
    except ActionProvenanceError as exc:
        assert "no action at" in str(exc)
    else:
        raise AssertionError("a missing action was accepted")


def test_the_check_is_separable_from_ordinary_failures(tmp_path=None):
    """Its own type, so a runner can quarantine provenance faults specifically."""
    assert issubclass(ActionProvenanceError, RuntimeError)
    assert not issubclass(ActionProvenanceError, (IndexError, KeyError))


def test_windows_separators_in_the_recorded_dir_still_match(tmp_path=None):
    """``action_output_dir`` is a Path field, so it can serialise either way."""
    loader = _Loader(_paths(), [REAL_UUID])
    act = loader.resolve_action(
        REAL_UUID, f"{SEQ_DIR}\\{EXP_DIR}\\{ACT_DIR}".replace("/", "\\")
    )
    assert act.json["action_uuid"] == REAL_UUID


def action_provenance_unit_test() -> bool:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"action provenance unit test: {len(tests)}/{len(tests)} PASS")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if action_provenance_unit_test() else 1)
