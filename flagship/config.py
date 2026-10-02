"""Chargement de la configuration depuis un fichier style `config.sh`.

Format attendu (lignes `CLE=valeur`, `export` et guillemets tolérés) :

    URL=https://ctf.example.com
    CTFD_TOKEN=ctfd_xxxxxxxx
    BASE_DIR=./MonCTF            # racine du CTF (les challenges vont dans BASE_DIR/CHALLENGES/)
    CTF_NAME=MonCTF              # nom affiché / dossier par défaut (optionnel)
    POLL_INTERVAL=60             # secondes entre deux synchros auto (0 = désactivé)
    WRITE_FLAG_ON_SOLVE=true     # écrire flag.txt quand un flag est validé
    WATCH_CHANGES=true           # suivre les changements desc/indices (desc2.txt…)
    AUTO_UNLOCK_FREE_HINTS=false # débloquer automatiquement les indices gratuits
    DOWNLOAD_WORKERS=6           # téléchargements parallèles pour « Tout synchroniser »
    THEME=textual-dark           # thème de couleurs de départ
    CTF_END=2026-10-05T18:00     # fin du CTF (compte à rebours) ; epoch ou ISO ; vide = auto via API

Le token n'est jamais affiché ni exécuté (pas de `source` shell ; simple parsing CLE=valeur).
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$""")


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_sh(path: Path) -> dict[str, str]:
    """Parse un fichier config.sh basique (CLE=valeur), sans exécuter de shell."""
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        key, val = m.group(1), _strip_quotes(m.group(2))
        # retirer un éventuel commentaire de fin de ligne non quoté
        if val and val[0] not in "\"'" and "#" in val:
            val = val.split("#", 1)[0].strip()
        data[key] = val
    return data


def _as_bool(v: str, default: bool = True) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "oui")


@dataclass
class Config:
    url: str
    token: str
    base_dir: Path
    ctf_name: str
    poll_interval: int
    write_flag_on_solve: bool
    watch_changes: bool  # détecter les changements de description/indices (fetch du détail à chaque sync)
    auto_unlock_free_hints: bool  # débloquer automatiquement les indices à coût 0
    download_workers: int  # téléchargements parallèles pour « Tout synchroniser »
    theme: str  # thème de couleurs de départ (ex. textual-dark, nord, gruvbox, dracula…)
    ctf_end: str  # fin du CTF pour le compte à rebours (epoch ou ISO ; vide = auto via API)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"config introuvable : {path}")
        d = parse_sh(path)

        # URL : accepte URL / CTFD_URL
        url = d.get("URL") or d.get("CTFD_URL") or ""
        url = url.rstrip("/")

        # Token : accepte CTFD_TOKEN, TOKEN, ou toute variable *TOKEN* (ex. PWNY_CTFD_TOKEN)
        token = ""
        for k in ("CTFD_TOKEN", "TOKEN"):
            if d.get(k):
                token = d[k]
                break
        if not token:
            for _k, v in d.items():
                if _k.upper().endswith("TOKEN") and v:
                    token = v
                    break

        if not url or not token:
            raise ValueError("config.sh doit définir au moins URL et un *TOKEN")

        ctf_name = d.get("CTF_NAME") or url.split("//")[-1].split("/")[0]
        base_dir = Path(d.get("BASE_DIR") or f"./{ctf_name}").expanduser()
        # base_dir relatif est résolu par rapport au dossier du config.sh
        if not base_dir.is_absolute():
            base_dir = (path.parent / base_dir).resolve()

        return cls(
            url=url,
            token=token,
            base_dir=base_dir,
            ctf_name=ctf_name,
            poll_interval=int(d.get("POLL_INTERVAL") or 60),
            write_flag_on_solve=_as_bool(d.get("WRITE_FLAG_ON_SOLVE"), True),
            watch_changes=_as_bool(d.get("WATCH_CHANGES"), True),
            auto_unlock_free_hints=_as_bool(d.get("AUTO_UNLOCK_FREE_HINTS"), False),
            download_workers=max(1, int(d.get("DOWNLOAD_WORKERS") or 6)),
            theme=(d.get("THEME") or "textual-dark").strip(),
            ctf_end=(d.get("CTF_END") or "").strip(),
        )
