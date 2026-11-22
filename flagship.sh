#!/usr/bin/env bash
# Flagship launcher: flagship.sh [--offline] [path/to/config.sh]
# (default: ./config.sh next to the flagship folder)
set -e
CFG="config.sh"
OPTS=()
for arg in "$@"; do
  case "$arg" in
    --*) OPTS+=("$arg") ;;   # options (e.g. --offline) are passed through to Python
    *)   CFG="$arg" ;;
  esac
done
# resolve the config path to an ABSOLUTE one before changing directory
CFG="$(cd "$(dirname "$CFG")" && pwd)/$(basename "$CFG")"
# move into the tool folder so that `python -m flagship` finds the package
cd "$(dirname "$0")"
exec python3 -m flagship "${OPTS[@]}" "$CFG"
