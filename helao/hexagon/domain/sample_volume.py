"""Sample volume/dilution arithmetic.

Moved here from `helao.helpers.sample_api` (which keeps a thin delegating
wrapper for its legacy callers). The rule this satisfies:
`pal_reconciliation` needs this arithmetic, and `helao.helpers.sample_api` is
not on the domain allow-list -- it is a ~1300-line SQLite/aiofiles/pandas
module, so importing it to reach one pure function dragged the whole thing into
the domain layer and was rejected by
`tests/test_boundaries.py::test_domain_imports_only_allowlist`. The function
itself was always domain-shaped: it mutates a sample model in place and does no
I/O.

LOGGER note: domain modules log through stdlib `logging`, not
`helao.helpers.helao_logging` (outside the allow-list) -- the same tradeoff
`global_params.py` documents. That matters here, because `helao_logging`
attaches its handlers to a module-named logger and sets `propagate = False`,
so a stdlib logger in this module reaches ROOT, which has no HELAO handlers:
records would effectively disappear. Legacy callers must therefore keep their
own routing, so `update_vol` takes an optional `logger` and
`sample_api.update_vol` passes its `helao_logging` LOGGER in. That keeps every
existing call site's log output byte-identical instead of quietly dropping the
"volume <= 0 ... destroyed" error on a live station.
"""

import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)

__all__ = ["update_vol"]


def update_vol(
    BS,
    delta_vol_ml: float,
    dilute: bool,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Apply a volume delta to a sample, optionally rescaling its dilution factor.

    If the new total volume is non-positive, the sample is zeroed and marked
    destroyed. When ``dilute`` is set, the dilution factor is rescaled so the
    concentration before mixing is preserved (negative sentinel when the old
    volume was non-positive).

    Args:
        BS: Sample model with ``volume_ml`` (and optionally ``dilution_factor``).
        delta_vol_ml: Signed change in volume, in milliliters.
        dilute: When True, recompute ``dilution_factor`` from the new volume.
        logger: Where to send the volume/dilution messages. Defaults to this
            module's stdlib logger; callers that own a configured HELAO logger
            should pass it so their log routing is preserved.
    """
    log = logger if logger is not None else LOGGER
    if hasattr(BS, "volume_ml"):
        old_vol = BS.volume_ml
        tot_vol = old_vol + delta_vol_ml
        if tot_vol <= 0:
            log.error(
                "new volume is <= 0, setting it to zero and setting status to destroyed"
            )
            BS.zero_volume()
            tot_vol = 0
        BS.volume_ml = tot_vol
        if dilute:
            if hasattr(BS, "dilution_factor"):
                old_df = BS.dilution_factor
                if old_vol <= 0:
                    log.error("previous volume is <= 0, setting new df to 0.")
                    new_df = -1
                else:
                    new_df = tot_vol / (old_vol / old_df)
                BS.dilution_factor = new_df
                log.info(f"updated sample dilution-factor: {BS.dilution_factor}")
