"""Standalone OCV test for the Gamry driver.

Connects to a Gamry potentiostat (device id supplied as a CLI argument),
runs a 30-second open-circuit voltage measurement at a 0.1 s acquisition
period using ``TECH_OCV``, prints incoming data to stdout, and disconnects.
"""

import sys
import time

from .....drivers.pstat.gamry.driver import GamryDriver
from .....drivers.pstat.gamry.technique import TECH_OCV

DURATION_SECONDS = 30.0
DATA_RATE = 0.1


def run_ocv(pstat):
    """Configure, start, and drain an OCV measurement on ``pstat``.

    Args:
        pstat: A connected ``GamryDriver`` instance.
    """
    resp = pstat.setup(
        technique=TECH_OCV,
        signal_params={"Tval__s": DURATION_SECONDS, "AcqInterval__s": DATA_RATE},
    )
    print(f"setup response: {resp.message}")
    resp = pstat.measure()
    print(f"start response: {resp.message}")
    state = "busy"
    time.sleep(DATA_RATE)
    while state == "busy":
        resp = pstat.get_data(DATA_RATE)
        print(f"got data: {resp.data}")
        state = resp.status
        time.sleep(DATA_RATE)
    print("OCV measurement complete.")


def main() -> bool:
    """Entry point: parse the device id from argv, run OCV, and disconnect.

    Returns:
        True on a successful run, False if the device id argument is missing
        or cannot be parsed as an integer.
    """
    if len(sys.argv) < 2:
        print(
            "Device ID was not specified. Provide device ID number as a launch argument."
        )
        return False

    device_id_arg = sys.argv[1]
    try:
        device_id = int(device_id_arg)
    except Exception:
        print(f"Could not cast device ID argument {device_id_arg} to integer.")
        return False

    pstat = GamryDriver({"dev_id": device_id})
    pstat.connect()

    print(f"connected to: {pstat.device_name}")
    print(f"model: {pstat.model}")
    print(f"device id: {device_id}")

    print(
        f"Running OCV for {DURATION_SECONDS} seconds, recording every {DATA_RATE} seconds."
    )
    run_ocv(pstat)

    print(f"Closing connection.")
    pstat.disconnect()

    return True


if __name__ == "__main__":
    main()
