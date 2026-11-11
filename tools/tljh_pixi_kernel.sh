#!/usr/bin/env bash
# Register a pixi environment as a JupyterLab kernel for every TLJH user.
#
# Run with sudo, after the pixi workspace is installed as a normal user:
#   sudo bash tools/tljh_pixi_kernel.sh [WORKSPACE] [ENV] [KERNEL_NAME] [DISPLAY_NAME]
# Defaults: <repo>/.helao-env  default  helao-pixi  "Python (helao pixi)"
#
# What it does:
#   1. As $SUDO_USER (not root): freezes `pixi shell-hook` into
#      WORKSPACE/activate-ENV.sh, so kernels get pixi's full activation
#      (activation.env such as PYTHONPATH, plus package activation scripts)
#      without running pixi on every kernel start.
#   2. As root: writes TLJH_PREFIX/share/jupyter/kernels/KERNEL_NAME/ via
#      `ipykernel install` (logos, metadata), then replaces argv so the kernel
#      sources the activation script before starting ipykernel.
# Re-run it after any change to [activation] or to packages that ship
# activation scripts. Remove the kernel with:
#   sudo rm -r /opt/tljh/user/share/jupyter/kernels/KERNEL_NAME
set -euo pipefail

WORKSPACE=${1:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)/.helao-env}
ENV_NAME=${2:-default}
KERNEL_NAME=${3:-helao-pixi}
DISPLAY_NAME=${4:-"Python (helao pixi)"}
TLJH_PREFIX=${TLJH_PREFIX:-/opt/tljh/user}

die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
[ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ] || die "run via sudo from your own account (SUDO_USER is unset or root)"
USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
# pixi: $PIXI, else whatever $SUDO_USER's login shell finds, else the installer's default
if [ -z "${PIXI:-}" ]; then
    PIXI=$(sudo -u "$SUDO_USER" -H bash -lc 'command -v pixi' 2>/dev/null | tail -n1 || true)
    [ -n "$PIXI" ] && [ -x "$PIXI" ] || PIXI=$USER_HOME/.pixi/bin/pixi
fi
[ -x "$PIXI" ] || die "pixi not found at $PIXI (run: sudo PIXI=/path/to/pixi bash tools/tljh_pixi_kernel.sh)"
[ -f "$WORKSPACE/pixi.toml" ] || die "no pixi.toml in $WORKSPACE"
[ -d "$TLJH_PREFIX/share/jupyter/kernels" ] || die "TLJH kernels dir missing: $TLJH_PREFIX/share/jupyter/kernels"

# 1. activation script, generated as the workspace owner so pixi never writes root-owned files
ACTIVATE="$WORKSPACE/activate-$ENV_NAME.sh"
trap 'rm -f "$ACTIVATE.tmp"' EXIT
sudo -u "$SUDO_USER" -H "$PIXI" shell-hook --frozen --shell bash \
    -e "$ENV_NAME" --manifest-path "$WORKSPACE/pixi.toml" > "$ACTIVATE.tmp"
# shell-hook froze the caller's PATH (sudo's secure_path); keep only the env's dirs
# and append the PATH of whoever sources the script
python3 -P - "$ACTIVATE.tmp" "$PATH" <<'PYEOF'
import sys
path_file, caller = sys.argv[1], sys.argv[2]
with open(path_file, encoding="utf-8") as f:
    lines = f.read().split("\n")
hit = False
for i, line in enumerate(lines):
    if line.startswith("export PATH="):
        val = line[len("export PATH="):].strip().strip("\"'")
        if not val.endswith(":" + caller):
            sys.exit(f"ERROR: PATH line in {path_file} does not end with the caller PATH: {line}")
        lines[i] = f'export PATH="{val[: -len(caller) - 1]}:$PATH"'
        hit = True
if not hit:
    sys.exit(f"ERROR: no 'export PATH=' line in {path_file}")
with open(path_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
PYEOF
mv "$ACTIVATE.tmp" "$ACTIVATE"
chown "$SUDO_USER":"$(stat -c %G "$WORKSPACE")" "$ACTIVATE"
chmod 0644 "$ACTIVATE"

# the kernel must start for a hub user, not just for you
QACT=$(printf %q "$ACTIVATE")
bash -c "source $QACT && python -c 'import ipykernel, sys; print(\"activation ok:\", sys.executable)'" \
    || die "sourcing $ACTIVATE did not give a working python"
ENV_PY=$(bash -c "source $QACT && command -v python" | tail -n1) || die "no python after sourcing $ACTIVATE"

# 2. kernelspec (root-owned, world-readable)
"$ENV_PY" -P -m ipykernel install --prefix "$TLJH_PREFIX" \
    --name "$KERNEL_NAME" --display-name "$DISPLAY_NAME" >/dev/null
SPEC="$TLJH_PREFIX/share/jupyter/kernels/$KERNEL_NAME/kernel.json"
"$ENV_PY" -P - "$SPEC" "$ACTIVATE" <<'EOF'
import json, shlex, sys
spec_path, activate = sys.argv[1], sys.argv[2]
with open(spec_path, encoding="utf-8") as f:
    spec = json.load(f)
# bash gets {connection_file} as $0; exec keeps signals (interrupt/restart) on the kernel
spec["argv"] = [
    "/bin/bash", "-c",
    f"source {shlex.quote(activate)} && exec python -m ipykernel_launcher -f \"$0\"",
    "{connection_file}",
]
with open(spec_path, "w", encoding="utf-8") as f:
    json.dump(spec, f, indent=1)
EOF
chmod 0755 "$(dirname "$SPEC")"
chmod 0644 "$(dirname "$SPEC")"/*

echo "kernel '$KERNEL_NAME' installed: $SPEC"
"$TLJH_PREFIX/bin/jupyter" kernelspec list 2>/dev/null | grep -E "^\s+$KERNEL_NAME\s" \
    || echo "WARNING: jupyter kernelspec list does not show $KERNEL_NAME"
echo "users: reload JupyterLab and pick '$DISPLAY_NAME'"
