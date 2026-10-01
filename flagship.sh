#!/usr/bin/env bash
# Lanceur Flagship : flagship.sh [chemin/vers/config.sh]
# (défaut : ./config.sh à côté du dossier flagship)
set -e
CFG="${1:-config.sh}"
# résout le chemin du config en ABSOLU avant de changer de dossier
CFG="$(cd "$(dirname "$CFG")" && pwd)/$(basename "$CFG")"
# se place dans le dossier de l'outil pour que `python -m flagship` trouve le package
cd "$(dirname "$0")"
exec python3 -m flagship "$CFG"
