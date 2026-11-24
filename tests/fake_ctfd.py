"""A small in-process CTFd emulator for the test-suite (no network, no real platform).

It serves the subset of the CTFd API that Flagship uses, from a mutable in-memory state, so each
test can set up challenges, solves, teams, hints, files and failures precisely.
"""

from __future__ import annotations

import copy
import json
import threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TOKEN = "test-token"


class FakeCTFd:
    def __init__(self) -> None:
        self.challenges: dict[int, dict] = {}   # id -> full detail (as /challenges/<id> returns it)
        self.accepted: dict[int, str] = {}      # id -> correct flag
        self.solved: set[int] = set()           # ids solved by "me"
        self.solves_by: dict[int, list[dict]] = defaultdict(list)  # id -> [{name, date, user}]
        self.attempts: Counter = Counter()      # id -> number of submissions
        self.unlocked_hints: set[int] = set()
        self.team_mode = False
        self.me = {"id": 1, "name": "me", "score": 0, "place": 1}
        self.team = {"id": 7, "name": "TeamX", "score": 0, "place": 1}
        self.team_members = [{"id": 1, "name": "me"}, {"id": 2, "name": "mate"}]
        self.scoreboard: list[dict] = []
        self.notifications: list[dict] = []
        self.files: dict[str, tuple[bytes, dict]] = {}   # url path -> (body, headers)
        self.overrides: dict[tuple[str, str], tuple[int, bytes, str]] = {}  # (METHOD, path) -> reply
        self.hits: Counter = Counter()          # request counter per "METHOD path"
        self.submissions: list[tuple[int, str]] = []
        self.token = TOKEN
        self._lock = threading.Lock()
        self.delays: dict[str, float] = {}      # path prefix -> seconds to wait before answering
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- setup helpers
    def add_challenge(self, cid: int, name: str, category: str = "web", value: int = 100,
                      description: str = "", files: list[str] | None = None,
                      hints: list[dict] | None = None, flag: str | None = None,
                      requirements: list[int] | None = None, **extra) -> dict:
        ch = {
            "id": cid, "name": name, "category": category, "value": value,
            "description": description, "connection_info": None,
            "files": [f"/files/{cid}/{f}?token=secret{cid}" for f in (files or [])],
            "hints": [dict(h) for h in (hints or [])],
            "requirements": {"prerequisites": requirements} if requirements else None,
            "solves": 0, "type": "standard", "state": "visible",
        }
        ch.update(extra)
        self.challenges[cid] = ch
        if flag is not None:
            self.accepted[cid] = flag
        return ch

    def add_file(self, path: str, body: bytes, headers: dict | None = None) -> None:
        """Serve `body` at `path` (query string ignored, like a real download link)."""
        self.files[path.split("?")[0]] = (body, headers or {"Content-Type": "application/octet-stream"})

    def set_override(self, method: str, path: str, status: int, body: bytes = b"{}",
                     ctype: str = "application/json") -> None:
        self.overrides[(method, path)] = (status, body, ctype)

    USER_IDS = {"me": 1, "mate": 2}

    def mark_solved(self, cid: int, by: str = "mate", date: str = "2026-11-20T10:00:00Z") -> None:
        uid = self.USER_IDS.get(by, 3)
        self.solves_by[cid].append({"name": by, "date": date, "user": {"id": uid, "name": by}})
        if by == "me":
            self.solved.add(cid)
        self.challenges[cid]["solves"] = len(self.solves_by[cid])

    # ---------------------------------------------------------------- server lifecycle
    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload) -> None:
                self._send(status, json.dumps(payload).encode(), "application/json")

            def _auth_ok(self) -> bool:
                return self.headers.get("Authorization") == f"Token {fake.token}"

            def _route(self, method: str, body: dict | None):
                path = urlsplit(self.path).path
                for prefix, secs in fake.delays.items():
                    if path.startswith(prefix):
                        import time as _t
                        _t.sleep(secs)
                key = f"{method} {path}"
                with fake._lock:
                    fake.hits[key] += 1
                    ov = fake.overrides.get((method, path))
                if ov:
                    return self._send(ov[0], ov[1], ov[2])
                if path.startswith("/files/"):
                    f = fake.files.get(path)
                    if f is None:
                        return self._json(404, {"success": False, "message": "no file"})
                    return self._send(200, f[0], f[1].get("Content-Type", "application/octet-stream"),
                                      {k: v for k, v in f[1].items() if k != "Content-Type"})
                if not path.startswith("/api/v1/"):
                    return self._json(404, {"success": False, "message": "not found"})
                if not self._auth_ok():
                    return self._json(403, {"success": False, "errors": {"token": "invalid"}})
                return self._api(method, path, body or {})

            def _api(self, method: str, path: str, body: dict):
                f = fake
                if method == "GET":
                    if path == "/api/v1/challenges":
                        data = []
                        for c in f.challenges.values():
                            data.append({k: c[k] for k in ("id", "name", "category", "value", "solves", "type", "state")})
                        return self._json(200, {"success": True, "data": data})
                    if path.startswith("/api/v1/challenges/") and path.endswith("/solves"):
                        cid = int(path.split("/")[4])
                        return self._json(200, {"success": True, "data": f.solves_by.get(cid, [])})
                    if path.startswith("/api/v1/challenges/"):
                        cid = int(path.rsplit("/", 1)[1])
                        if cid not in f.challenges:
                            return self._json(404, {"success": False, "message": "no such challenge"})
                        d = copy.deepcopy(f.challenges[cid])
                        for h in d["hints"]:
                            if h["id"] in f.unlocked_hints:
                                h["content"] = h.get("content") or f"hint {h['id']} text"
                            else:
                                h.pop("content", None)
                        d["attempts"] = f.attempts[cid]
                        return self._json(200, {"success": True, "data": d})
                    if path.startswith("/api/v1/hints/"):
                        hid = int(path.rsplit("/", 1)[1])
                        return self._json(200, {"success": True, "data": {"id": hid, "content": f"hint {hid} text"}})
                    if path in ("/api/v1/users/me", "/api/v1/users/me/"):
                        return self._json(200, {"success": True, "data": dict(f.me)})
                    if path == "/api/v1/teams/me":
                        if not f.team_mode:
                            return self._json(404, {"success": False, "message": "teams disabled"})
                        return self._json(200, {"success": True, "data": dict(f.team)})
                    if path == "/api/v1/users/me/solves":
                        return self._json(200, {"success": True, "data": [
                            {"challenge_id": c, "user": {"id": 1, "name": "me"}, "date": "2026-11-20T10:00:00Z"}
                            for c in sorted(f.solved)]})
                    if path == "/api/v1/teams/me/solves":
                        rows = []
                        for cid, lst in f.solves_by.items():
                            for s in lst:
                                rows.append({"challenge_id": cid, "user": s["user"], "date": s["date"]})
                        return self._json(200, {"success": True, "data": rows})
                    if path == "/api/v1/scoreboard":
                        return self._json(200, {"success": True, "data": list(f.scoreboard)})
                    if path == "/api/v1/notifications":
                        return self._json(200, {"success": True, "data": list(f.notifications)})
                    if path.startswith("/api/v1/users/") and path.endswith("/solves"):
                        uid = int(path.split("/")[4])
                        rows = [self._row(cid, s) for cid, lst in f.solves_by.items() for s in lst
                                if s["user"]["id"] == uid]
                        return self._json(200, {"success": True, "data": rows})
                    if path.startswith("/api/v1/teams/") and path.endswith("/solves"):
                        rows = [self._row(cid, s) for cid, lst in f.solves_by.items() for s in lst]
                        return self._json(200, {"success": True, "data": rows})
                    return self._json(404, {"success": False, "message": "unknown endpoint"})
                if method == "POST":
                    if path == "/api/v1/challenges/attempt":
                        cid = int(body.get("challenge_id", -1))
                        sub = str(body.get("submission", ""))
                        f.submissions.append((cid, sub))
                        if cid in f.solved:
                            return self._json(200, {"success": True, "data": {"status": "already_solved", "message": "already solved"}})
                        f.attempts[cid] += 1
                        if f.accepted.get(cid) == sub:
                            f.solved.add(cid)
                            f.mark_solved(cid, by="me")
                            return self._json(200, {"success": True, "data": {"status": "correct", "message": "Correct"}})
                        return self._json(200, {"success": True, "data": {"status": "incorrect", "message": "Incorrect"}})
                    if path == "/api/v1/unlocks":
                        f.unlocked_hints.add(int(body.get("target", -1)))
                        return self._json(200, {"success": True, "data": {"id": body.get("target")}})
                    return self._json(404, {"success": False, "message": "unknown endpoint"})
                return self._json(405, {"success": False})

            @staticmethod
            def _row(cid, s):
                ch = fake.challenges.get(cid, {})
                return {"challenge_id": cid, "date": s["date"], "user": s["user"],
                        "challenge": {"name": ch.get("name"), "category": ch.get("category"),
                                      "value": ch.get("value")}}

            def do_GET(self):
                self._route("GET", None)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                self._route("POST", body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
