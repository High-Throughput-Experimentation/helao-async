"""UUID -> stable-ordinal mapping (spec §5.5, §6.4).

Runtime uuids are uuid7 (time-seeded) and always differ between captures,
but the LINKS they encode (parent/child action uuids, FileInfo.action_uuid,
per-sample action_uuid lists, S3 key prefixes, uuid5 process derivation) are
part of the parity contract. Mapping each capture's uuids to ordinals in a
deterministic order lets the diff CHECK link structure instead of blanket-
ignoring it — the F1 countermeasure applied to identity fields.

Ordinal determinism: any uuid that appears in a FILENAME must be seeded via
harness.treepass.seed_mapper (meta files in a capture-independent sort
order) before names are normalized; `sub(strict=True)` enforces this by
raising on an unseeded uuid in a name. Content-only uuids may map lazily —
given identical normalized structure, lazy first-seen order is identical on
both sides.
"""

from __future__ import annotations

import re
import uuid as uuid_mod

RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-" r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class UuidMapper:
    """Assigns 'UUID-<n>' ordinals in first-seen order; one instance per capture."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._derived: dict[str, str] = {}

    def register_derived(
        self, raw_process_uuid: str, experiment_uuid: str, pidx
    ) -> bool:
        """Tag raw_process_uuid iff it equals uuid5(NAMESPACE_URL, exp__pidx).

        Returns True when the derivation held (spec §5.5 'exception with
        structure'); False leaves the uuid to ordinary ordinal mapping.
        """
        expected = str(
            uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"{experiment_uuid}__{pidx}")
        )
        if raw_process_uuid.lower() == expected.lower():
            exp_ordinal = self.map(experiment_uuid)
            self._derived[raw_process_uuid.lower()] = f"DERIVED:{exp_ordinal}__{pidx}"
            return True
        return False

    def known(self, raw: str) -> str:
        """Return the ordinal already assigned to ``raw``, or ``""``.

        A pure lookup: unlike :meth:`map` it never assigns an ordinal, so it is
        safe to call while DECIDING a seeding order -- assigning one there would
        make the ordinal sequence depend on the very order being computed.
        """
        key = str(raw).lower()
        return self._derived.get(key) or self._map.get(key, "")

    def map(self, raw: str) -> str:
        key = raw.lower()
        if key in self._derived:
            return self._derived[key]
        if key not in self._map:
            self._map[key] = f"UUID-{len(self._map)}"
        return self._map[key]

    def sub(self, text: str, strict: bool = False) -> str:
        """Replace every uuid substring in ``text`` with its ordinal."""

        def repl(m: re.Match) -> str:
            key = m.group(0).lower()
            if strict and key not in self._map and key not in self._derived:
                raise KeyError(
                    f"unseeded uuid {m.group(0)} appears in a filename; extend "
                    "harness.treepass.seed_mapper so name ordinals stay "
                    "capture-independent"
                )
            return self.map(m.group(0))

        return RE_UUID.sub(repl, text)

    def sub_any(self, value):
        """Recursively substitute uuids inside str/list/dict values."""
        if isinstance(value, str):
            return self.sub(value)
        if isinstance(value, list):
            return [self.sub_any(v) for v in value]
        if isinstance(value, dict):
            return {self.sub(str(k)): self.sub_any(v) for k, v in value.items()}
        return value
