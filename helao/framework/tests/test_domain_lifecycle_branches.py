"""Branch-coverage tests for domain/lifecycle.py (Task 5.2 close-out).

Exercises the conditional branches the main lifecycle suite leaves partial:
the ``serial already in label`` skip in ``sequence_output_dir``; the
``force`` overwrite vs. ``already-set`` paths in ``init_action`` /
``_init_sequence`` / ``_init_experiment``; and the ``split already marked``
branch in ``split_action``. Pure functions, fixed now/uuid injected.
"""
from datetime import datetime
from uuid import UUID

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.lifecycle import (
    init_action,
    sequence_output_dir,
    split_action,
)

NOW = datetime(2026, 6, 22, 14, 5, 6)
NOW2 = datetime(2026, 6, 22, 15, 0, 0)
UID = UUID("00000000-0000-0000-0000-0000000000aa")
UID2 = UUID("00000000-0000-0000-0000-0000000000bb")


def test_sequence_dir_skips_append_when_serial_already_in_label():
    # serial for plate 6321 is "63212"; pre-place it in the label so the
    # append branch (line 60) is skipped.
    a = RunAction(
        sequence_timestamp=NOW,
        sequence_name="myseq",
        sequence_label="lab-63212",
        sequence_params={"plate_id": 6321, "plate_sample_no_list": [42]},
    )
    assert sequence_output_dir(a) == "26.25/0622/140506__myseq__lab-63212"


def test_init_action_force_overwrites_existing_values():
    a = RunAction(
        action_name="act",
        action_uuid=UID,
        action_timestamp=NOW,
        sequence_timestamp=NOW,
        experiment_timestamp=NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_status=[HloStatus.active],
        action_output_dir="preexisting",
    )
    init_action(a, now=NOW2, uuid=UID2, force=True)
    # force=True overwrites the action-level identity
    assert a.action_timestamp == NOW2
    assert a.action_uuid == UID2
    assert a.action_output_dir != "preexisting"


def test_init_action_no_force_keeps_existing_values():
    a = RunAction(
        action_name="act",
        action_uuid=UID,
        action_timestamp=NOW,
        sequence_timestamp=NOW,
        experiment_timestamp=NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_status=[HloStatus.active],
        action_output_dir="keepme",
    )
    init_action(a, now=NOW2, uuid=UID2, force=False)
    # already-set values are preserved when force is False
    assert a.action_timestamp == NOW
    assert a.action_uuid == UID
    assert str(a.action_output_dir) == "keepme"


def test_init_action_manual_promotion_keeps_preset_seq_exp_identity():
    # No parent timestamps -> manual promotion; but pre-set seq/exp identity is
    # kept (the _init_* helpers run with force=False).
    a = RunAction(
        action_name="manualact",
        sequence_uuid=UID,
        sequence_timestamp=NOW,
        sequence_status=[HloStatus.active],
        sequence_output_dir="seqdir",
    )
    # experiment_timestamp is None -> still triggers manual
    result = init_action(a, now=NOW2, uuid=UID2)
    assert result.manual is True
    # pre-set sequence identity preserved
    assert a.sequence_uuid == UID
    assert a.sequence_timestamp == NOW


def test_split_action_when_already_marked_split():
    a = RunAction(
        action_name="act",
        action_uuid=UID,
        action_timestamp=NOW,
        sequence_timestamp=NOW,
        experiment_timestamp=NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_status=[HloStatus.active, HloStatus.split],
        action_output_dir="d",
        file_conn_keys=[],
    )
    result = split_action(a, now=NOW2, uuid=UID2)
    # prev already carried split -> not appended twice
    assert result.prev_action.action_status.count(HloStatus.split) == 1
    # no prior file connections -> nothing to open/close
    assert result.open_file_conns == []
    assert result.close_file_conns == []
