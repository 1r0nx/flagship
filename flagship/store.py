"""Synchronisation API -> système de fichiers.

Conventions :
- arborescence : <base_dir>/CHALLENGES/<Catégorie>/<Nom-du-challenge>/
  (la racine <base_dir> reste réservée à config.sh, PROGRESS.md, .flagship/…)
- nommage : espaces -> '-', jamais de tirets consécutifs ; en cas de collision de noms dans
  une même catégorie, on suffixe par l'id du challenge.
- fichiers téléchargés rangés dans <challenge>/work/ ; desc.txt/downloads.txt à la racine.
- idempotent : ne supprime/écrase jamais un desc.txt existant ; changements desc/indices -> descN.txt.
"""

from __future__ import annotations
import html
import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

from .ctfd import CTFd, CTFdError, _stream_to

MAX_BYTES = 2 * 1024**3  # 2 Go : au-delà -> manuel
CHALLENGES = "CHALLENGES"  # sous-dossier qui contient les catégories (racine réservée à config.sh, etc.)

_FORBIDDEN = re.compile(r'[/\\\x00]')
_SPACES = re.compile(r"\s+")
_DASHES = re.compile(r"-{2,}")
_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')


# ------------------------------------------------------------------ nommage
def slugify(name: str) -> str:
    s = _FORBIDDEN.sub("-", name.strip())
    s = _SPACES.sub("-", s)
    s = _DASHES.sub("-", s)
    return s.strip("-") or "challenge"


def slugify_filename(name: str) -> str:
    return _FORBIDDEN.sub("_", name).strip() or "download.bin"


def challenge_dir(base_dir: Path, category: str, name: str) -> Path:
    return base_dir / CHALLENGES / slugify(category or "Uncategorized") / slugify(name)


def assign_paths(challenges: list[dict], base_dir: Path) -> None:
    """Fixe `ch['path']` pour chaque challenge, avec anti-collision (suffixe -id)."""
    root = base_dir / CHALLENGES
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ch in challenges:
        key = (slugify(ch.get("category", "Uncategorized")), slugify(ch.get("name", "challenge")))
        buckets[key].append(ch)
    for (cat, name), group in buckets.items():
        if len(group) == 1:
            group[0]["path"] = str(root / cat / name)
        else:  # collision -> suffixe id
            for ch in group:
                ch["path"] = str(root / cat / f"{name}-{ch.get('id')}")


# ------------------------------------------------------------------ desc.txt
def clean_desc(desc: str | None) -> str:
    if not desc:
        return ""
    s = html.unescape(desc)
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


def classify_link(url: str) -> str:
    u = url.lower()
    if "drive.google" in u or "docs.google" in u:
        return "gdrive"
    if "mega.nz" in u or "mega.co.nz" in u:
        return "mega"
    if "dropbox.com" in u:
        return "dropbox"
    return "http"


def extract_links(text: str | None) -> list[str]:
    if not text:
        return []
    seen, out = set(), []
    for m in _URL_RE.findall(text):
        u = m.rstrip(".,);]")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _sig(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _hints_state(detail: dict) -> list[dict]:
    out = [{"id": h.get("id"), "cost": h.get("cost", 0), "unlocked": bool(h.get("content"))}
           for h in detail.get("hints") or []]
    return sorted(out, key=lambda x: (x["id"] is None, x["id"]))


def _hints_lines(detail: dict) -> str:
    hints = detail.get("hints") or []
    if not hints:
        return "aucun"
    parts = []
    for h in hints:
        cost = h.get("cost", 0)
        tag = "gratuit" if cost == 0 else f"{cost} pts"
        if h.get("content"):
            parts.append(f'[{h.get("id")}] (débloqué, {tag}) "{h["content"]}"')
        else:
            parts.append(f'[{h.get("id")}] (verrouillé, {tag})')
    return "\n            ".join(parts)


def _files_block(file_urls: list[tuple[str, str]]) -> str:
    if not file_urls:
        return "aucun"
    return "\n" + "\n".join(f"            - work/{n} : {u}" for n, u in file_urls)


def _ext_block(ext_links: list[str]) -> str:
    if not ext_links:
        return "aucun"
    return "\n" + "\n".join(f"            - [{classify_link(u)}] {u}" for u in ext_links)


def _desc_text(detail: dict, file_urls, ext_links, header: str = "") -> str:
    body = (
        f"Nom        : {detail.get('name','?')}\n"
        f"Catégorie  : {detail.get('category','?')}\n"
        f"Points     : {detail.get('value','?')}\n"
        f"Solves     : {detail.get('solves','?')}\n"
        f"ID         : {detail.get('id','?')}\n\n"
        f"Description :\n{clean_desc(detail.get('description'))}\n\n"
        f"Connexion : {detail.get('connection_info') or 'aucune'}\n"
        f"Fichiers (plateforme, -> work/) : {_files_block(file_urls)}\n"
        f"Liens externes : {_ext_block(ext_links)}\n"
        f"Indices   : {_hints_lines(detail)}\n"
    )
    return (header + body) if header else body


# ------------------------------------------------------------------ état
def _state_path(d: Path) -> Path:
    return d / ".flagship.json"


def _load_state(d: Path) -> dict:
    p = _state_path(d)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_state(d: Path, state: dict) -> None:
    _state_path(d).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _hint_events(old, new, name):
    ev = []
    old_by = {h["id"]: h for h in old}
    for nh in new:
        oid = nh["id"]
        tag = "gratuit" if nh["cost"] == 0 else f"{nh['cost']} pts"
        if oid not in old_by:
            ev.append({"kind": "hint", "name": name, "msg": f"nouvel indice #{oid} ({tag})"})
        else:
            o = old_by[oid]
            if not o["unlocked"] and nh["unlocked"]:
                ev.append({"kind": "hint", "name": name, "msg": f"indice #{oid} débloqué"})
            elif o["cost"] != nh["cost"]:
                ev.append({"kind": "hint", "name": name, "msg": f"indice #{oid} : coût {o['cost']}→{nh['cost']}"})
    return ev


# ------------------------------------------------------------------ downloads
def _filename_from(r: requests.Response, url: str) -> str:
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
    if m:
        return slugify_filename(m.group(1))
    name = url.split("?")[0].rstrip("/").split("/")[-1]
    return slugify_filename(name) or "download.bin"


def _dropbox_direct(url: str) -> str:
    if "dl=1" in url:
        return url
    if "dl=0" in url:
        return url.replace("dl=0", "dl=1")
    return url + ("&dl=1" if "?" in url else "?dl=1")


def download_external(url: str, dest_dir: Path, max_bytes: int = MAX_BYTES) -> tuple[str, str]:
    """Télécharge un lien externe (JAMAIS d'auth CTFd). (statut, détail)."""
    kind = classify_link(url)
    if kind == "gdrive":
        try:
            import gdown
            if "/folders/" in url:
                outs = gdown.download_folder(url=url, output=str(dest_dir), quiet=True, use_cookies=False)
                return ("ok", f"{len(outs)} fichier(s)") if outs else ("manual", "Drive (dossier) : échec (manuel)")
            m = re.search(r'/d/([\w-]+)', url) or re.search(r'[?&]id=([\w-]+)', url)
            fid = m.group(1) if m else None
            out = (gdown.download(id=fid, output=str(dest_dir) + "/", quiet=True)
                   if fid else gdown.download(url=url, output=str(dest_dir) + "/", quiet=True))
            if not out:
                return "manual", "Google Drive : échec (manuel)"
            try:
                if Path(out).stat().st_size > max_bytes:
                    Path(out).unlink(missing_ok=True)
                    return "manual", "> 2 Go (manuel)"
            except OSError:
                pass
            return "ok", out
        except Exception as e:  # noqa: BLE001
            msg = "lien privé ou accès refusé" if "Cannot retrieve" in str(e) else str(e).splitlines()[0]
            return "manual", f"Google Drive : {msg} (manuel)"
    if kind == "mega":
        tool = shutil.which("megadl") or shutil.which("megatools")
        if not tool:
            return "manual", "MEGA : pas d'outil (megatools) — manuel"
        try:
            cmd = ([tool, "--path", str(dest_dir), url] if tool.endswith("megadl")
                   else [tool, "dl", "--path", str(dest_dir), url])
            subprocess.run(cmd, check=True, timeout=600, capture_output=True)
            return "ok", "MEGA"
        except Exception as e:  # noqa: BLE001
            return "manual", f"MEGA : {e} (manuel)"
    if kind == "dropbox":
        url = _dropbox_direct(url)
    # http / dropbox direct : requête SANS auth
    try:
        r = requests.get(url, stream=True, timeout=60, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        return "error", str(e)
    size = int(r.headers.get("Content-Length") or 0)
    if size and size > max_bytes:
        r.close()
        return "manual", f"{size/1024**3:.1f} Go > 2 Go (manuel)"
    return _stream_to(r, dest_dir / _filename_from(r, url), max_bytes)


def _do_downloads(client, d: Path, detail, file_urls, ext_links) -> list[str]:
    work = d / "work"
    work.mkdir(parents=True, exist_ok=True)
    report = []
    for f in detail.get("files") or []:
        base = Path(f.split("?")[0]).name
        dest = work / base
        if dest.exists():
            report.append(f"[skip] work/{base} (déjà présent)")
            continue
        status, info = client.download(f, dest)
        report.append(f"[{status}] work/{base} — {info}")
    for u in ext_links:
        status, info = download_external(u, work)
        report.append(f"[{status}] {u} — {info}")
    if report:
        (d / "downloads.txt").write_text(
            "# Rapport de téléchargement Flagship (fichiers -> work/)\n"
            "# ok = téléchargé · manual = à faire soi-même (lien dans desc.txt) · error\n\n"
            + "\n".join(report) + "\n", encoding="utf-8")
    return report


# ------------------------------------------------------------------ cœur
def _auto_unlock_free(client, detail: dict) -> dict:
    """Débloque les indices à coût 0 encore verrouillés, puis re-récupère le détail."""
    locked_free = [h for h in (detail.get("hints") or []) if h.get("cost", 0) == 0 and not h.get("content")]
    if not locked_free:
        return detail
    for h in locked_free:
        try:
            client.unlock_hint(h["id"])
        except CTFdError:
            pass
    try:
        return client.challenge(detail["id"])
    except CTFdError:
        return detail


def ensure_challenge(client: CTFd, base_dir: Path, summary: dict, watch: bool,
                     auto_free_hints: bool = False):
    d = Path(summary["path"]) if summary.get("path") else challenge_dir(
        base_dir, summary.get("category", ""), summary.get("name", ""))
    (d / "work").mkdir(parents=True, exist_ok=True)
    events, name = [], summary.get("name", "?")
    desc = d / "desc.txt"

    need_detail = watch or not desc.exists()
    detail = client.challenge(summary["id"]) if need_detail else None
    if detail is None:
        return d, events, None
    if auto_free_hints:
        detail = _auto_unlock_free(client, detail)

    file_urls = [(Path(f.split("?")[0]).name, client.file_url(f)) for f in (detail.get("files") or [])]
    ext_links = extract_links(detail.get("description"))
    desc_hash = _sig(clean_desc(detail.get("description")))
    hints_now = _hints_state(detail)
    state = _load_state(d)

    if not desc.exists():
        desc.write_text(_desc_text(detail, file_urls, ext_links), encoding="utf-8")
        _do_downloads(client, d, detail, file_urls, ext_links)
        _save_state(d, {"desc_hash": desc_hash, "hints": hints_now, "version": 1})
        events.append({"kind": "new", "name": name})
        return d, events, detail

    if not state:
        _save_state(d, {"desc_hash": desc_hash, "hints": hints_now, "version": 1})
        return d, events, detail
    if not watch:
        return d, events, detail

    desc_changed = state.get("desc_hash") != desc_hash
    hint_evs = _hint_events(state.get("hints", []), hints_now, name)
    hints_changed = bool(hint_evs) or (state.get("hints") != hints_now)
    if desc_changed or hints_changed:
        version = int(state.get("version", 1)) + 1
        what = []
        if desc_changed:
            what.append("description")
            events.append({"kind": "desc", "name": name, "version": version,
                           "msg": f"description modifiée → desc{version}.txt"})
        if hints_changed:
            what.append("indices")
        events.extend(hint_evs)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# Version {version} — {ts} (changement : {', '.join(what)})\n\n"
        (d / f"desc{version}.txt").write_text(_desc_text(detail, file_urls, ext_links, header), encoding="utf-8")
        _save_state(d, {"desc_hash": desc_hash, "hints": hints_now, "version": version})
    return d, events, detail


def download_one(client, base_dir, summary, watch=True, auto_free_hints=False):
    """Télécharge/complète UN challenge, de façon AUTO-RÉPARATRICE.

    - passe toujours par `ensure_challenge` → recrée `desc.txt` (+ état) s'il manque, puis
      télécharge les fichiers (branche « nouveau ») ;
    - si le dossier préexistait, (re)complète les fichiers manquants/échoués dans `work/`
      (idempotent : les fichiers déjà présents sont sautés).
    Retourne (chemin, events). Jamais de `work/`/`downloads.txt` sans `desc.txt`.
    """
    d, events, detail = ensure_challenge(client, base_dir, summary, watch, auto_free_hints)
    fresh = any(e.get("kind") == "new" for e in events)  # desc.txt venait d'être (re)créé -> déjà téléchargé
    if not fresh:
        if detail is None:
            detail = client.challenge(summary["id"])
            if auto_free_hints:
                detail = _auto_unlock_free(client, detail)
        file_urls = [(Path(f.split("?")[0]).name, client.file_url(f)) for f in (detail.get("files") or [])]
        ext_links = extract_links(detail.get("description"))
        _do_downloads(client, d, detail, file_urls, ext_links)
    return str(d), events


def list_state(client: CTFd, base_dir: Path, watch: bool = True, auto_free_hints: bool = False):
    """Mode LÉGER : liste sans télécharger. Re-vérifie les changements pour les déjà-téléchargés."""
    base_dir.mkdir(parents=True, exist_ok=True)
    challenges = client.challenges()
    solved = client.solved_ids()
    assign_paths(challenges, base_dir)
    all_events = []
    for ch in challenges:
        d = Path(ch["path"])
        downloaded = (d / "desc.txt").exists()
        ch["downloaded"] = downloaded
        ch["solved"] = int(ch.get("id", -1)) in solved or _has_flag(str(d))
        if downloaded and watch:
            try:
                _, evs, detail = ensure_challenge(client, base_dir, ch, True, auto_free_hints)
                all_events.extend(evs)
                if detail:
                    ch["_detail"] = detail
            except CTFdError:
                pass
    save_cache(base_dir, challenges)
    return challenges, all_events


def sync(client: CTFd, base_dir: Path, watch: bool = True, auto_free_hints: bool = False,
         workers: int = 6, progress=None):
    """Mode COMPLET (« Tout synchroniser »), téléchargements PARALLÈLES + progression."""
    base_dir.mkdir(parents=True, exist_ok=True)
    challenges = client.challenges()
    solved = client.solved_ids()
    assign_paths(challenges, base_dir)
    all_events, lock = [], threading.Lock()
    total, done = len(challenges), 0

    def task(ch):
        try:
            _, evs, detail = ensure_challenge(client, base_dir, ch, watch, auto_free_hints)
            ch["downloaded"] = (Path(ch["path"]) / "desc.txt").exists()
            if detail:
                ch["_detail"] = detail
            return evs
        except CTFdError:
            ch["downloaded"] = False
            return []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(task, ch): ch for ch in challenges}
        for fut in as_completed(futs):
            evs = fut.result() or []
            with lock:
                all_events.extend(evs)
            done += 1
            if progress:
                progress(done, total)
    for ch in challenges:
        ch["solved"] = int(ch.get("id", -1)) in solved or _has_flag(ch.get("path"))
    save_cache(base_dir, challenges)
    return challenges, all_events


# ------------------------------------------------------------------ divers
def _cache_path(base_dir: Path) -> Path:
    return base_dir / ".flagship" / "challenges_cache.json"


def save_cache(base_dir: Path, challenges: list[dict]) -> None:
    """Mémorise la dernière liste synchronisée (pour le mode hors-ligne)."""
    try:
        p = _cache_path(base_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(challenges, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError):
        pass


def load_cache(base_dir: Path) -> list[dict]:
    """Relit la dernière liste synchronisée (liste vide si aucune)."""
    try:
        return json.loads(_cache_path(base_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _has_flag(path):
    return bool(path) and (Path(path) / "flag.txt").exists()


def write_flag(path, flag: str) -> None:
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "flag.txt"
    if not p.exists():
        p.write_text(flag.strip() + "\n", encoding="utf-8")


def write_progress(base_dir: Path, challenges: list[dict], ctf_name: str = "CTF") -> Path:
    """Génère un PROGRESS.md récapitulatif à la racine de base_dir."""
    rows = sorted(challenges, key=lambda c: (c.get("category", ""), c.get("value", 0), c.get("name", "")))
    solved = sum(1 for c in challenges if c.get("solved"))
    dl = sum(1 for c in challenges if c.get("downloaded"))
    lines = [
        f"# PROGRESS — {ctf_name}", "",
        f"{solved}/{len(challenges)} résolus · {dl} téléchargés · "
        f"généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
        "| Catégorie | Challenge | Points | Solves | Résolu | Téléchargé |",
        "|-----------|-----------|--------|--------|--------|------------|",
    ]
    for c in rows:
        lines.append(
            f"| {c.get('category','?')} | {c.get('name','?')} | {c.get('value','')} | "
            f"{c.get('solves','')} | {'✔' if c.get('solved') else ''} | "
            f"{'✓' if c.get('downloaded') else ''} |")
    # nom DISTINCT : ne jamais écraser un PROGRESS.md maintenu à la main par l'utilisateur
    out = base_dir / "PROGRESS_flagship.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
