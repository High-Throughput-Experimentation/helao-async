"""Unit tests for the Action/Experiment/Sequence model + premodel layer.

Exercises the pydantic models under ``helao.core.models`` plus the runtime
``Action``/``Experiment``/``Sequence`` classes in
``helao.helpers.premodels`` that the orchestrator builds work units from.
Verifies field defaults, the ``ActionModel.url`` property, the
``init_seq``/``init_exp``/``init_act`` lifecycle helpers, the manual-action
promotion path, the output-directory layout helpers, and round-tripping
through ``model_dump``/``HelaoDict.as_dict``.
"""

__all__ = ["action_experiment_sequence_unit_test"]

import traceback
from datetime import datetime
from uuid import UUID

from helao.core.models.action import ActionModel, ShortActionModel
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.file import FileInfo
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.sequence import SequenceModel, ShortSequenceModel
from helao.helpers.premodels import Action, Experiment, Sequence

from helao.core.tests._test_utils import TestReporter


def action_experiment_sequence_unit_test() -> bool:
    """Run all action/experiment/sequence assertions and report pass/fail."""
    reporter = TestReporter("action_experiment_sequence")

    try:
        reporter.section("ActionModel defaults and url")

        am = ActionModel(
            action_name="run_thing",
            action_server=MachineModel(
                server_name="DRV", hostname="127.0.0.1", port=8123
            ),
        )

        reporter.check(
            "ActionModel.url builds http://host:port/server/name",
            lambda: am.url == "http://127.0.0.1:8123/DRV/run_thing",
        )
        reporter.check(
            "ActionModel default start_condition is wait_for_all",
            lambda: am.start_condition == ActionStartCondition.wait_for_all,
        )
        reporter.check(
            "ActionModel default save_act/save_data are True",
            lambda: am.save_act and am.save_data,
        )
        reporter.check(
            "ActionModel default action_status is empty list",
            lambda: am.action_status == [],
        )
        reporter.check(
            "ActionModel inherits ShortActionModel",
            lambda: isinstance(am, ShortActionModel),
        )

        reporter.section("ShortActionModel default factory")
        sm = ShortActionModel()
        reporter.check(
            "ShortActionModel.hlo_version is populated by default factory",
            lambda: isinstance(sm.hlo_version, str) and len(sm.hlo_version) > 0,
        )

        reporter.section("ExperimentModel + ShortExperimentModel defaults")
        sem = ShortExperimentModel(experiment_name="exp")
        em = ExperimentModel(experiment_name="exp")
        reporter.check(
            "ExperimentModel inherits ShortExperimentModel",
            lambda: isinstance(em, ShortExperimentModel),
        )
        reporter.check(
            "ExperimentModel default access is 'hte'", lambda: em.access == "hte"
        )
        reporter.check(
            "ExperimentModel default dummy/simulation are False",
            lambda: not em.dummy and not em.simulation,
        )
        reporter.check(
            "ShortExperimentModel exposes experiment_params dict",
            lambda: sem.experiment_params == {},
        )

        reporter.section("SequenceModel + ShortSequenceModel defaults")
        ssm = ShortSequenceModel(sequence_name="seq")
        smod = SequenceModel(sequence_name="seq")
        reporter.check(
            "SequenceModel inherits ShortSequenceModel",
            lambda: isinstance(smod, ShortSequenceModel),
        )
        reporter.check(
            "SequenceModel default sequence_label is 'noLabel'",
            lambda: smod.sequence_label == "noLabel",
        )
        reporter.check(
            "ShortSequenceModel planned_experiments default empty",
            lambda: ssm.planned_experiments == [],
        )

        reporter.section("MachineModel helpers")
        mm = MachineModel(
            server_name="A", machine_name="host1", hostname="127.0.0.1", port=8000
        )
        reporter.check(
            "MachineModel.as_key returns (server_name, machine_name)",
            lambda: mm.as_key() == ("A", "host1"),
        )
        reporter.check(
            "MachineModel.disp_name returns 'server@machine'",
            lambda: mm.disp_name() == "A@host1",
        )

        reporter.section("Sequence runtime helpers")
        seq = Sequence(sequence_name="my_seq", sequence_label="lab")
        seq.init_seq()
        reporter.check(
            "init_seq populates sequence_timestamp",
            lambda: isinstance(seq.sequence_timestamp, datetime),
        )
        reporter.check(
            "init_seq populates sequence_uuid as UUID",
            lambda: isinstance(seq.sequence_uuid, UUID),
        )
        reporter.check(
            "init_seq sets status to [active]",
            lambda: seq.sequence_status == [HloStatus.active],
        )
        reporter.check(
            "Sequence.get_seq returns plain SequenceModel",
            lambda: type(seq.get_seq()) is SequenceModel,
        )

        seq_dir = seq.get_sequence_dir()
        reporter.check(
            "get_sequence_dir contains the sequence_name and label",
            lambda: "my_seq" in seq_dir and "lab" in seq_dir,
        )

        # force should overwrite even when fields are populated
        original_uuid = seq.sequence_uuid
        seq.init_seq(force=True)
        reporter.check(
            "init_seq(force=True) replaces sequence_uuid",
            lambda: seq.sequence_uuid != original_uuid,
        )

        reporter.section("Experiment runtime helpers")
        exp = Experiment(
            sequence_name="my_seq",
            sequence_label="lab",
            experiment_name="my_exp",
            experiment_params={
                "is_on": "true",  # string coercion happens in ActionPlanMaker, not here
            },
        )
        exp.init_seq()
        exp.init_exp()
        reporter.check(
            "init_exp populates experiment_timestamp",
            lambda: isinstance(exp.experiment_timestamp, datetime),
        )
        reporter.check(
            "init_exp populates experiment_uuid as UUID",
            lambda: isinstance(exp.experiment_uuid, UUID),
        )
        reporter.check(
            "get_experiment_dir nests under sequence_output_dir",
            lambda: exp.get_experiment_dir().startswith(str(exp.sequence_output_dir)),
        )
        reporter.check(
            "get_experiment_dir includes experiment_name",
            lambda: "my_exp" in exp.get_experiment_dir(),
        )
        plain_exp = exp.get_exp()
        reporter.check(
            "Experiment.get_exp returns plain ExperimentModel",
            lambda: type(plain_exp) is ExperimentModel,
        )

        reporter.section("Action manual promotion via init_act")
        manual = Action(action_name="ping", action_server=MachineModel(server_name="X"))
        # no parent sequence/experiment -> promote to a manual run
        manual.init_act()
        reporter.check(
            "Action without parent timestamps becomes manual_action",
            lambda: manual.manual_action is True,
        )
        reporter.check(
            "Manual action access set to 'manual'", lambda: manual.access == "manual"
        )
        reporter.check(
            "Manual action sequence_name uses 'seq--<action>' template",
            lambda: manual.sequence_name == "seq--ping",
        )
        reporter.check(
            "Manual action experiment_name uses 'exp--<action>' template",
            lambda: manual.experiment_name == "exp--ping",
        )
        reporter.check(
            "init_act assigns action_uuid",
            lambda: isinstance(manual.action_uuid, UUID),
        )
        reporter.check(
            "init_act sets action_status to [active]",
            lambda: manual.action_status == [HloStatus.active],
        )
        reporter.check(
            "get_action_dir nests under experiment_output_dir",
            lambda: manual.get_action_dir().startswith(
                str(manual.experiment_output_dir)
            ),
        )
        reporter.check(
            "Action.get_act returns plain ActionModel",
            lambda: type(manual.get_act()) is ActionModel,
        )

        reporter.section("Non-manual Action keeps parent identity")
        parent_seq = Sequence(sequence_name="seqp", sequence_label="lab")
        parent_seq.init_seq()
        child_exp = Experiment(
            **parent_seq.model_dump(),
            experiment_name="expp",
        )
        child_exp.init_exp()
        child_act = Action(
            **child_exp.model_dump(),
            action_name="run",
            action_server=MachineModel(server_name="S"),
        )
        child_act.init_act()
        reporter.check(
            "Action with parent timestamps does not become manual",
            lambda: child_act.manual_action is False,
        )
        reporter.check(
            "Child action inherits sequence_name from parent",
            lambda: child_act.sequence_name == "seqp",
        )
        reporter.check(
            "Child action inherits experiment_uuid from parent",
            lambda: child_act.experiment_uuid == child_exp.experiment_uuid,
        )

        reporter.section("ActionModel <-> dict round-trip")
        am2 = ActionModel(
            action_name="echo",
            action_server=MachineModel(server_name="A", hostname="h", port=1),
            files=[FileInfo(file_name="out.hlo", file_type="helao__file")],
        )
        dumped = am2.as_dict()
        reporter.check(
            "ActionModel.as_dict has files entry with file_name",
            lambda: dumped["files"][0]["file_name"] == "out.hlo",
        )
        rebuilt = ActionModel(**am2.model_dump())
        reporter.check(
            "ActionModel rebuilt from model_dump preserves url",
            lambda: rebuilt.url == am2.url,
        )

        reporter.section("Experiment._experiment_update_from_actlist aggregates files")
        exp2 = Experiment(
            sequence_name="seqp",
            sequence_label="lab",
            experiment_name="aggregator",
        )
        exp2.init_seq()
        exp2.init_exp()
        a1 = Action(
            **exp2.model_dump(),
            action_name="step1",
            action_server=MachineModel(server_name="A"),
        )
        a1.init_act()
        a1.files = [FileInfo(file_name="f1.hlo")]
        a2 = Action(
            **exp2.model_dump(),
            action_name="step2",
            action_server=MachineModel(server_name="B"),
        )
        a2.init_act()
        a2.files = [FileInfo(file_name="f2.hlo")]
        exp2.dispatched_actions = [a1, a2]
        flat_exp = exp2.get_exp()
        reporter.check(
            "get_exp aggregates files across dispatched_actions",
            lambda: {f.file_name for f in flat_exp.files} == {"f1.hlo", "f2.hlo"},
        )
        reporter.check(
            "get_exp populates dispatched_actions_abbr",
            lambda: len(flat_exp.dispatched_actions_abbr) == 2,
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
