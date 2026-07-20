"""Best-effort POST /shutdown to a local helao action server.

Triggers the server's FastAPI shutdown hook, which invokes the driver's
``shutdown()``. For the gamry driver that runs ``disconnect()`` (``pstat.Close()``
-> releases the exclusive GamryCOM device) and ``kill_gamrycom()`` (terminates
the out-of-process ``GamryCOM.exe``). A HARD kill of the python process skips
this and LEAKS the device lock -- the next launch then fails with
``CGamryPstat - In use by another script``. Station smoke scripts must call
this BEFORE force-killing stragglers.

The server dies mid-response, so a connection/timeout error here is EXPECTED and
ignored (exit 0 regardless -- this is a best-effort cleanup, not a gate).

Usage: python graceful_shutdown.py [port]   (default 8001)
"""

import sys
import urllib.request


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    url = f"http://127.0.0.1:{port}/shutdown"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=15)
        print(f"[graceful_shutdown] POST {url} accepted")
    except Exception as exc:  # noqa: BLE001 -- server exits mid-response; expected
        print(
            f"[graceful_shutdown] {url} returned/failed (expected as server exits): {exc}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
