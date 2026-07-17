"""Legacy-vs-candidate artifact parity harness for the HELAO hexagonal rewrite (P0).

See docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md
sections 5 (artifact inventory), 5.5 (volatile-field contract), and 6
(golden-master procedure). The harness is additive tooling: it never modifies
legacy source and never launches servers itself.
"""

HARNESS_VERSION = "0.1.0"
