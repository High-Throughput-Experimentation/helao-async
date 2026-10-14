"""Save the raw /openapi.json of every FastAPI server in a launch config.

Gate 8 of B7c: run it once against the running pre-B7c group (step 1) and once
against the bare-prefix group (step 6), then diff each pair with openapi_diff.py.
Hosts and ports come from the config, so a station that binds its hostname rather
than 127.0.0.1 is reached at the address it actually serves on.

Usage (from the repo root, helao env):
    python helao/hexagon/tests/smoke/openapi_snapshot.py <config.yml> <out_dir>

Writes <out_dir>/<KEY>_<port>.json per server and <out_dir>/manifest.json. Exits
non-zero if any server is unreachable or returns a spec with no paths, so an empty
capture cannot pass a later diff as "identical".

Standalone on purpose: it imports nothing from helao, so it can be copied onto a
station checkout that predates it.
"""

import json
import os
import sys
import urllib.request

import yaml


def fast_servers(config_path):
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key, server in cfg["servers"].items():
        if server.get("fast"):
            yield key, server["host"], int(server["port"])


def main(config_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    manifest, failed = {}, []
    for key, host, port in fast_servers(config_path):
        url = f"http://{host}:{port}/openapi.json"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                spec = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # report every server, then fail once at the end
            print(f"FAIL {key} {url}: {exc}")
            failed.append(key)
            continue
        n = len(spec.get("paths", {}))
        if n == 0:
            print(f"FAIL {key} {url}: spec has no paths")
            failed.append(key)
            continue
        name = f"{key}_{port}.json"
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=1, sort_keys=True)
        manifest[key] = {"url": url, "file": name, "paths": n}
        print(f"ok   {key} {url}: {n} paths -> {name}")
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print(f"{len(manifest)} saved, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
