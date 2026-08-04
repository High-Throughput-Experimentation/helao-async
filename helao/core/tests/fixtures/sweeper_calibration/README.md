# Frozen sweeper-calibration snapshots — do not refresh

These `*.py.txt` files are verbatim copies of five modules as they existed when
`helao/core/tests/test_palette.py` pinned its sweeper manifests. They are
intentionally frozen: refreshing them, or running `black`/`pyright` over this
directory, invalidates every pinned line number in `FIXTURE_MANIFESTS`.

The calibration runs against these snapshots rather than the live tree so that
it survives the later phases that edit those same five modules.
