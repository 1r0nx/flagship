"""API -> filesystem synchronisation.

Conventions:
- tree: <base_dir>/CHALLENGES/<Category>/<Challenge-name>/
  (the <base_dir> root stays reserved for config.sh, PROGRESS.md, .flagship/…)
- naming: spaces -> '-', never consecutive dashes; on a name collision within the same
  category, the challenge id is appended as a suffix.
- downloaded files go in <challenge>/work/; desc.txt/downloads.txt at the challenge root.
- idempotent: never deletes/overwrites an existing desc.txt; desc/hint changes -> descN.txt.
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

MAX_BYTES = 2 * 1024**3  # 2 GB: beyond that -> manual
CHALLENGES = "CHALLENGES"  # subfolder holding the categories (root reserved for config.sh, etc.)

_FORBIDDEN = re.compile(r'[/\\\x00]')
_SPACES = re.compile(r"\s+")
_DASHES = re.compile(r"-{2,}")
_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')


# ------------------------------------------------------------------ naming
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
    """Set `ch['path']` for each challenge, with collision avoidance (-id suffix)."""
    root = base_dir / CHALLENGES
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ch in challenges:
        key = (slugify(ch.get("category", "Uncategorized")), slugify(ch.get("name", "challenge")))
        buckets[key].append(ch)
    for (cat, name), group in buckets.items():
        if len(group) == 1:
            group[0]["path"] = str(root / cat / name)
        else:  # collision -> id suffix
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
        return "none"
    parts = []
    for h in hints:
        cost = h.get("cost", 0)
        tag = "free" if cost == 0 else f"{cost} pts"
        if h.get("content"):
            parts.append(f'[{h.get("id")}] (unlocked, {tag}) "{h["content"]}"')
        else:
            parts.append(f'[{h.get("id")}] (locked, {tag})')
    return "\n            ".join(parts)


def _files_block(file_urls: list[tuple[str, str]]) -> str:
    if not file_urls:
        return "none"
    return "\n" + "\n".join(f"            - work/{n} : {u}" for n, u in file_urls)


def _ext_block(ext_links: list[str]) -> str:
    if not ext_links:
        return "none"
    return "\n" + "\n".join(f"            - [{classify_link(u)}] {u}" for u in ext_links)


def prereq_ids(detail: dict) -> list:
    """Ids of prerequisite challenges (CTFd `requirements`), whatever the format."""
    req = detail.get("requirements")
    if isinstance(req, dict):
        return list(req.get("prerequisites") or [])
    if isinstance(req, list):
        return list(req)
    return []


def _desc_text(detail: dict, file_urls, ext_links, header: str = "") -> str:
    pr = prereq_ids(detail)
    prereq = ", ".join(str(i) for i in pr) if pr else "none"
    body = (
        f"Name       : {detail.get('name','?')}\n"
        f"Category   : {detail.get('category','?')}\n"
        f"Points     : {detail.get('value','?')}\n"
        f"Solves     : {detail.get('solves','?')}\n"
        f"ID         : {detail.get('id','?')}\n\n"
        f"Description:\n{clean_desc(detail.get('description'))}\n\n"
        f"Connection: {detail.get('connection_info') or 'none'}\n"
        f"Prerequisites (ids): {prereq}\n"
        f"Files (platform, -> work/): {_files_block(file_urls)}\n"
        f"External links: {_ext_block(ext_links)}\n"
        f"Hints      : {_hints_lines(detail)}\n"
    )
    return (header + body) if header else body


# ------------------------------------------------------------------ state
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
        tag = "free" if nh["cost"] == 0 else f"{nh['cost']} pts"
        if oid not in old_by:
            ev.append({"kind": "hint", "name": name, "msg": f"new hint #{oid} ({tag})"})
        else:
            o = old_by[oid]
            if not o["unlocked"] and nh["unlocked"]:
                ev.append({"kind": "hint", "name": name, "msg": f"hint #{oid} unlocked"})
            elif o["cost"] != nh["cost"]:
                ev.append({"kind": "hint", "name": name, "msg": f"hint #{oid}: cost {o['cost']}→{nh['cost']}"})
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
    """Download an external link (NEVER with CTFd auth). (status, detail)."""
    kind = classify_link(url)
    if kind == "gdrive":
        try:
            import gdown
            if "/folders/" in url:
                outs = gdown.download_folder(url=url, output=str(dest_dir), quiet=True, use_cookies=False)
                return ("ok", f"{len(outs)} file(s)") if outs else ("manual", "Drive (folder): failed (manual)")
            m = re.search(r'/d/([\w-]+)', url) or re.search(r'[?&]id=([\w-]+)', url)
            fid = m.group(1) if m else None
            out = (gdown.download(id=fid, output=str(dest_dir) + "/", quiet=True)
                   if fid else gdown.download(url=url, output=str(dest_dir) + "/", quiet=True))
            if not out:
                return "manual", "Google Drive: failed (manual)"
            try:
                if Path(out).stat().st_size > max_bytes:
                    Path(out).unlink(missing_ok=True)
                    return "manual", "> 2 GB (manual)"
            except OSError:
                pass
            return "ok", out
        except Exception as e:  # noqa: BLE001
            msg = "private link or access denied" if "Cannot retrieve" in str(e) else str(e).splitlines()[0]
            return "manual", f"Google Drive: {msg} (manual)"
    if kind == "mega":
        tool = shutil.which("megadl") or shutil.which("megatools")
        if not tool:
            return "manual", "MEGA: megatools not installed, manual retrieval"
        try:
            cmd = ([tool, "--path", str(dest_dir), url] if tool.endswith("megadl")
                   else [tool, "dl", "--path", str(dest_dir), url])
            subprocess.run(cmd, check=True, timeout=600, capture_output=True)
            return "ok", "MEGA"
        except Exception as e:  # noqa: BLE001
            return "manual", f"MEGA: {e} (manual)"
    if kind == "dropbox":
        url = _dropbox_direct(url)
    # direct http / dropbox: request WITHOUT auth
    try:
        r = requests.get(url, stream=True, timeout=60, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        return "error", str(e)
    size = int(r.headers.get("Content-Length") or 0)
    if size and size > max_bytes:
        r.close()
        return "manual", f"{size/1024**3:.1f} GB > 2 GB (manual)"
    dest = dest_dir / _filename_from(r, url)
    if dest.exists():  # never overwrite an already-present file
        r.close()
        return "skip", f"{dest.name} (already present)"
    return _stream_to(r, dest, max_bytes)


def _do_downloads(client, d: Path, detail, file_urls, ext_links) -> list[str]:
    work = d / "work"
    work.mkdir(parents=True, exist_ok=True)
    report = []
    for f in detail.get("files") or []:
        base = Path(f.split("?")[0]).name
        dest = work / base
        if dest.exists():
            report.append(f"[skip] work/{base} (already present)")
            continue
        status, info = client.download(f, dest)
        report.append(f"[{status}] work/{base} : {info}")
    for u in ext_links:
        status, info = download_external(u, work)
        report.append(f"[{status}] {u} : {info}")
    if report:
        (d / "downloads.txt").write_text(
            "# Flagship download report (files -> work/)\n"
            "# ok = downloaded · skip = already present (not overwritten) · "
            "manual = to be done by hand (link in desc.txt) · error\n\n"
            + "\n".join(report) + "\n", encoding="utf-8")
    return report


# ------------------------------------------------------------------ core
def _auto_unlock_free(client, detail: dict) -> dict:
    """Unlock cost-0 hints that are still locked, then re-fetch the detail."""
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
                           "msg": f"description changed → desc{version}.txt"})
        if hints_changed:
            what.append("hints")
        events.extend(hint_evs)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# Version {version} · {ts} (changed: {', '.join(what)})\n\n"
        (d / f"desc{version}.txt").write_text(_desc_text(detail, file_urls, ext_links, header), encoding="utf-8")
        _save_state(d, {"desc_hash": desc_hash, "hints": hints_now, "version": version})
    return d, events, detail


def download_one(client, base_dir, summary, watch=True, auto_free_hints=False):
    """Download/complete ONE challenge, in a SELF-HEALING way.

    - always goes through `ensure_challenge` → recreates `desc.txt` (+ state) if missing, then
      downloads the files ("new" branch);
    - if the folder already existed, (re)completes missing/failed files in `work/`
      (idempotent: files already present are skipped).
    Returns (path, events). Never a `work/`/`downloads.txt` without `desc.txt`.
    """
    d, events, detail = ensure_challenge(client, base_dir, summary, watch, auto_free_hints)
    fresh = any(e.get("kind") == "new" for e in events)  # desc.txt was just (re)created -> already downloaded
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
    """LIGHT mode: list without downloading. Re-checks changes for already-downloaded ones."""
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
    """FULL mode ("Sync all"), PARALLEL downloads + progress."""
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


def download_subset(client: CTFd, base_dir: Path, summaries: list[dict], watch: bool = True,
                    auto_free_hints: bool = False, workers: int = 6, progress=None):
    """Download a SUBSET of challenges (e.g. a category), in parallel.

    `summaries` are already-listed entries (with their `path`). The dicts are mutated in place
    (`downloaded`, `_detail`) to reflect the state. Returns (summaries, events).
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    all_events, lock = [], threading.Lock()
    total, done = len(summaries), 0

    def task(ch):
        try:
            _, evs, detail = ensure_challenge(client, base_dir, ch, watch, auto_free_hints)
            d = Path(ch["path"]) if ch.get("path") else challenge_dir(
                base_dir, ch.get("category", ""), ch.get("name", ""))
            ch["downloaded"] = (d / "desc.txt").exists()
            if detail:
                ch["_detail"] = detail
            return evs
        except CTFdError:
            return []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(task, ch): ch for ch in summaries}
        for fut in as_completed(futs):
            with lock:
                all_events.extend(fut.result() or [])
            done += 1
            if progress:
                progress(done, total)
    return summaries, all_events


# ------------------------------------------------------------------ cache (offline mode)
def save_json(base_dir: Path, name: str, data) -> None:
    """Write a JSON cache to <base>/.flagship/<name> (silent on failure)."""
    try:
        d = base_dir / ".flagship"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError):
        pass


def load_json(base_dir: Path, name: str, default=None):
    """Read a JSON cache back; returns `default` if missing/unreadable."""
    try:
        return json.loads((base_dir / ".flagship" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_cache(base_dir: Path, challenges: list[dict]) -> None:
    """Remember the last synced challenge list (offline mode)."""
    save_json(base_dir, "challenges_cache.json", challenges)


def load_cache(base_dir: Path) -> list[dict]:
    """Read back the last synced challenge list (empty list if none)."""
    return load_json(base_dir, "challenges_cache.json", []) or []


def _has_flag(path):
    return bool(path) and (Path(path) / "flag.txt").exists()


def write_flag(path, flag: str) -> None:
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "flag.txt"
    if not p.exists():
        p.write_text(flag.strip() + "\n", encoding="utf-8")


# ------------------------------------------------------------ flag attempts
def _attempts_path(base_dir: Path) -> Path:
    return base_dir / ".flagship" / "attempts.json"


def load_attempts(base_dir: Path) -> dict:
    """Central index {challenge_id: [incorrect flags already submitted]}."""
    try:
        return json.loads(_attempts_path(base_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def was_attempted(base_dir: Path, cid: int, flag: str) -> bool:
    """True if this flag was ALREADY submitted and rejected for this challenge."""
    return flag.strip() in load_attempts(base_dir).get(str(cid), [])


def record_attempt(base_dir: Path, cid: int, flag: str, correct: bool, path: str | None = None) -> None:
    """Log an attempt. Remembers INCORRECT flags to avoid resubmitting them.

    - Writes a readable `attempts.log` in the challenge folder (if present), useful for a
      writeup; never overwrites anything (append only).
    - Indexes incorrect flags in `.flagship/attempts.json` (resubmission guard).
    """
    flag = flag.strip()
    if path:
        d = Path(path)
        if d.exists():
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(d / "attempts.log", "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] {'OK ' if correct else 'KO '} : {flag}\n")
            except OSError:
                pass
    if correct:
        return
    try:
        p = _attempts_path(base_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = load_attempts(base_dir)
        lst = data.setdefault(str(cid), [])
        if flag not in lst:
            lst.append(flag)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError):
        pass


def write_progress(base_dir: Path, challenges: list[dict], ctf_name: str = "CTF") -> Path:
    """Generate a PROGRESS_flagship.md summary at the root of base_dir."""
    rows = sorted(challenges, key=lambda c: (c.get("category", ""), c.get("value", 0), c.get("name", "")))
    solved = sum(1 for c in challenges if c.get("solved"))
    dl = sum(1 for c in challenges if c.get("downloaded"))
    lines = [
        f"# PROGRESS · {ctf_name}", "",
        f"{solved}/{len(challenges)} solved · {dl} downloaded · "
        f"generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
        "| Category | Challenge | Points | Solves | Solved | Downloaded |",
        "|----------|-----------|--------|--------|--------|------------|",
    ]
    for c in rows:
        lines.append(
            f"| {c.get('category','?')} | {c.get('name','?')} | {c.get('value','')} | "
            f"{c.get('solves','')} | {'✔' if c.get('solved') else ''} | "
            f"{'✓' if c.get('downloaded') else ''} |")
    # DISTINCT name: never overwrite a PROGRESS.md the user maintains by hand
    out = base_dir / "PROGRESS_flagship.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
