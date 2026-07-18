"""Hexagon-native adapters (P2b-1): the first non-legacy, non-fake adapter
family. Bodies are verbatim copies of the CARDS-P6 write collaborators
(source-parity-pinned); they read all per-action state off the legacy
``Active``/``Base`` back-reference at call time (cache-nothing rule) and
never import ``helao.core.servers.*`` (boundary-enforced)."""
