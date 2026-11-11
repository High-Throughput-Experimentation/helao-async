# Activate the helao environment in the calling shell. Source it:
#     source "$HA_DIR/activate_helao.sh"
# Returns 0 when activated, 1 otherwise. Prefers the pixi workspace
# <repo>/.helao-env; falls back to a conda env named helao while hosts move
# over (spec 2026-11-11-pixi-env-design.md, "Transition fallback").
_helao_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
_helao_ws="$_helao_dir/.helao-env/pixi.toml"
_helao_pixi=$(command -v pixi || true)
[ -z "$_helao_pixi" ] && [ -x "$HOME/.pixi/bin/pixi" ] && _helao_pixi="$HOME/.pixi/bin/pixi"
if [ -f "$_helao_ws" ]; then
    if [ -z "$_helao_pixi" ]; then
        echo "ERROR: $_helao_ws exists but pixi is not on PATH or in ~/.pixi/bin; run setup_env.sh to install it" >&2
        return 1
    fi
    _helao_hook=$("$_helao_pixi" shell-hook --frozen --manifest-path "$_helao_ws" --shell bash) || return 1
    eval "$_helao_hook"
    return 0
fi
if command -v conda >/dev/null 2>&1 && conda env list 2>/dev/null | grep -qE '[/\\]envs[/\\]helao$'; then
    echo "WARNING: helao is still on conda; run setup_env.sh to move to pixi" >&2
    eval "$(conda shell.bash hook)"
    conda activate helao
    return 0
fi
echo "ERROR: no helao environment; run setup_env.sh <config prefix> ..." >&2
return 1
