"""Tests for the pure action-lifecycle functions (domain/lifecycle.py).

These functions port ``init_act``/``init_seq``/``init_exp``/``get_*_dir``/``split``
from ``helao.helpers.premodels``, but the wall clock and uuid are INJECTED as
arguments (``now=``/``uuid=``) and never read internally — so output is
deterministic given fixed inputs. The directory strings must reproduce the legacy
path strings byte-for-byte.
"""

from datetime import datetime
from uuid import UUID

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.commands import ActionInit, SplitResult
from helao.framework.domain.lifecycle import (
    init_action,
    action_output_dir,
    experiment_output_dir,
    sequence_output_dir,
    split_action,
    meta_doc,
)

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FIXED_SEQ_UUID = UUID("00000000-0000-0000-0000-0000000000bb")
FIXED_EXP_UUID = UUID("00000000-0000-0000-0000-0000000000cc")


# --- dir functions: byte-for-byte legacy strings -------------------------------


def test_sequence_output_dir_plain():
    a = RunAction(
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
    )
    # YY.WW / MMDD / HHMMSS__name__label
    assert sequence_output_dir(a) == "26.25/0622/140506__myseq__lab1"


def test_sequence_output_dir_with_plate_and_sample():
    a = RunAction(
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        sequence_params={"plate_id": 6321, "plate_sample_no_list": [42]},
    )
    # serial = plate + (digitsum % 10); 6+3+2+1=12 -> 2 -> "63212"; one sample -> -42
    assert sequence_output_dir(a) == "26.25/0622/140506__myseq__lab1-63212-42"


def test_sequence_output_dir_with_plate_multi_sample():
    a = RunAction(
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        sequence_params={"plate_id": 6321, "plate_sample_no_list": [1, 2]},
    )
    assert sequence_output_dir(a) == "26.25/0622/140506__myseq__lab1-63212"


def test_experiment_output_dir():
    a = RunAction(
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        experiment_timestamp=FIXED_NOW,
        experiment_name="myexp",
    )
    a.sequence_output_dir = sequence_output_dir(a)
    # sequence_dir / YYMMDD.HHMMSS__experiment_name
    assert experiment_output_dir(a) == "26.25/0622/140506__myseq__lab1/260622.140506__myexp"


def test_action_output_dir():
    a = RunAction(
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        experiment_timestamp=FIXED_NOW,
        experiment_name="myexp",
        action_name="myact",
        orch_submit_order=3,
        action_split=0,
    )
    a.action_server.server_name = "srv"
    a.sequence_output_dir = sequence_output_dir(a)
    a.experiment_output_dir = experiment_output_dir(a)
    # experiment_dir / {orch_submit_order}__{action_split}__{server_name}__{action_name}
    assert action_output_dir(a) == (
        "26.25/0622/140506__myseq__lab1/260622.140506__myexp/3__0__srv__myact"
    )


# --- init_action: deterministic, with injected clock+uuid ----------------------


def test_init_action_assigns_identity_deterministically():
    a = RunAction(
        action_name="myact",
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        experiment_timestamp=FIXED_NOW,
        experiment_name="myexp",
        orch_submit_order=0,
    )
    a.action_server.server_name = "srv"
    a.sequence_output_dir = sequence_output_dir(a)
    a.experiment_output_dir = experiment_output_dir(a)

    result = init_action(a, now=FIXED_NOW, uuid=FIXED_UUID)
    assert isinstance(result, ActionInit)
    run = result.action
    assert run.action_timestamp == FIXED_NOW
    assert run.action_uuid == FIXED_UUID
    assert run.action_status == [HloStatus.active]
    assert run.action_output_dir == action_output_dir(a)
    assert result.manual is False


def test_init_action_is_deterministic_no_wallclock():
    """Calling twice with the same injected inputs yields identical output."""
    def make():
        a = RunAction(
            action_name="myact",
            sequence_timestamp=FIXED_NOW,
            sequence_name="myseq",
            sequence_label="lab1",
            experiment_timestamp=FIXED_NOW,
            experiment_name="myexp",
        )
        a.action_server.server_name = "srv"
        a.sequence_output_dir = sequence_output_dir(a)
        a.experiment_output_dir = experiment_output_dir(a)
        return a

    r1 = init_action(make(), now=FIXED_NOW, uuid=FIXED_UUID)
    r2 = init_action(make(), now=FIXED_NOW, uuid=FIXED_UUID)
    assert r1.action.model_dump() == r2.action.model_dump()


def test_init_action_auto_promotes_to_manual():
    a = RunAction(action_name="myact")  # no sequence/experiment timestamps
    a.action_server.server_name = "srv"

    result = init_action(
        a,
        now=FIXED_NOW,
        uuid=FIXED_UUID,
        seq_uuid=FIXED_SEQ_UUID,
        exp_uuid=FIXED_EXP_UUID,
    )
    run = result.action
    assert result.manual is True
    assert run.manual_action is True
    assert run.access == "manual"
    assert run.sequence_name == "seq--myact"
    assert run.experiment_name == "exp--myact"
    assert run.sequence_label == "manual"
    assert run.sequence_uuid == FIXED_SEQ_UUID
    assert run.experiment_uuid == FIXED_EXP_UUID
    assert run.sequence_timestamp == FIXED_NOW
    assert run.experiment_timestamp == FIXED_NOW
    assert run.action_uuid == FIXED_UUID
    assert run.sequence_status == [HloStatus.active]
    assert run.experiment_status == [HloStatus.active]
    # output dirs computed
    assert run.sequence_output_dir == sequence_output_dir(run)
    assert run.experiment_output_dir is not None
    assert run.action_output_dir is not None


def test_init_action_does_not_read_wallclock():
    """The function must not consult datetime.now(): if now is in the past, the
    assigned timestamp equals the injected value exactly."""
    past = datetime(2000, 1, 1, 0, 0, 0)
    a = RunAction(
        action_name="myact",
        sequence_timestamp=FIXED_NOW,
        sequence_name="s",
        sequence_label="l",
        experiment_timestamp=FIXED_NOW,
        experiment_name="e",
    )
    a.action_server.server_name = "srv"
    a.sequence_output_dir = sequence_output_dir(a)
    a.experiment_output_dir = experiment_output_dir(a)
    result = init_action(a, now=past, uuid=FIXED_UUID)
    assert result.action.action_timestamp == past


# --- split_action --------------------------------------------------------------


def _ready_action():
    a = RunAction(
        action_name="myact",
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        experiment_timestamp=FIXED_NOW,
        experiment_name="myexp",
    )
    a.action_server.server_name = "srv"
    a.sequence_output_dir = sequence_output_dir(a)
    a.experiment_output_dir = experiment_output_dir(a)
    init_action(a, now=FIXED_NOW, uuid=FIXED_UUID)
    return a


def test_split_action_returns_new_and_old_states():
    old = _ready_action()
    old_keys = [
        UUID("00000000-0000-0000-0000-0000000000f1"),
        UUID("00000000-0000-0000-0000-0000000000f2"),
    ]
    old.file_conn_keys = list(old_keys)
    new_uuid = UUID("00000000-0000-0000-0000-0000000000dd")
    new_now = datetime(2026, 6, 22, 14, 6, 7)

    result = split_action(old, now=new_now, uuid=new_uuid)
    assert isinstance(result, SplitResult)

    prev = result.prev_action
    cur = result.new_action

    # previous action marked split
    assert HloStatus.split in prev.action_status
    assert prev.data_stream_status == HloStatus.split
    assert prev.child_action_uuid == new_uuid

    # new action re-inited; split_action mutates the input in place, so the
    # pre-split value is preserved only on the prev_action snapshot
    assert cur.action_split == prev.action_split + 1
    assert cur.action_uuid == new_uuid
    assert cur.action_timestamp == new_now
    assert cur.parent_action_uuid == prev.action_uuid
    assert cur.child_action_uuid is None
    assert cur.samples_in == []
    assert cur.samples_out == []
    assert cur.files == []
    assert cur.data_stream_status == HloStatus.active

    # one open + close command per prior file conn
    assert len(result.open_file_conns) == 2
    assert len(result.close_file_conns) == 2
    assert result.close_file_conns == old_keys
    # new file conn keys land on the new action; legacy prepends each new key, so
    # the action's list is the reverse of the open-order list
    assert set(cur.file_conn_keys) == set(result.open_file_conns)
    assert cur.file_conn_keys == list(reversed(result.open_file_conns))


def test_split_action_no_prior_file_conns():
    old = _ready_action()
    old.file_conn_keys = []
    result = split_action(
        old, now=FIXED_NOW, uuid=UUID("00000000-0000-0000-0000-0000000000ee")
    )
    assert result.open_file_conns == []
    assert result.close_file_conns == []
    assert result.new_action.file_conn_keys == []


# --- meta_doc: strip null/empty attrs from exported yml (legacy clean_dict parity) ---


def test_meta_doc_strips_null_and_empty_attributes():
    """Exported -act/-exp/-seq.yml must carry no None / empty-list / empty-dict
    / empty-string attributes (matches legacy Base.write_act/exp/seq clean_dict)."""
    body = {
        "action_name": "dummy_act",
        "action_params": {"x": 1},
        "none_attr": None,
        "empty_list": [],
        "empty_dict": {},
        "empty_str": "",
        "nested": {"keep": 1, "drop": None, "also_drop": []},
        "all_empty_nested": {"a": None, "b": {}},
    }
    doc = meta_doc("action", body)

    # file_type stays first and present
    assert doc["file_type"] == "action"
    # non-empty values survive
    assert doc["action_name"] == "dummy_act"
    assert doc["action_params"] == {"x": 1}
    assert doc["nested"] == {"keep": 1}
    # null / empty values are dropped entirely (keys absent)
    for absent in (
        "none_attr",
        "empty_list",
        "empty_dict",
        "empty_str",
        "all_empty_nested",
    ):
        assert absent not in doc, f"{absent} should have been stripped"


def test_meta_doc_preserves_nonempty_collections():
    """Lists/dicts with content are kept; dicts inside a kept list are cleaned."""
    body = {
        "files": [{"name": "a.hlo", "note": None}, {"name": "b.hlo"}],
        "tags": ["x"],
    }
    doc = meta_doc("experiment", body)
    assert doc["file_type"] == "experiment"
    assert doc["tags"] == ["x"]
    # the None inside the list's dict is pruned, but both list items remain
    assert doc["files"] == [{"name": "a.hlo"}, {"name": "b.hlo"}]
