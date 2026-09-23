# helao/ui/shared/platemap.py
"""Plate-map helpers shared by the Reflex operator and the composition page.

Hoisted out of `helao/ui/reflex/operator.py`, where they were written for the
operator's plate tab. Nothing about them is operator-specific: they turn an
`HTEPlateAPI` platemap into plottable points, and resolve a click back to a
sample. `operator.py` imports them back under their existing names, so its call
sites and the tests that reach them through it are unchanged.

This module imports no `reflex`, which is what makes it testable without an app.

Two properties are load-bearing and easy to break:

* `platemap_points` numbers samples **positionally** (`index + 1`), not from the
  platemap's own `sample_no` column. That is the operator's existing behaviour
  and is left alone. Anything joining against records that carry a real sample
  number must use `platemap_rows` instead.
* `plate_api_for` is **opt-in**: no `params.plate_api` means no plate API, and
  an unrecognised value is ignored rather than imported, so a typo cannot pull
  in something arbitrary.
"""

from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


# -- plate map ---------------------------------------------------------------

#: Composition fraction keys on a platemap entry, in display order.
FRACTION_KEYS = ("A", "B", "C", "D", "E", "F", "G", "H")

#: Plate APIs the operator knows how to build, by config value.
PLATE_APIS = ("HTEPlateAPI",)

_PLATE_API_CACHE: dict = {}


def plate_api_for(server_cfg: dict):
    """Build the configured plate API, or ``None`` when there is none.

    Opt-in, as in the Bokeh operator: most stations have no plate API, and an
    unknown name is ignored rather than imported, so a typo cannot pull in
    something arbitrary.
    """
    params = (server_cfg or {}).get("params")
    name = params.get("plate_api") if isinstance(params, dict) else None
    if name not in PLATE_APIS:
        if name:
            LOGGER.warning(f"operator ignoring unknown plate_api '{name}'")
        return None
    cached = _PLATE_API_CACHE.get(name)
    if cached is not None:
        return cached
    try:
        from helao.helpers.plate_api import HTEPlateAPI

        cached = HTEPlateAPI()
    except Exception as exc:
        LOGGER.warning(f"operator could not build plate API '{name}': {exc}")
        return None
    _PLATE_API_CACHE[name] = cached
    return cached


def plate_api_for_config(world_cfg: Optional[dict]):
    """The first plate API any server in *world_cfg* declares, or ``None``.

    `/composition` binds to no server, so there is no single ``server_cfg`` to
    read ``params.plate_api`` from. Scanning preserves the opt-in property: a
    config where nothing declares one still yields ``None``.
    """
    servers = ((world_cfg or {}).get("servers")) or {}
    for server_cfg in servers.values():
        api = plate_api_for(server_cfg)
        if api is not None:
            return api
    return None


def _as_number(value):
    """Read one coordinate, or ``None`` when it is not a number."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def platemap_points(pmdata: Optional[list]) -> tuple:
    """Split a platemap into plottable coordinates and sample numbers.

    A row whose coordinates will not convert is dropped whole. Handing a
    non-numeric value to ``plots`` raises from inside the render and takes the
    entire chart down, and dropping only one of the pair would leave x and y
    at different lengths, which ``scatter_map`` rejects.

    Returns:
        tuple: ``(xs, ys, sample_nos)``, all the same length. Sample numbers
        are 1-based, matching the plate's own numbering.
    """
    xs, ys, samples = [], [], []
    for index, entry in enumerate(pmdata or []):
        x = _as_number((entry or {}).get("x"))
        y = _as_number((entry or {}).get("y"))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
        samples.append(index + 1)
    return xs, ys, samples


def platemap_rows(pmdata: Optional[list]) -> list:
    """Plottable platemap rows, each keyed by the map's own ``sample_no``.

    The same rows :func:`platemap_points` keeps -- coordinates coerced,
    unconvertible rows dropped whole -- but carrying the sample number the
    platemap itself records rather than the row's position. A caller joining
    against records whose sample number came from somewhere else (an API label,
    a filename) must use this; `platemap_points`' positional numbering would
    silently pair the right value with the wrong position.

    Args:
        pmdata: The platemap, as `HTEPlateAPI.get_platemap_plateid` returns it.

    Returns:
        list: ``{"sample_no": int, "x": float, "y": float, "entry": dict}``.
    """
    rows = []
    for entry in pmdata or []:
        item = entry or {}
        x = _as_number(item.get("x"))
        y = _as_number(item.get("y"))
        if x is None or y is None:
            continue
        raw = item.get("sample_no")
        if raw is None:
            raw = item.get("Sample")
        try:
            sample_no = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        rows.append({"sample_no": sample_no, "x": x, "y": y, "entry": item})
    return rows


def nearest_sample(pmdata: Optional[list], x: float, y: float):
    """Sample number nearest a clicked point, or ``None`` on an empty map.

    Matched against the plottable rows only: a click lands on the rendered
    map, which does not contain the rows that were dropped, so matching
    against them could return a sample the operator cannot see.
    """
    xs, ys, samples = platemap_points(pmdata)
    if not xs:
        return None
    best = min(range(len(xs)), key=lambda i: (xs[i] - x) ** 2 + (ys[i] - y) ** 2)
    return samples[best]


def composition_text(entry: Optional[dict]) -> str:
    """Composition fractions of one platemap entry, as one line.

    A dash when there are none: an empty readout reads as a failure to load
    rather than a plate with no composition.
    """
    entry = entry or {}
    parts = [
        f"{key}_{entry[key]}" for key in FRACTION_KEYS if entry.get(key) is not None
    ]
    return " ".join(parts) if parts else "-"


def sample_summary(pmdata: Optional[list], sample_no: int) -> dict:
    """Code and composition for one sample number.

    Args:
        pmdata: The platemap.
        sample_no: 1-based sample number. ``0`` is rejected rather than
            treated as an index, which would silently return the last sample
            on the plate.

    Returns:
        dict: ``sample_no``, ``code``, ``composition``, and ``error``.
    """
    blank = {"sample_no": str(sample_no), "code": "", "composition": ""}
    entries = pmdata or []
    if sample_no < 1 or sample_no > len(entries):
        return {**blank, "error": f"sample {sample_no} is not on this plate"}
    entry = entries[sample_no - 1] or {}
    return {
        "sample_no": str(sample_no),
        "code": "" if entry.get("code") is None else str(entry["code"]),
        "composition": composition_text(entry),
        "error": "",
    }
