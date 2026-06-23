"""Pure ``Progress`` value object + push-condition predicate.

Ported from the legacy syncer (``helao/core/drivers/data/sync_driver.py``,
``Progress`` class lines 509-650 and ``sync_process`` lines 1504-1577) with all
disk I/O removed. ``Progress`` holds the ``.prg`` sidecar payload as a plain
dict whose schema is byte-identical to the legacy syncer; reading and writing
that payload to disk is the storage adapter's job in a later wave.

This module is part of the PURE ``domain/`` layer: stdlib only, no I/O.
"""
from copy import deepcopy
from dataclasses import dataclass


@dataclass
class Progress:
    """Sync state for one ``HelaoYml``, as a pure value object.

    Mirrors the legacy ``.prg`` sidecar payload. The first-time defaults are
    produced by :meth:`initial` and differ for ``action`` vs ``experiment``
    node types (matching legacy ``Progress.__init__`` lines 569-591). All
    updaters return a NEW ``Progress`` instead of mutating in place.

    Attributes:
        yml_relpath: Relative path of the parent yml (legacy ``ymlpath``).
        dict_: In-memory copy of the progress dict (legacy ``dict``).
    """

    yml_relpath: str
    dict_: dict

    @classmethod
    def initial(cls, yml_relpath: str, node_type: str, meta: dict) -> "Progress":
        """Build the default progress dict for a freshly-seen yml.

        Equivalent to the legacy ``Progress.__init__`` default-dict branch
        (lines 569-591). The base keys (``yml``/``api``/``s3``) are always
        present; ``action`` ymls add ``files_pending``/``files_s3`` and
        ``experiment`` ymls add the per-process bookkeeping fields.

        Args:
            yml_relpath: Relative path of the parent yml.
            node_type: ``"action"``, ``"experiment"``, or other.
            meta: The yml's metadata dict. ``meta["yml"]`` becomes the stored
                ``yml`` target; for experiments ``meta["process_order_groups"]``
                seeds ``process_groups``.

        Returns:
            A new ``Progress`` with the legacy default schema.
        """
        d: dict = {
            "yml": meta["yml"],
            "api": False,
            "s3": False,
        }
        if node_type == "action":
            d.update(
                {
                    "files_pending": [],
                    "files_s3": {},
                }
            )
        if node_type == "experiment":
            process_groups = deepcopy(meta.get("process_order_groups", {}))
            d.update(
                {
                    "process_actions_done": {},  # {action submit order: yml.target.name}
                    "process_groups": process_groups,  # {process_idx: contributor action indices}
                    "process_metas": {},  # {process_idx: yml_dict}
                    "process_s3": [],  # list of process_idx with S3 done
                    "process_api": [],  # list of process_idx with API done
                    "legacy_finisher_idxs": [],  # end action indicies (submit order)
                    "legacy_experiment": False if process_groups else True,
                }
            )
        return cls(yml_relpath=yml_relpath, dict_=d)

    @classmethod
    def from_dict(cls, yml_relpath: str, d: dict) -> "Progress":
        """Wrap an existing ``.prg`` payload (e.g. read back from storage).

        The input dict is deep-copied so the caller cannot mutate the
        ``Progress`` through an aliased reference.
        """
        return cls(yml_relpath=yml_relpath, dict_=deepcopy(d))

    def to_dict(self) -> dict:
        """Return a deep copy of the progress payload (never the internal ref)."""
        return deepcopy(self.dict_)

    @property
    def s3_done(self) -> bool:
        """Whether the yml has been pushed to S3 (legacy ``self.dict["s3"]``)."""
        return self.dict_["s3"]

    @property
    def api_done(self) -> bool:
        """Whether the yml is registered with the API (legacy ``self.dict["api"]``)."""
        return self.dict_["api"]

    def list_unfinished_procs(self) -> tuple[list, list]:
        """Return ``(s3_unfinished, api_unfinished)`` process-group indices.

        For experiment ymls (those carrying ``process_groups``), returns the
        process group keys not yet flagged in ``process_s3`` / ``process_api``.
        For other yml types both lists are empty. Mirrors legacy lines 603-621
        but keyed off the presence of ``process_groups`` rather than re-reading
        the yml type from disk.
        """
        if "process_groups" in self.dict_:
            s3_unf = [
                x
                for x in self.dict_["process_groups"].keys()
                if x not in self.dict_["process_s3"]
            ]
            api_unf = [
                x
                for x in self.dict_["process_groups"].keys()
                if x not in self.dict_["process_api"]
            ]
            return s3_unf, api_unf
        return [], []

    def with_s3_done(self, value: bool = True) -> "Progress":
        """Return a new ``Progress`` with ``dict["s3"]`` set to ``value``."""
        new_dict = deepcopy(self.dict_)
        new_dict["s3"] = value
        return Progress(yml_relpath=self.yml_relpath, dict_=new_dict)

    def with_api_done(self, value: bool = True) -> "Progress":
        """Return a new ``Progress`` with ``dict["api"]`` set to ``value``."""
        new_dict = deepcopy(self.dict_)
        new_dict["api"] = value
        return Progress(yml_relpath=self.yml_relpath, dict_=new_dict)


def should_push_process(
    pidx,
    process_groups: dict,
    process_actions_done: dict,
    is_legacy: bool,
    finisher_idxs: list,
    force: bool,
    process_metas: dict | None = None,
) -> bool:
    """Pure push-condition gate for one experiment process group.

    Extracted verbatim from legacy ``sync_process`` lines 1523-1534:

    * ``force`` overrides everything.
    * legacy experiment: the max contributing action index is in
      ``finisher_idxs`` AND every contributing action is done.
    * modern experiment: every contributing action is done AND the process
      metadata for ``pidx`` is non-empty.

    Args:
        pidx: Process group index being evaluated.
        process_groups: ``{process_idx: [action indices]}``.
        process_actions_done: ``{action_idx: name}`` of completed actions.
        is_legacy: Whether this is a legacy experiment.
        finisher_idxs: Legacy end-action indices (submit order).
        force: Push even if completion conditions aren't met.
        process_metas: ``{process_idx: meta dict}`` (modern branch only).

    Returns:
        Whether the process group is ready to push.
    """
    if force:
        return True
    gids = process_groups[pidx]
    if is_legacy:
        return max(gids) in finisher_idxs and all(
            i in process_actions_done for i in gids
        )
    metas = process_metas or {}
    return all(i in process_actions_done for i in gids) and metas.get(pidx, {}) != {}
