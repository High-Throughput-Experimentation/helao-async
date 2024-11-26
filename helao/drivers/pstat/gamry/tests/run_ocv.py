import sys
import time
from helao.drivers.pstat.gamry.driver import GamryDriver
from helao.drivers.pstat.gamry.technique import TECH_OCV

DURATION_SECONDS = 10.0
DATA_RATE = 0.1


def run_ocv(pstat):
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
        
    
def main():
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

    print(f"Running OCV for {DURATION_SECONDS} seconds, recording every {DATA_RATE} seconds.")
    run_ocv(pstat)

    return True


if __name__ == "__main__":
    main()
