"""``adss3.yml`` composed entirely of hexagon-hosted servers.

Not a copy of ``adss3.yml`` -- it IS ``adss3.yml``, loaded at launch and
re-composed onto the hexagon app layer by
:func:`helao.hexagon.hexconfig.hexagon_variant`. Ports, addresses, channel
maps, credentials and every other value live in the base config and ONLY
there, so the two cannot drift; edit the base and this variant follows.

That is the point of deriving rather than duplicating. Parallel hexagon
configs were rejected twice before (P4f, P5g) for exactly one reason -- two
copies of a station's real hardware params drift, and the copy is the one
nobody notices is stale. A derived variant has no second copy to go stale.

The composition is the only difference. Every server gains
``deployment: hexagon``; those without a same-named hexagon shim additionally
route through the generic graft (``<code key>: graft`` plus a
``legacy_module:`` naming the real target). ``root:`` is unchanged, so this
writes to the same run tree the station always used.

Rollback is to launch ``adss3`` instead of ``adss3_hex``. Nothing is
migrated, nothing is deleted, and the legacy composition stays exactly as it
was.

To see what this resolves to without launching::

    python -m helao.hexagon.preflight helao/deploy/hte/configs/adss3_hex.py
"""

import os

from helao.hexagon.hexconfig import hexagon_variant

config = hexagon_variant(os.path.join(os.path.dirname(__file__), "adss3.yml"))
