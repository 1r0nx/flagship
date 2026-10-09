#!/usr/bin/env bash
# Flagship launcher: flagship.sh [path/to/config.sh]
# (default: ./config.sh next to the flagship folder)
set -e
CFG="${1:-config.sh}"
# resolve the config path to an ABSOLUTE one before changing directory
CFG="$(cd "$(dirname "$CFG")" && pwd)/$(basename "$CFG")"
# move into the tool folder so that `python -m flagship` finds the package
cd "$(dirname "$0")"
exec python3 -m flagship "$CFG"
