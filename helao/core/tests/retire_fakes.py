"""Test builders for the sequence-retire logic (see helao/ui/shared/retire.py)."""

import os

import httpx


def _write(path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def make_run_tree(
    root: str,
    run_tree: str,
    rel_dir: str,
    *,
    sequence_uuid: str,
    label: str = "",
    name: str = "SEQ",
    campaign: str = "",
    experiments: dict[str, list[tuple[str, str | None]]] = {},
) -> str:
    """Write <root>/<run_tree>/<rel_dir>/<ts>-seq.yml plus exp and act children.

    experiments maps experiment_uuid -> [(action_uuid, process_uuid or None)].
    The seq yml carries an indented embedded ``sequence_uuid`` block ahead of the
    top-level line, so only an anchored scan finds the right one.
    Returns the seq-dir path.
    """
    seq_dir = os.path.join(root, run_tree, *rel_dir.split("/"))
    lines = [
        "experiment_list:",
        "- experiment_name: embedded",
        "  sequence_uuid: 00000000-embedded",
    ]
    if label:
        lines.append(f"  sequence_label: embedded-{label}")
        lines.append(f"sequence_label: {label}")
    lines += [f"sequence_name: {name}", f"sequence_uuid: {sequence_uuid}"]
    if campaign:
        lines.append(f"campaign_name: {campaign}")
    _write(os.path.join(seq_dir, "20261001.000000-seq.yml"), lines)
    for i, (exp_uuid, acts) in enumerate(experiments.items()):
        exp_dir = os.path.join(seq_dir, f"{i}__exp")
        _write(
            os.path.join(exp_dir, f"{i}-exp.yml"),
            ["  experiment_uuid: embedded", f"experiment_uuid: {exp_uuid}"],
        )
        for j, (act_uuid, proc_uuid) in enumerate(acts):
            _write(
                os.path.join(exp_dir, f"{j}__act", f"{j}-act.yml"),
                [
                    f"action_uuid: {act_uuid}",
                    f"process_uuid: {'null' if proc_uuid is None else proc_uuid}",
                ],
            )
    return seq_dir


class FakeMetadataClient:
    """In-memory stand-in for the metadata client, with the real error formats.

    rows: entity_type -> uuids present. fail: (op_name, uuid) -> "404" | "500" |
    "504" | "timeout", op_name e.g. "read_sequence" or "delete_command". persist:
    uuids whose delete is acknowledged but whose row stays. calls: ("delete",
    entity_type, uuid) in order. cascade: (entity_type, uuid) ->
    delete_connected_processes as passed.
    sequence_body: body returned by read_sequence (label/campaign fallback).
    """

    def __init__(
        self,
        rows: dict[str, set[str]],
        *,
        seq_processes: dict[str, list[str]] = {},
        analyses: dict[str, list[str]] = {},
    ):
        self.rows = {t: set(u) for t, u in rows.items()}
        self.seq_processes = seq_processes
        self.analyses = analyses
        self.fail: dict[tuple[str, str], str] = {}
        self.persist: set[str] = set()
        self.calls: list[tuple[str, str, str]] = []
        self.cascade: dict[tuple[str, str], bool] = {}
        self.sequence_body: dict = {}

    def _maybe_fail(self, op: str, uuid: str) -> None:
        mode = self.fail.get((op, uuid))
        if mode == "timeout":
            try:
                raise httpx.ReadTimeout("timed out")
            except httpx.ReadTimeout:
                raise RuntimeError(
                    f"Request failed for operation '{op}' to https://fake: "
                )
        if mode:
            raise RuntimeError(
                f"API call to '{op}' (GET https://fake/api/x) failed: {mode} - "
                "Details: {'detail': '...'}"
            )

    def _read(self, entity_type: str, op: str, uuid: str) -> dict:
        self._maybe_fail(op, uuid)
        if uuid not in self.rows.get(entity_type, set()):
            self._not_found(op)
        return (
            {**self.sequence_body, "uuid": uuid}
            if entity_type == "SEQUENCE"
            else {"uuid": uuid}
        )

    @staticmethod
    def _not_found(op: str) -> None:
        raise RuntimeError(
            f"API call to '{op}' (GET https://fake/api/x) failed: 404 - "
            "Details: {'detail': 'not found'}"
        )

    async def read_sequence(self, *, sequence_uuid):
        return self._read("SEQUENCE", "read_sequence", sequence_uuid)

    async def read_experiment(self, *, experiment_uuid):
        return self._read("EXPERIMENT", "read_experiment", experiment_uuid)

    async def read_action(self, *, action_uuid):
        return self._read("ACTION", "read_action", action_uuid)

    async def read_process(self, *, process_uuid):
        return self._read("PROCESS", "read_process", process_uuid)

    async def read_analysis(self, *, analysis_uuid):
        return self._read("ANALYSIS", "read_analysis", analysis_uuid)

    async def read_processes_by_sequence(self, *, sequence_uuid):
        self._maybe_fail("read_processes_by_sequence", sequence_uuid)
        return [{"process_uuid": u} for u in self.seq_processes.get(sequence_uuid, [])]

    async def read_analysis_by_process(self, *, process_uuid):
        self._maybe_fail("read_analysis_by_process", process_uuid)
        return [{"analysis_uuid": u} for u in self.analyses.get(process_uuid, [])]

    async def delete_command(
        self, *, entity_type, primary_id, delete_connected_processes
    ):
        self.calls.append(("delete", entity_type, primary_id))
        self.cascade[(entity_type, primary_id)] = delete_connected_processes
        self._maybe_fail("delete_command", primary_id)
        if primary_id not in self.rows.get(entity_type, set()):
            self._not_found("delete_command")
        if primary_id not in self.persist:
            self.rows[entity_type].discard(primary_id)
        return {"deleted": primary_id}
