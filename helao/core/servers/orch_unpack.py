"""Re-export of :mod:`helao.hexagon.app.orch_unpack` (B7a); B7b deletes it.

The definitions moved to ``helao/hexagon/app/orch_unpack.py``. Patching
``PLATE_API`` here reaches nothing: the functions read it from the module that
defines them, so its one patch point is
``helao.hexagon.app.orch_unpack.PLATE_API``. The four functions are the same
objects as in the new module; legacy ``Orch`` still calls them through this one.
"""

from helao.hexagon.app.orch_unpack import (  # noqa: F401
    PLATE_API,
    get_sequence_codehash,
    seq_unpacker,
    unpack_sequence,
    verify_plate_in_params,
)
