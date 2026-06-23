"""Pure process-folding logic ported from the legacy syncer.

Ports the body of ``HelaoSyncer.update_process``
(``helao/core/drivers/data/sync_driver.py`` lines 1354-1502) with all disk I/O
and ``Progress`` storage removed. The caller (``app`` layer) reads the parent
experiment's ``.prg`` payload, calls :func:`fold_action_into_process`, and writes
the returned dict back.

The legacy ``update_process`` bifurcates on ``legacy_experiment``:

* **legacy** (no explicit ``process_groups``) — the action's *finisher index*
  acts as a proxy for the process group. Finishers are accumulated in
  ``legacy_finisher_idxs`` and the contributing action is appended to a computed
  group; the legacy branch builds **no** ``process_metas`` (lines 1375-1390).
* **modern** (``process_groups`` populated from ``process_order_groups``) — the
  process group is looked up directly, a process-meta dict is constructed if
  absent, ``process_contrib`` keys are merged, and ``samples_in``/``samples_out``
  are deduplicated (lines 1391-1501).

All functions are PURE: stdlib + ``helao.framework.models`` only, no I/O, no
asyncio, no randomness. Any UUID generation is INJECTED via a ``gen_uuid``
callable so the domain stays deterministic. Inputs are never mutated; updaters
operate on copies and return new dicts.
"""
from collections import defaultdict
from copy import deepcopy

from helao.framework.models.action import ShortActionModel


# experiment-level fields copied verbatim into a fresh process meta
# (legacy lines 1398-1414).
_PROCESS_META_COPY_KEYS = (
    "sequence_uuid",
    "experiment_uuid",
    "orchestrator",
    "access",
    "dummy",
    "simulation",
    "run_type",
    "campaign_name",
    "campaign_uuid",
    "run_id",
)


def find_process_group_index(action_order, process_groups, is_legacy, finisher_idxs):
    """Resolve the process-group index a contributing action belongs to.

    Modern experiments (``is_legacy`` False) look up ``process_groups`` for the
    group whose contributor list contains ``action_order`` (legacy lines
    1392-1394). Legacy experiments use the finisher-index proxy (lines 1382-1386):
    if the action runs after every finisher it opens a new group at
    ``len(finisher_idxs)``; otherwise it joins the group of the smallest finisher
    ``>= action_order``.

    Args:
        action_order: The action's submit order (legacy ``action_order``).
        process_groups: ``{process_idx: [action indices]}`` (modern only).
        is_legacy: Whether the parent experiment is a legacy experiment.
        finisher_idxs: Sorted finisher action indices (legacy only).

    Returns:
        The integer process-group index.
    """
    if is_legacy:
        pf_idxs = finisher_idxs
        if action_order > max(pf_idxs + [-1]):
            return len(pf_idxs)
        return pf_idxs.index(min(x for x in pf_idxs if x >= action_order))
    return [k for k, l in process_groups.items() if action_order in l][0]


def make_process_meta(exp_meta, process_list, pidx, action_meta, gen_uuid=None):
    """Build a fresh process-meta dict for ``pidx`` (legacy lines 1396-1434).

    Copies the experiment-level identity fields, derives ``process_params`` /
    ``technique_name``, sets ``process_uuid`` (from ``process_list[pidx]`` when a
    process list is present, otherwise from the injected ``gen_uuid`` callable),
    and seeds the per-process bookkeeping fields.

    Args:
        exp_meta: The parent experiment metadata dict (legacy ``yml.meta``).
        process_list: Pre-assigned process UUIDs, or empty/None to derive one.
        pidx: Process-group index this meta describes.
        action_meta: The contributing action's metadata (unused for the fresh
            meta itself but accepted to mirror the legacy signature).
        gen_uuid: Callable ``str -> uuid``-like used only when ``process_list`` is
            empty. Must be supplied in that case (the domain never generates
            randomness itself).

    Returns:
        A new process-meta dict.
    """
    process_meta = {
        k: deepcopy(exp_meta[k]) for k in _PROCESS_META_COPY_KEYS if k in exp_meta
    }
    if "data_request_id" in exp_meta:
        process_meta["data_request_id"] = deepcopy(exp_meta["data_request_id"])
    process_meta["process_params"] = deepcopy(exp_meta.get("experiment_params", {}))
    process_meta["technique_name"] = exp_meta.get(
        "technique_name", exp_meta["experiment_name"]
    )
    if process_list:
        process_uuid = process_list[pidx]
    else:
        process_input_str = f"{exp_meta['experiment_uuid']}__{pidx}"
        if gen_uuid is None:
            raise ValueError(
                "gen_uuid must be provided when process_list is empty "
                "(domain layer cannot generate randomness)"
            )
        process_uuid = str(gen_uuid(process_input_str))
    process_meta["process_uuid"] = process_uuid
    process_meta["process_group_index"] = pidx
    process_meta["dispatched_actions_abbr"] = []
    return process_meta


def merge_process_contrib(process_meta, action_meta, contrib_keys):
    """Merge an action's ``process_contrib`` fields into a process meta.

    Ports legacy lines 1453-1465 (the merge half only; sample dedup is
    :func:`deduplicate_samples`). For each contrib key present on the action, the
    ``action_*`` name is rewritten to ``process_*`` and merged: dicts are
    ``update``-d, lists are extended, scalars (and first-seen values) replace.

    Args:
        process_meta: The current process meta (not mutated).
        action_meta: The contributing action metadata.
        contrib_keys: The action's ``process_contrib`` list.

    Returns:
        A NEW process-meta dict with the contributions merged.
    """
    out = deepcopy(process_meta)
    for pc in contrib_keys:
        if pc not in action_meta:
            continue
        contrib = action_meta[pc]
        new_name = pc.replace("action_", "process_")
        if new_name not in out:
            out[new_name] = deepcopy(contrib)
        elif isinstance(contrib, dict):
            out[new_name].update(deepcopy(contrib))
        elif isinstance(contrib, list):
            out[new_name] += deepcopy(contrib)
        else:
            out[new_name] = contrib
    return out


def deduplicate_samples(sample_list, dispatched_actions_abbr, is_input):
    """Deduplicate a process sample list by ``global_label``.

    Ports legacy lines 1467-1496. Each sample is keyed by ``global_label``; for a
    given label the survivor is chosen by action order (derived from the matching
    dispatched action's ``orch_submit_order``, falling back to list position when
    no dispatched action matches the sample's ``action_uuid``). ``samples_in``
    keeps the EARLIEST contributor, ``samples_out`` the LATEST.

    Args:
        sample_list: The merged sample dicts (``process_samples_in/out``).
        dispatched_actions_abbr: The process meta's dispatched-action records,
            each with ``action_uuid`` and ``orch_submit_order``.
        is_input: True for ``samples_in`` (earliest), False for ``samples_out``
            (latest).

    Returns:
        A NEW list of deduplicated sample dicts. If nothing was labeled the
        input is returned unchanged (deep-copied), matching legacy's behavior of
        only overwriting when ``deduped_samples`` is non-empty.
    """
    actuuid_order = {
        x["action_uuid"]: x["orch_submit_order"] for x in dispatched_actions_abbr
    }
    dedupe_dict = defaultdict(list)
    for si, x in enumerate(sample_list):
        sample_label = x.get("global_label", False)
        if not sample_label:
            continue
        actuuid = [y for y in x["action_uuid"] if y in actuuid_order]
        if not actuuid:
            actorder = si
        else:
            actorder = actuuid_order[actuuid[0]]
        dedupe_dict[sample_label].append((actorder, si))

    if is_input:
        deduped = [sample_list[min(v)[1]] for v in dedupe_dict.values()]
    else:
        deduped = [sample_list[max(v)[1]] for v in dedupe_dict.values()]

    if deduped:
        return deepcopy(deduped)
    return deepcopy(sample_list)


def fold_action_into_process(exp_meta, prg_dict, act_meta, *, gen_uuid=None):
    """Fold a finished action into its parent experiment's process bookkeeping.

    Top-level composition mirroring the body of legacy ``update_process``
    (lines 1373-1502). Returns a NEW prg dict; ``exp_meta``, ``prg_dict``, and
    ``act_meta`` are never mutated.

    Legacy experiments (``prg_dict["legacy_experiment"]``) record finishers and
    append the action to a computed process group but build no ``process_metas``.
    Modern experiments look up the group, build/extend the process meta, merge
    contribs, dedup samples, and record the action.

    Args:
        exp_meta: Parent experiment metadata dict.
        prg_dict: The experiment's ``.prg`` payload.
        act_meta: The finished contributing action's metadata.
        gen_uuid: Callable ``str -> uuid``-like, injected for deterministic UUID
            derivation (modern branch, no process list).

    Returns:
        The updated ``.prg`` payload (new dict).
    """
    prg = deepcopy(prg_dict)
    act_idx = act_meta["action_order"]

    if prg["legacy_experiment"]:
        # legacy 1375-1390: finisher-index proxy, no process meta build
        if act_meta["process_finish"]:
            prg["legacy_finisher_idxs"] = sorted(
                set(prg["legacy_finisher_idxs"]).union([act_idx])
            )
        pf_idxs = prg["legacy_finisher_idxs"]
        pidx = find_process_group_index(
            act_idx, prg["process_groups"], is_legacy=True, finisher_idxs=pf_idxs
        )
        prg["process_groups"][pidx] = prg["process_groups"].get(pidx, [])
        prg["process_groups"][pidx].append(act_idx)
        return prg

    # modern branch (legacy 1391-1501)
    pidx = find_process_group_index(
        act_idx, prg["process_groups"], is_legacy=False, finisher_idxs=[]
    )

    if pidx not in prg["process_metas"]:
        process_list = exp_meta.get("process_list", [])
        process_meta = make_process_meta(
            exp_meta, process_list, pidx, act_meta, gen_uuid=gen_uuid
        )
    else:
        process_meta = deepcopy(prg["process_metas"][pidx])

    # record the action (legacy 1440-1442)
    process_meta["dispatched_actions_abbr"].append(
        ShortActionModel(**act_meta).clean_dict(strip_private=True)
    )

    # first action in the group sets the process timestamp (legacy 1445-1446)
    if act_idx == min(prg["process_groups"][pidx]):
        process_meta["process_timestamp"] = act_meta["action_timestamp"]

    # technique-name resolution (legacy 1447-1452)
    if "technique_name" in act_meta:
        process_meta["technique_name"] = act_meta["technique_name"]
    tech_name = process_meta["technique_name"]
    if isinstance(tech_name, list):
        process_meta["technique_name"] = tech_name[act_meta.get("action_split", 0)]

    # merge process_contrib (legacy 1453-1465)
    process_meta = merge_process_contrib(
        process_meta, act_meta, act_meta["process_contrib"]
    )

    # dedup sample lists (legacy 1466-1496). NOTE legacy keys the dedup on the
    # POST-rewrite ``new_name`` checked against the bare strings "samples_in" /
    # "samples_out" (line 1467). Because ``new_name = pc.replace("action_",
    # "process_")``, this only fires when the contrib key is the *bare*
    # "samples_in"/"samples_out" (no ``action_`` prefix to rewrite), under which
    # the merged field is also stored unprefixed. This faithfully reproduces
    # that behavior.
    for key, is_input in (("samples_in", True), ("samples_out", False)):
        if key in act_meta.get("process_contrib", []) and key in process_meta:
            process_meta[key] = deduplicate_samples(
                process_meta[key],
                process_meta["dispatched_actions_abbr"],
                is_input=is_input,
            )

    # register finished action (legacy 1497-1500)
    prg["process_metas"][pidx] = process_meta
    prg["process_actions_done"][act_idx] = act_meta["action_name"]
    return prg
