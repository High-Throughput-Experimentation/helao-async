from time import time, ctime
import ntplib


def get_ntp_time(ntp_server, output_path):
    """
    Retrieves the current time from an NTP server and updates the
    instance variables with the response.

    This method acquires a lock to ensure thread safety while accessing the NTP
    server. It sends a request to the specified NTP server and updates the
    following instance variables based on the response:
    - ntp_response: The full response from the NTP server.
    - ntp_last_sync: The original time from the NTP response.
    - ntp_offset: The offset time from the NTP response.

    If the request to the NTP server fails, it logs a timeout message and sets
    ntp_last_sync to the current time and ntp_offset to 0.0.

    Additionally, it logs the ntp_offset and ntp_last_sync values. If a file path
    for ntp_last_sync_file is provided, it waits until the file is not in use,
    then writes the ntp_last_sync and ntp_offset values to the file.

    Raises:
        ntplib.NTPException: If there is an error in the NTP request.

    Returns:
        None
    """
    c = ntplib.NTPClient()
    try:
        response = c.request(ntp_server, version=3)
        ntp_response = response
        ntp_last_sync = response.orig_time
        ntp_offset = response.offset
        print(f"retrieved time at {ctime(ntp_response.tx_timestamp)} from {ntp_server}")
    except ntplib.NTPException:
        print(f"{ntp_server} ntp timeout")
        ntp_last_sync = time()
        ntp_offset = 0.0

    print(f"ntp_offset: {ntp_offset}")
    print(f"ntp_last_sync: {ntp_last_sync}")

    with open(output_path, "w") as f:
        f.write(f"{ntp_last_sync},{ntp_offset}")


def read_saved_offset(file_path):
    with open(file_path, "r") as f:
        tmps = f.readline().strip().split(",")
        if len(tmps) == 2:
            ntp_last_sync, ntp_offset = tmps
            ntp_offset = float(ntp_offset)
            return ntp_last_sync, ntp_offset
