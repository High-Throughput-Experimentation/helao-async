"""The extracted-value matrix, and the legacy-vs-hexagon diff over it.

P7 moves the *hosting* of a UI, never the wire and never the render. The
proposition that follows is directly checkable: the same page served through
the legacy launcher path and through the P7e graft must produce the same
rendered values. This module is what makes "the same" a computation rather
than a judgement.

**Values, not screenshots.** Two runs of the same page differ by a pixel or two
of antialiasing, by font hinting, by whichever frame the compositor happened to
capture -- so an image diff reports a difference on every run and is
immediately ignored. A tint's measured sRGB triple, a contrast ratio to two
decimal places, an element count, and a live WebGL context count are all stable
across runs of the *same* build and all move when the hosting breaks.

**Volatile keys are declared, not discovered.** A run carries values that
legitimately differ between two launches of two configs -- a document title
naming the config, a queue length, a port. Those are recorded (they are useful
in a failure report) and excluded from the diff by name. Discovering
volatility instead -- "ignore anything that differed" -- would be a diff that
can never fail, which is the failure mode this file exists to avoid.
"""

__all__ = [
    "VOLATILE_KEYS",
    "diff_matrices",
    "format_diff",
    "load_matrix",
    "save_matrix",
]

import json
import os

#: Value-key *suffixes* excluded from the legacy-vs-hexagon diff, each with the
#: reason it cannot be compared. Matched against the end of the flattened key,
#: so ``operator.doc_title`` and ``live.doc_title`` are both covered by one
#: entry, as are ``live.canvas0_ink_distinct`` and ``live.canvas1_ink_distinct``.
#:
#: Kept deliberately short. Every entry is a hole in the gate, so a new one
#: needs a reason that is about the *value*, not about a diff that failed.
VOLATILE_KEYS = {
    # The two configs name their documents differently on purpose -- that is
    # how a launch log says which host is serving. Comparing them would report
    # the one difference the pair is designed to have.
    "doc_title": "the config names the host in the title, by design",
    # Simulators are free-running, so how much a chart has drawn at capture
    # time is a function of when the browser connected. The *bucket* this
    # classifies into (blank / axes-only / drawn) is compared instead, and that
    # is the property the diff is actually about.
    "ink_distinct": "raw pixel variety moves with the simulator's data",
    # Same reason, one level up: *how many* canvases have painted at capture
    # time depends on when the browser connected (measured: 5 on one run of a
    # document, 4 on the next). The boolean `canvas_any_painted` is compared
    # instead, and that is the property the check is actually about.
    "painted_count": "which canvases have painted yet depends on connect timing",
    "series_points": "sample count depends on connection timing",
    # A page's total text length shifts with a status line or a queue length.
    # The coarse band is compared instead.
    "body_text_length": "shifts with live status text",
    # A run's own identifiers.
    "run_id": "per-run identifier",
    "port": "the two variants may bind different ports",
}


def save_matrix(path: str, label: str, measurements: list) -> dict:
    """Serialize a run's measurements to JSON.

    Args:
        path: Destination file. Parent directories are created.
        label: Which lane this run is -- ``"legacy"`` or ``"hexagon"``.
        measurements: :class:`~probe.Measurement` objects.

    Returns:
        dict: The document written.
    """
    document = {
        "label": label,
        "routes": {m.name: m.values for m in measurements},
        "problems": [p for m in measurements for p in m.problems],
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=1, sort_keys=True)
    return document


def load_matrix(path: str) -> dict:
    """Read a matrix written by :func:`save_matrix`."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _flatten(routes: dict) -> dict:
    """Flatten ``{route: {key: value}}`` to ``{"route.key": value}``."""
    flat = {}
    for route, values in sorted(routes.items()):
        for key, value in sorted(values.items()):
            flat[f"{route}.{key}"] = value
    return flat


def _is_volatile(key: str) -> bool:
    """Whether a flattened key is excluded from the diff.

    Suffix matching, not equality: the keys that vary are named for what they
    are (``canvas0_ink_distinct``, ``canvas1_ink_distinct``) and enumerating
    every index would leave the next one silently compared.
    """
    leaf = key.rsplit(".", 1)[-1]
    return any(leaf == v or leaf.endswith(v) for v in VOLATILE_KEYS)


def diff_matrices(left: dict, right: dict) -> list:
    """Compare two matrices, ignoring the declared volatile keys.

    A route present in one run and absent in the other is a difference, and an
    important one: it is what a config pair drifting apart looks like. It is
    reported as a missing key rather than skipped.

    Returns:
        list: ``(key, left_value, right_value)`` triples, empty when the two
        runs agree. ``None`` marks a side that had no such key.
    """
    left_flat = _flatten(left.get("routes") or {})
    right_flat = _flatten(right.get("routes") or {})
    differences = []
    for key in sorted(set(left_flat) | set(right_flat)):
        if _is_volatile(key):
            continue
        a, b = left_flat.get(key), right_flat.get(key)
        if a != b:
            differences.append((key, a, b))
    return differences


def format_diff(left_label: str, right_label: str, differences: list) -> str:
    """Render a diff for a terminal."""
    if not differences:
        return f"matrix diff {left_label} vs {right_label}: empty (identical)"
    lines = [
        f"matrix diff {left_label} vs {right_label}: "
        f"{len(differences)} difference(s)"
    ]
    for key, a, b in differences:
        lines.append(f"  {key}: {left_label}={a!r} {right_label}={b!r}")
    return "\n".join(lines)


def perturb(document: dict, key: str, value) -> dict:
    """Return a copy of *document* with one flattened key changed.

    The mutation self-test uses this: a harness that reports "no differences"
    is worthless unless a known difference makes it speak. ``run_browser_parity
    --self-test`` perturbs a real captured matrix and requires the diff to
    report exactly that key.

    Args:
        document: A loaded matrix.
        key: ``"route.key"``.
        value: Replacement value.

    Raises:
        KeyError: If the key is not present -- perturbing a key that does not
            exist would prove nothing and pass.
    """
    route, _, leaf = key.rpartition(".")
    routes = {r: dict(v) for r, v in (document.get("routes") or {}).items()}
    if route not in routes or leaf not in routes[route]:
        raise KeyError(f"{key} is not in this matrix; cannot perturb it")
    routes[route][leaf] = value
    return {**document, "routes": routes}
