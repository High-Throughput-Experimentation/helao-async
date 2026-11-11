#!/usr/bin/env bash
HELAO_ENV_MODE=update exec bash "$(dirname "$(readlink -f "$0")")/setup_env.sh" "$@"
