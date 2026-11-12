#!/usr/bin/env bash
# Create or update the helao pixi environment, then install the packages of
# the given station config prefixes. update_env.sh runs this with mode update.
HA_DIR=$(dirname "$(readlink -f "$0")")
MODE=${HELAO_ENV_MODE:-setup}
PIXI=$(command -v pixi || true)
[ -z "$PIXI" ] && [ -x "$HOME/.pixi/bin/pixi" ] && PIXI="$HOME/.pixi/bin/pixi"
if [ -z "$PIXI" ]; then
    echo "pixi not found; installing it to ~/.pixi ..."
    curl -fsSL https://pixi.sh/install.sh | bash || exit 1
    PIXI="$HOME/.pixi/bin/pixi"
    [ -x "$PIXI" ] || { echo "ERROR: pixi install failed; install pixi from https://pixi.sh and rerun setup_env.sh" >&2; exit 1; }
fi
WS="$HA_DIR/.helao-env"
CREATED=0
if [ "$MODE" = update ] && { [ ! -f "$WS/pixi.toml" ] || [ ! -f "$WS/pixi.lock" ]; }; then
    echo "no pixi env yet on this host; run setup_env <config prefix> ... first (a host moving from conda must name its prefixes once)" >&2
    exit 1
fi
if [ ! -f "$WS/pixi.toml" ] || [ ! -f "$WS/pixi.lock" ]; then
    mkdir -p "$WS" || exit 1
    CREATED=1
    cp "$HA_DIR/pixi.lock" "$WS/" || exit 1
    cp "$HA_DIR/pixi.toml" "$WS/" || exit 1
fi
# Run helao_env.py in the env. pixi installs it from the lock on first use, and
# the env's location is pixi's business (detached-environments may move it).
PIXI="$PIXI" "$PIXI" run --frozen --manifest-path "$WS/pixi.toml" \
    python "$HA_DIR/helao_env.py" "$MODE" "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
    if [ "$CREATED" = 1 ]; then
        rm -f "$WS/pixi.toml" "$WS/pixi.lock" "$WS/.seed"
        echo "setup failed; removed the new .helao-env manifest so helao.sh keeps using the previous environment"
    fi
    exit $rc
fi
chmod +x "$HA_DIR/helao.sh"
echo ""
echo "'helao' environment $MODE is complete"
