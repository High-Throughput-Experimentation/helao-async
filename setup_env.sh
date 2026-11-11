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
fi
WS="$HA_DIR/.helao-env"
if [ ! -f "$WS/pixi.toml" ]; then
    mkdir -p "$WS" || exit 1
    cp "$HA_DIR/pixi.toml" "$HA_DIR/pixi.lock" "$WS/" || exit 1
fi
# Run helao_env.py in the env. pixi installs it from the lock on first use, and
# the env's location is pixi's business (detached-environments may move it).
PIXI="$PIXI" "$PIXI" run --frozen --manifest-path "$WS/pixi.toml" \
    python "$HA_DIR/helao_env.py" "$MODE" "$@" || exit 1
chmod +x "$HA_DIR/helao.sh"
echo ""
echo "'helao' environment $MODE is complete"
