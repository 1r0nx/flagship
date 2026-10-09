"""Load the configuration from a `config.sh`-style file.

Expected format (`KEY=value` lines; `export` and quotes tolerated):

    URL=https://ctf.example.com
    CTFD_TOKEN=ctfd_xxxxxxxx
    BASE_DIR=./MyCTF            # CTF root (challenges go in BASE_DIR/CHALLENGES/)
    CTF_NAME=MyCTF              # displayed name / default folder (optional)
    POLL_INTERVAL=60             # seconds between two auto syncs (0 = disabled)
    WRITE_FLAG_ON_SOLVE=true     # write flag.txt when a flag is accepted
    WATCH_CHANGES=true           # track desc/hint changes (desc2.txt…)
    AUTO_UNLOCK_FREE_HINTS=false # automatically unlock free hints
    DOWNLOAD_WORKERS=6           # parallel downloads for "Sync all"
    THEME=textual-dark           # start colour theme
    EDITOR=nano                  # command used to edit notes.md (e.g. vim, subl, code)

The token is never displayed nor executed (no shell `source`; plain KEY=value parsing).
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
    """Parse a basic config.sh file (KEY=value) without running a shell."""
    data: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")  # tolerate a leading UTF-8 BOM (e.g. saved from Windows)
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        key, val = m.group(1), _strip_quotes(m.group(2))
        # strip a possible unquoted end-of-line comment
        if val and val[0] not in "\"'" and "#" in val:
            val = val.split("#", 1)[0].strip()
        data[key] = val
    return data


def _as_bool(v: str, default: bool = True) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "oui")


def _as_int(v, default: int) -> int:
    """Parse an int setting, falling back to `default` on a missing or malformed value, so a typo
    in a non-critical setting (e.g. POLL_INTERVAL=60s) never blocks startup."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    url: str
    token: str
    base_dir: Path
    ctf_name: str
    poll_interval: int
    write_flag_on_solve: bool
    watch_changes: bool  # detect description/hint changes (fetch the detail on every sync)
    auto_unlock_free_hints: bool  # automatically unlock cost-0 hints
    download_workers: int  # parallel downloads for "Sync all"
    theme: str  # start colour theme (e.g. textual-dark, nord, gruvbox, dracula…)
    editor: str  # command used to edit notes.md (e.g. nano, vim, subl, code); empty = $EDITOR/$VISUAL then nano
    config_dir: Path  # folder holding config.sh (reference for displaying paths relatively)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"config not found: {path}")
        d = parse_sh(path)

        # URL: accepts URL / CTFD_URL
        url = d.get("URL") or d.get("CTFD_URL") or ""
        url = url.rstrip("/")

        # Token: accepts CTFD_TOKEN, TOKEN, or any *TOKEN* variable (e.g. PWNY_CTFD_TOKEN)
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
            raise ValueError("config.sh must define at least URL and a *TOKEN")

        ctf_name = d.get("CTF_NAME") or url.split("//")[-1].split("/")[0]
        base_dir = Path(d.get("BASE_DIR") or f"./{ctf_name}").expanduser()
        # a relative base_dir is resolved against the config.sh folder
        if not base_dir.is_absolute():
            base_dir = (path.parent / base_dir).resolve()

        return cls(
            url=url,
            token=token,
            base_dir=base_dir,
            ctf_name=ctf_name,
            poll_interval=_as_int(d.get("POLL_INTERVAL"), 60),
            write_flag_on_solve=_as_bool(d.get("WRITE_FLAG_ON_SOLVE"), True),
            watch_changes=_as_bool(d.get("WATCH_CHANGES"), True),
            auto_unlock_free_hints=_as_bool(d.get("AUTO_UNLOCK_FREE_HINTS"), False),
            download_workers=max(1, _as_int(d.get("DOWNLOAD_WORKERS"), 6)),
            theme=(d.get("THEME") or "textual-dark").strip(),
            editor=(d.get("EDITOR") or "").strip(),
            config_dir=path.parent,
        )
