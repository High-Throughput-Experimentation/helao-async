"""Tiny stand-in sidecar for spawn tests: serves /health after ~1 s, /shutdown exits."""
import argparse
import http.server
import json
import threading
import time

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, required=True)
p.add_argument("--simulate", action="store_true")
args = p.parse_args()
port = args.port
time.sleep(1.0)


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body=b"{}"):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(
            json.dumps(
                {"pid": 1, "hw_initialized": False, "simulate": args.simulate}
            ).encode()
        )

    def do_POST(self):
        self._send()
        if self.path == "/shutdown":
            threading.Thread(target=srv.shutdown, daemon=True).start()

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
srv.serve_forever()
