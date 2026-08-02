"""The operator's saved-parameter store, shared by both UIs.

Both operators offer "load last parameters": the values last used for a
sequence or experiment, plus the label and campaign that went with them,
persisted under ``<root>/STATES/previous_params.json``. The file is a
cross-session, cross-UI artifact -- a station's operator may have saved it from
Bokeh and reloaded it from Reflex -- so one reader and one writer, here.

Every read is tolerant. The file lives on an instrument PC that can lose power
mid-write, and a half-written file must not take the button down with it.
"""

__all__ = [
    "params_path",
    "read_params",
    "read_last_meta",
    "write_params",
    "form_values",
    "PARAM_KINDS",
]

import json
import os

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The two kinds of saved parameters, matching the file's top-level keys.
PARAM_KINDS = ("seq", "exp")

#: Name of the store under the config root's STATES directory.
STORE_NAME = "previous_params.json"


def params_path(root: str) -> str:
    """Path of the store under ``root``."""
    return os.path.join(root, "STATES", STORE_NAME)


def _empty() -> dict:
    return {"seq": {}, "exp": {}, "last_meta": {}}


def _load(root: str) -> dict:
    """Read the store, or an empty one.

    Never raises and never creates the file: a *read* that writes would put a
    file into the instrument's data tree just for opening the operator.
    """
    if not root:
        return _empty()
    path = params_path(root)
    if not os.path.exists(path):
        return _empty()
    try:
        with open(path, "r", encoding="utf8") as handle:
            loaded = json.load(handle)
    except Exception as exc:
        # Half a JSON file is a real outcome of a station losing power
        # mid-write. The next write replaces it.
        LOGGER.warning(f"previous_params.json is unreadable ({exc}); ignoring it")
        return _empty()
    if not isinstance(loaded, dict):
        LOGGER.warning("previous_params.json does not hold an object; ignoring it")
        return _empty()
    store = _empty()
    for key in store:
        value = loaded.get(key)
        if isinstance(value, dict):
            store[key] = value
    return store


def read_params(root: str, kind: str, name: str) -> dict:
    """Parameters last saved for ``name``, or ``{}``.

    Args:
        root: The config root.
        kind: ``"seq"`` or ``"exp"``.
        name: Sequence or experiment name.
    """
    if kind not in PARAM_KINDS:
        return {}
    entry = _load(root).get(kind, {}).get(name)
    return entry if isinstance(entry, dict) else {}


def read_last_meta(root: str) -> dict:
    """The label/campaign block last saved, or ``{}``."""
    return _load(root).get("last_meta", {})


def write_params(root: str, kind: str, name: str, params: dict, meta=None) -> bool:
    """Save the parameters used for ``name``.

    Args:
        root: The config root. Empty for a UI-only server, where persisting is
            not possible.
        kind: ``"seq"`` or ``"exp"``.
        name: Sequence or experiment name.
        params: The parameters to remember.
        meta: Optional label/campaign block. Omitted leaves the previous one
            in place, so saving a sequence's parameters does not wipe the
            campaign the operator set earlier.

    Returns:
        bool: Whether anything was written. Never raises -- this runs as part
        of enqueueing, and a failure to remember must not fail the enqueue.
    """
    if kind not in PARAM_KINDS:
        LOGGER.warning(f"refusing to save parameters of unknown kind '{kind}'")
        return False
    if not root:
        return False
    store = _load(root)
    store[kind][name] = params
    if meta:
        store["last_meta"] = meta
    path = params_path(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf8") as handle:
            json.dump(store, handle)
    except Exception as exc:
        LOGGER.warning(f"could not save previous parameters: {exc}")
        return False
    return True


def form_values(params) -> dict:
    """Render saved parameters as the strings a form's inputs hold.

    The Reflex operator's fields are all strings and are parsed back on
    enqueue, so a saved int or list has to come back in a form an input can
    carry.
    """
    return {key: str(value) for key, value in (params or {}).items()}
