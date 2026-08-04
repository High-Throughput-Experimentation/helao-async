"""Freeze hte legacy endpoint checklists (spec §8.3, P3-pre).

Runs the P0 AST extractor over each hte action-server module and writes the
frozen route set as the endpoint-parity baseline for the P3 wave.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.endpoints import extract_routes

HTE_ACTION = Path("helao/deploy/hte/servers/action")
OUT = Path("helao/hexagon/tests/checklists/hte")

# (module filename, representative server_key for {server_key} substitution)
SERVERS: list[tuple[str, str | None]] = [
    ("HTEdata_server.py", None),
    ("analysis_server.py", "ANA"),
    ("andor_server.py", "ANDOR"),
    ("biologic_server.py", "BIOLOGIC"),
    ("calc_server.py", "CALC"),
    ("cam_server.py", "CAM"),
    ("co2sensor_server.py", "CO2SENSOR"),
    ("sync_server.py", "DB"),
    ("diapump_server.py", "DOSEPUMP"),
    ("galil_io.py", "IO"),
    ("galil_motion.py", "MOTOR"),
    ("gamry_server2.py", "PSTAT"),
    ("kinesis_server.py", "KMOTOR"),
    ("mfc_server.py", "MFC"),
    ("nidaqmx_server.py", "NI"),
    ("o2sensor_server.py", None),
    ("pal_server.py", "PAL"),
    ("pdu_server.py", None),
    ("power_supply_server.py", "POWER_SUPPLY"),
    ("sample_server.py", "SAMPLE"),
    ("spec_server.py", "SPEC_T"),
    ("syringe_server.py", "WORKSYRINGE"),
    ("tec_server.py", None),
]


def freeze_all(out_dir: Path = OUT) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for module, key in SERVERS:
        routes = extract_routes(HTE_ACTION / module, server_key=key)
        dst = out_dir / (Path(module).stem + ".json")
        dst.write_text(json.dumps(routes, indent=2) + "\n")
        written.append(dst)
    return written


if __name__ == "__main__":
    for p in freeze_all():
        print(p)
