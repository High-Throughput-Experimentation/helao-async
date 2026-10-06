"""Test builders for the sequence-retire logic (see helao/ui/shared/retire.py)."""

import os


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
