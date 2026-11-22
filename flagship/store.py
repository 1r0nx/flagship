"""API -> filesystem synchronisation.

Conventions:
- tree: <base_dir>/CHALLENGES/<Category>/<Challenge-name>/
  (the <base_dir> root stays reserved for config.sh, PROGRESS.md, .flagship/…)
- naming: spaces -> '-', never consecutive dashes; on a name collision within the same
  category, the challenge id is appended as a suffix.
- downloaded files go in <nom-du-challenge>/work/; <nom-du-challenge>.txt/downloads.txt at the challenge root.
- idempotent: never deletes/overwrites an existing <nom-du-challenge>.txt; desc/hint changes -> <nom-du-challenge>-vN.txt.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

from . import shutdown
from .ctfd import CTFd, CTFdError, _stream_to

MAX_BYTES = 2 * 1024**3  # 2 GB: beyond that -> manual
CHALLENGES = "CHALLENGES"  # subfolder holding the categories (root reserved for config.sh, etc.)

_FORBIDDEN = re.compile(r'[/\\\x00]')
# shell metacharacters that need quoting/escaping to use literally on a command line (space is
# handled separately, by _SPACES) ; dropped outright rather than turned into a dash, so
# "Anakin's PC" -> "Anakins-PC", not "Anakin's-PC"
_SHELL_SPECIAL = re.compile(r"""['"`$!;&|()<>{}\[\]*?~#=%^]""")
_SPACES = re.compile(r"\s+")
_DASHES = re.compile(r"-{2,}")
_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')


# ------------------------------------------------------------------ atomic writes
def write_text_atomic(path, text: str) -> None:
    """Write a whole text file in one step: a temporary sibling, then a rename. A quit or a crash in
    the middle of the write leaves the previous version (or nothing), never a truncated file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ naming
def slugify(name: str) -> str:
    s = _FORBIDDEN.sub("-", name.strip())
    s = _SHELL_SPECIAL.sub("", s)
    s = _SPACES.sub("-", s)
    s = _DASHES.sub("-", s)
    s = s.strip("-")
    # "." / ".." as a lone path component is a directory-traversal primitive (`category_dir / ".."`
    # escapes CHALLENGES/ entirely) ; neither survives sanitisation below, so guard them explicitly
    if not s or s in (".", ".."):
        return "challenge"
    return s


def slugify_filename(name: str) -> str:
    s = _FORBIDDEN.sub("_", name).strip()
    if not s or s in (".", ".."):
        return "download.bin"
    return s


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


# ------------------------------------------------------------------ <nom-du-challenge>.txt
def _desc_name(folder_name: str, version: int = 1) -> str:
    """<nom-du-challenge>.txt for the statement, <nom-du-challenge>-vN.txt once the statement changed."""
    return f"{folder_name}.txt" if version == 1 else f"{folder_name}-v{version}.txt"


def migrate_desc_names(d: Path) -> list:
    """Rename legacy desc.txt / descN.txt files in a challenge folder to the <nom-du-challenge>.txt scheme.
    Never overwrites: if the target already exists, the legacy file is left as it is."""
    moved = []
    for p in sorted(d.glob("desc*.txt")):
        m = re.fullmatch(r"desc(\d*)\.txt", p.name)
        if not m:
            continue
        target = d / _desc_name(d.name, int(m.group(1) or 1))
        if target.exists():
            continue
        p.rename(target)
        moved.append((p.name, target.name))
    return moved


def ensure_notes(d: Path, summary: dict) -> Path:
    """Create the notes file <nom-du-challenge>.md (skeleton) if it is missing. Never overwrites it."""
    notes = d / f"{d.name}.md"
    if not notes.exists():
        notes.write_text(
            f"# {summary.get('name','?')}\n"
            f"**Category:** {summary.get('category','?')} | "
            f"**Points:** {summary.get('value','?')}\n\n## Notes\n\n", encoding="utf-8")
    return notes


def desc_file(d: Path, version: int = 1) -> Path:
    """Path of the statement file of a challenge folder (also migrates legacy names first)."""
    d = Path(d)
    if d.is_dir():
        migrate_desc_names(d)
    return d / _desc_name(d.name, version)


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
    write_text_atomic(_state_path(d), json.dumps(state, ensure_ascii=False, indent=2))


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
def file_name_of(file_path: str) -> str:
    """Local file name for a platform file path (query string dropped, sanitised)."""
    return slugify_filename(Path(file_path.split("?")[0]).name)


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


def _looks_like_page(r: requests.Response) -> bool:
    """True if the response is a web page (HTML), not a downloadable file.
    A page link is kept in <nom-du-challenge>.txt but NOT saved into work/."""
    if "attachment" in r.headers.get("Content-Disposition", "").lower():
        return False  # server explicitly offers a file to save
    ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    return ctype.startswith("text/html") or ctype == "application/xhtml+xml"


def download_external(url: str, dest_dir: Path, max_bytes: int = MAX_BYTES, on_bytes=None) -> tuple[str, str]:
    """Download an external link (NEVER with CTFd auth). (status, detail).
    `on_bytes(written, total)` reports progress for direct http/dropbox links (total=0 if unknown)."""
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
    if _looks_like_page(r):  # a web page, not a file: keep the link in <nom-du-challenge>.txt only
        r.close()
        return "page", "web page, left in <nom-du-challenge>.txt (not downloaded)"
    size = int(r.headers.get("Content-Length") or 0)
    if size and size > max_bytes:
        r.close()
        return "manual", f"{size/1024**3:.1f} GB > 2 GB (manual)"
    dest = dest_dir / _filename_from(r, url)
    if dest.exists():  # never overwrite an already-present file
        r.close()
        return "skip", f"{dest.name} (already present)"
    return _stream_to(r, dest, max_bytes, on_bytes=on_bytes, total=size)


_SETTLED = ("ok", "skip", "page")  # external links that need no new request on a later pass
_REPORT_LINE = re.compile(r"^\[(\w+)\] (.+?) : ")


def _settled_links(d: Path) -> dict[str, str]:
    """{target: report line} of the previous pass for external links that are settled (fetched,
    already present, or a web page). Re-requesting them on every full sync is pure waste."""
    p = d / "downloads.txt"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _REPORT_LINE.match(line)
        if m and m.group(1) in _SETTLED:
            out[m.group(2)] = line
    return out


def _do_downloads(client, d: Path, detail, ext_links, on_file=None, on_bytes=None) -> list[str]:
    """Download a challenge's files into work/. Optional progress callbacks (used by the single
    `d` download): `on_file(name, index, n_items)` when each file starts, `on_bytes(name, written,
    total)` as its bytes arrive. Both are None in the parallel sync paths (no per-file bar there)."""
    work = d / "work"
    work.mkdir(parents=True, exist_ok=True)
    report = []
    files = detail.get("files") or []
    n_items = len(files) + len(ext_links)
    idx = 0
    for f in files:
        if shutdown.requested():
            break
        base = file_name_of(f)
        idx += 1
        if on_file:
            on_file(base, idx, n_items)
        dest = work / base
        if dest.exists():
            report.append(f"[skip] work/{base} (already present)")
            continue
        cb = (lambda w, t, _n=base: on_bytes(_n, w, t)) if on_bytes else None
        status, info = client.download(f, dest, on_bytes=cb)
        report.append(f"[{status}] work/{base} : {info}")
    settled = _settled_links(d)
    for u in ext_links:
        if shutdown.requested():
            break
        idx += 1
        name = u.split("?")[0].rstrip("/").split("/")[-1] or u
        if u in settled:  # already handled by an earlier pass: keep its report line, no request
            report.append(settled[u])
            continue
        if on_file:
            on_file(name, idx, n_items)
        cb = (lambda w, t, _n=name: on_bytes(_n, w, t)) if on_bytes else None
        status, info = download_external(u, work, on_bytes=cb)
        report.append(f"[{status}] {u} : {info}")
    if report:
        write_text_atomic(d / "downloads.txt",
            "# Flagship download report (files -> work/)\n"
            "# ok = downloaded · skip = already present (not overwritten) · "
            "page = web page (kept in <nom-du-challenge>.txt, not saved) · "
            "manual = to be done by hand (link in <nom-du-challenge>.txt) · error\n\n"
            + "\n".join(report) + "\n")
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
                     auto_free_hints: bool = False, on_file=None, on_bytes=None, auto_notes: bool = False):
    d = Path(summary["path"]) if summary.get("path") else challenge_dir(
        base_dir, summary.get("category", ""), summary.get("name", ""))
    if shutdown.requested():  # quitting: start nothing new
        return d, [], None
    (d / "work").mkdir(parents=True, exist_ok=True)
    if auto_notes:
        ensure_notes(d, summary)
    events, name = [], summary.get("name", "?")
    desc = desc_file(d)

    need_detail = watch or not desc.exists()
    detail = client.challenge(summary["id"]) if need_detail else None
    if detail is None:
        return d, events, None
    if auto_free_hints:
        detail = _auto_unlock_free(client, detail)

    file_urls = [(file_name_of(f), client.file_url(f)) for f in (detail.get("files") or [])]
    ext_links = extract_links(detail.get("description"))
    desc_hash = _sig(clean_desc(detail.get("description")))
    hints_now = _hints_state(detail)
    state = _load_state(d)

    if not desc.exists():
        write_text_atomic(desc, _desc_text(detail, file_urls, ext_links))
        _do_downloads(client, d, detail, ext_links, on_file, on_bytes)
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
                           "msg": f"description changed → {_desc_name(d.name, version)}"})
        if hints_changed:
            what.append("hints")
        events.extend(hint_evs)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# Version {version} · {ts} (changed: {', '.join(what)})\n\n"
        write_text_atomic(desc_file(d, version), _desc_text(detail, file_urls, ext_links, header))
        _save_state(d, {"desc_hash": desc_hash, "hints": hints_now, "version": version})
    return d, events, detail


def download_one(client, base_dir, summary, watch=True, auto_free_hints=False, on_file=None, on_bytes=None, auto_notes: bool = False):
    """Download/complete ONE challenge, in a SELF-HEALING way.

    - always goes through `ensure_challenge` → recreates `<nom-du-challenge>.txt` (+ state) if missing, then
      downloads the files ("new" branch);
    - if the folder already existed, (re)completes missing/failed files in `work/`
      (idempotent: files already present are skipped).
    Returns (path, events). Never a `work/`/`downloads.txt` without `<nom-du-challenge>.txt`.
    """
    d, events, detail = ensure_challenge(client, base_dir, summary, watch, auto_free_hints,
                                         on_file=on_file, on_bytes=on_bytes, auto_notes=auto_notes)
    if not _is_fresh(events):
        complete_downloads(client, d, summary, detail, auto_free_hints, on_file, on_bytes)
    return str(d), events


def _is_fresh(events: list[dict]) -> bool:
    """True when ensure_challenge just created the statement, i.e. its files were already downloaded."""
    return any(e.get("kind") == "new" for e in events)


def complete_downloads(client, d: Path, summary: dict, detail: dict | None, auto_free_hints: bool = False,
                       on_file=None, on_bytes=None) -> list[str]:
    """(Re)complete the files of one challenge: whatever is missing in work/ is downloaded, what is
    already there is skipped. `detail` may be None (fetched here if needed)."""
    if shutdown.requested():  # quitting: start nothing new
        return []
    if detail is None:
        detail = client.challenge(summary["id"])
        if auto_free_hints:
            detail = _auto_unlock_free(client, detail)
    ext_links = extract_links(detail.get("description"))
    return _do_downloads(client, d, detail, ext_links, on_file, on_bytes)


def list_state(client: CTFd, base_dir: Path, watch: bool = True, auto_free_hints: bool = False,
               should_stop=None, on_connected=None, on_listed=None, workers: int = 6, auto_notes: bool = False):
    """LIGHT mode: list without downloading. Re-checks changes for already-downloaded ones.

    `should_stop` is an optional callable: when it returns True (e.g. the app is quitting), the
    per-challenge watch loop breaks after the current request instead of walking every challenge.
    This keeps quit near-instant on CTFs with many downloaded challenges (each one is a network GET).

    `on_connected` is an optional callable fired once the list is fetched, i.e. as soon as the
    platform is proven reachable, BEFORE the slow per-challenge watch loop. It lets the UI flip to
    "Online" immediately instead of after every challenge's detail GET.

    `on_listed(challenges)` is an optional callable fired once the cheap downloaded/solved flags are
    set (no network), BEFORE the watch loop, so the UI can render the full list right away instead
    of waiting for every challenge's detail GET."""
    base_dir.mkdir(parents=True, exist_ok=True)
    challenges = client.challenges()
    solved = client.solved_ids()
    if on_connected:  # list reachable = online, don't wait for the per-challenge watch loop below
        on_connected()
    assign_paths(challenges, base_dir)
    # cheap first pass (filesystem + set membership, no network): enough to render the list now
    for ch in challenges:
        d = Path(ch["path"])
        ch["downloaded"] = desc_file(d).exists()
        ch["solved"] = int(ch.get("id", -1)) in solved or _has_flag(str(d))
    if on_listed:
        on_listed(challenges)
    # watch loop: one network GET per downloaded challenge to detect desc/hint changes. Run in
    # parallel (each challenge has its own folder, so the writes don't collide) to keep the
    # background refresh short.
    all_events = []
    stopped = False
    if watch:
        todo = [ch for ch in challenges if ch["downloaded"]]

        def _watch_one(ch):
            if (should_stop and should_stop()) or shutdown.requested():  # quitting: skip the GET
                return []
            try:
                _, evs, detail = ensure_challenge(client, base_dir, ch, True, auto_free_hints, auto_notes=auto_notes)
                if detail:
                    ch["_detail"] = detail
                return evs
            except Exception:  # noqa: BLE001  (one bad challenge must never abort the whole poll)
                return []

        if todo:
            ex = ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo))))
            futs = [ex.submit(_watch_one, ch) for ch in todo]
            try:
                for fut in as_completed(futs):
                    if should_stop and should_stop():  # quitting: stop collecting, cancel the rest
                        stopped = True
                        break
                    all_events.extend(fut.result() or [])
            finally:
                # on a quit, don't wait for the in-flight GETs (cancel the queued ones): the join
                # would hold the terminal. Otherwise wait so every detail is folded in.
                ex.shutdown(wait=not stopped, cancel_futures=True)
    if not stopped:  # don't persist a half-walked list (some challenges may miss their _detail)
        save_cache(base_dir, challenges)
    return challenges, all_events


def sync(client: CTFd, base_dir: Path, watch: bool = True, auto_free_hints: bool = False,
         workers: int = 6, progress=None, auto_notes: bool = False):
    """FULL mode ("Sync all"), PARALLEL downloads + progress."""
    base_dir.mkdir(parents=True, exist_ok=True)
    challenges = client.challenges()
    solved = client.solved_ids()
    assign_paths(challenges, base_dir)
    all_events, lock = [], threading.Lock()
    total, done = len(challenges), 0

    def task(ch):
        if shutdown.requested():
            return []
        try:
            d, evs, detail = ensure_challenge(client, base_dir, ch, watch, auto_free_hints, auto_notes=auto_notes)
            if not _is_fresh(evs):  # "download all" also completes files missing from known challenges
                complete_downloads(client, d, ch, detail, auto_free_hints)
            ch["downloaded"] = desc_file(Path(ch["path"])).exists()
            if detail:
                ch["_detail"] = detail
            return evs
        except Exception:  # noqa: BLE001  (one bad challenge must never abort the whole sync)
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
                progress(done, total, futs[fut].get("name", ""))
    for ch in challenges:
        ch["solved"] = int(ch.get("id", -1)) in solved or _has_flag(ch.get("path"))
    save_cache(base_dir, challenges)
    return challenges, all_events


def download_subset(client: CTFd, base_dir: Path, summaries: list[dict], watch: bool = True,
                    auto_free_hints: bool = False, workers: int = 6, progress=None, auto_notes: bool = False):
    """Download a SUBSET of challenges (e.g. a category), in parallel.

    `summaries` are already-listed entries (with their `path`). The dicts are mutated in place
    (`downloaded`, `_detail`) to reflect the state. Returns (summaries, events).
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    all_events, lock = [], threading.Lock()
    total, done = len(summaries), 0

    def task(ch):
        if shutdown.requested():
            return []
        try:
            d, evs, detail = ensure_challenge(client, base_dir, ch, watch, auto_free_hints, auto_notes=auto_notes)
            if not _is_fresh(evs):
                complete_downloads(client, d, ch, detail, auto_free_hints)
            ch["downloaded"] = desc_file(d).exists()
            if detail:
                ch["_detail"] = detail
            return evs
        except Exception:  # noqa: BLE001  (one bad challenge must never abort the whole download)
            return []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(task, ch): ch for ch in summaries}
        for fut in as_completed(futs):
            with lock:
                all_events.extend(fut.result() or [])
            done += 1
            if progress:
                progress(done, total, futs[fut].get("name", ""))
    return summaries, all_events


# ------------------------------------------------------------------ first blood
def fetch_first_bloods(client: CTFd, challenge_ids: list[int], known: dict[int, str],
                       workers: int = 6) -> tuple[dict[int, str], int]:
    """First solver's name for every id in `challenge_ids` not already in `known` (parallel).

    Returns (new_entries, api_errors). Merge `new_entries` into your own cache ; `known` itself
    is not mutated. A challenge's first blood never changes once set, so callers can cache the
    result forever (no need to re-fetch on a later sync). This is why a still-unknown first
    blood (no recorded solve yet, e.g. a locally-flagged solve the server hasn't caught up with)
    is NEVER included here: it must stay retriable on the next call, not frozen as "no one"
    forever.

    `api_errors` counts calls that raised `CTFdError` (as opposed to a clean "no solves yet"),
    e.g. because the CTF has ended. This endpoint is `@during_ctf_time_only` on CTFd, so EVERY
    call fails the same way once it's over. Callers should treat "every attempted id errored" as
    a signal to stop auto-retrying this batch on every poll, not just a handful of "not yet"s.
    """
    todo = [cid for cid in dict.fromkeys(challenge_ids) if cid not in known]
    if not todo:
        return {}, 0
    out: dict[int, str] = {}
    errors = 0
    lock = threading.Lock()

    def task(cid: int) -> None:
        nonlocal errors
        try:
            name = client.first_blood(cid)
        except CTFdError:
            name = None
            with lock:
                errors += 1
        if name is not None:
            with lock:
                out[cid] = name

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(task, todo))
    return out, errors


# ------------------------------------------------------------------ cache (offline mode)
def save_json(base_dir: Path, name: str, data) -> None:
    """Write a JSON cache to <base>/.flagship/<name> (silent on failure)."""
    try:
        d = base_dir / ".flagship"
        d.mkdir(parents=True, exist_ok=True)
        write_text_atomic(d / name, json.dumps(data, ensure_ascii=False))
    except (OSError, TypeError):
        pass


def load_json(base_dir: Path, name: str, default=None):
    """Read a JSON cache back; returns `default` if missing/unreadable."""
    try:
        return json.loads((base_dir / ".flagship" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_cache(base_dir: Path, challenges: list[dict]) -> None:
    """Remember the last synced challenge list (offline mode), and stamp the sync time."""
    save_json(base_dir, "challenges_cache.json", challenges)
    save_json(base_dir, "last_sync.json", {"at": datetime.now().isoformat(timespec="seconds")})


def load_cache(base_dir: Path) -> list[dict]:
    """Read back the last synced challenge list (empty list if none).

    The cached `path`s are absolute and may come from another machine (or a moved folder): they are
    re-anchored on this `base_dir`, and `downloaded` is checked against the disk, so offline views
    read the files that really exist here."""
    challenges = load_json(base_dir, "challenges_cache.json", []) or []
    assign_paths(challenges, base_dir)
    for ch in challenges:
        ch["downloaded"] = desc_file(Path(ch["path"])).exists()
    return challenges


def last_sync_at(base_dir: Path) -> datetime | None:
    """When the challenge list was last fetched successfully, or None if never."""
    raw = (load_json(base_dir, "last_sync.json") or {}).get("at")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _has_flag(path):
    return bool(path) and (Path(path) / "flag.txt").exists()


def write_flag(path, flag: str) -> None:
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "flag.txt"
    if not p.exists():
        write_text_atomic(p, flag.strip() + "\n")


def read_flag(path) -> str | None:
    """The validated flag for a challenge, if `flag.txt` was written (None otherwise)."""
    if not path:
        return None
    try:
        return (Path(path) / "flag.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


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
                    f.write(f"[{ts}] {'OK ' if correct else 'NO '} : {flag}\n")
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
        write_text_atomic(p, json.dumps(data, ensure_ascii=False))
    except (OSError, TypeError):
        pass


def _md_cell(value) -> str:
    """Escape a value for a Markdown table cell: a literal `|` would start a new column and a
    newline would break the row (challenge names / flags are arbitrary text)."""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def write_progress(base_dir: Path, challenges: list[dict], ctf_name: str = "CTF") -> Path:
    """Generate a PROGRESS_flagship.md summary at the root of base_dir."""
    rows = sorted(challenges, key=lambda c: (c.get("category") or "", c.get("value") or 0, c.get("name") or ""))
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
            f"| {_md_cell(c.get('category','?'))} | {_md_cell(c.get('name','?'))} | {c.get('value','')} | "
            f"{c.get('solves','')} | {'✔' if c.get('solved') else ''} | "
            f"{'✓' if c.get('downloaded') else ''} |")
    # DISTINCT name: never overwrite a PROGRESS.md the user maintains by hand
    out = base_dir / "PROGRESS_flagship.md"
    write_text_atomic(out, "\n".join(lines) + "\n")
    return out


def write_flags(base_dir: Path, challenges: list[dict], ctf_name: str = "CTF") -> Path:
    """Generate a FLAGS_flagship.md listing every SOLVED challenge, with its flag when a flag.txt
    holds one (a teammate's solve shows as "(unknown)" until you save the flag yourself)."""
    rows = []
    for c in challenges:
        if not c.get("solved"):
            continue
        flag = read_flag(c.get("path"))
        rows.append((c.get("category", "?"), c.get("name", "?"), c.get("value", ""), flag))
    rows.sort(key=lambda r: (r[0], r[1]))
    known = sum(1 for r in rows if r[3])
    lines = [
        f"# Flags · {ctf_name}", "",
        f"{len(rows)} solved · {known} flag(s) recorded · "
        f"generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
        "| Category | Challenge | Points | Flag |",
        "|----------|-----------|--------|------|",
    ]
    for cat, name, value, flag in rows:
        lines.append(f"| {_md_cell(cat)} | {_md_cell(name)} | {value} | "
                     f"{('`'+_md_cell(flag)+'`') if flag else '(unknown)'} |")
    out = base_dir / "FLAGS_flagship.md"
    write_text_atomic(out, "\n".join(lines) + "\n")
    return out
