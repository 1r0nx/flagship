"""Minimal CTFd API client (read + submit).

Never logs the token. All methods raise CTFdError on network/API problems,
with a message the TUI can display.
"""

from __future__ import annotations
import requests


class CTFdError(RuntimeError):
    pass


class CTFd:
    def __init__(self, url: str, token: str, timeout: int = 15):
        self.url = url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.timeout = timeout
        self._account_base: str | None = None  # '/api/v1/teams/me' (team) or '/api/v1/users/me' (solo)

    # -- helpers ---------------------------------------------------------
    def _get(self, path: str) -> dict:
        try:
            r = self._session.get(self.url + path, timeout=self.timeout)
        except requests.RequestException as e:
            raise CTFdError(f"network: {e}") from e
        return self._json(r)

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = self._session.post(self.url + path, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise CTFdError(f"network: {e}") from e
        return self._json(r)

    @staticmethod
    def _json(r: requests.Response) -> dict:
        # clear messages depending on the HTTP code
        if r.status_code in (401, 403):
            raise CTFdError("access denied: invalid/expired token or locked challenge (HTTP %d)" % r.status_code)
        if r.status_code == 429:
            raise CTFdError("too many requests (429): try again in a moment (CTFd rate limit)")
        if r.status_code == 404:
            raise CTFdError("not found (404): wrong URL/endpoint or missing resource")
        if r.status_code >= 500:
            raise CTFdError(f"CTFd server error (HTTP {r.status_code})")
        try:
            data = r.json()
        except ValueError:
            raise CTFdError(f"non-JSON response (HTTP {r.status_code}): does the URL really point to a CTFd?")
        if isinstance(data, dict) and data.get("success") is False:
            raise CTFdError(str(data.get("message") or data.get("errors") or "API failure"))
        # some messages (CTF over/not started) arrive without "success"
        if isinstance(data, dict) and "message" in data and "data" not in data and "success" not in data:
            raise CTFdError(str(data["message"]))
        return data

    # -- endpoints -------------------------------------------------------
    def challenges(self) -> list[dict]:
        """List of visible challenges (id, name, category, value, solves...)."""
        return self._get("/api/v1/challenges").get("data", []) or []

    def auth_ok(self) -> bool:
        """True if the token is accepted by the API (GET /users/me succeeds). Used to tell
        an invalid token from a mere access refusal on challenges (CTF over/hidden)."""
        try:
            self._get("/api/v1/users/me")
            return True
        except CTFdError:
            return False

    def challenge(self, cid: int) -> dict:
        """Challenge detail (description, files, hints, connection_info...)."""
        return self._get(f"/api/v1/challenges/{cid}").get("data", {}) or {}

    def _account(self) -> str:
        """Endpoint of the "account" relevant to the competition: the TEAM in team mode,
        otherwise the user. Detected once then remembered.

        In team mode, the score, the rank and above all the SOLVED set that matter are at team
        level (a flag submitted by a teammate must show as solved). `/api/v1/teams/me`
        fails in solo mode (teams disabled): we then fall back to the user.
        """
        if self._account_base is None:
            self._account_base = "/api/v1/users/me"
            try:
                d = self._get("/api/v1/teams/me").get("data") or {}
                if d.get("id"):
                    self._account_base = "/api/v1/teams/me"
            except CTFdError:
                pass
        return self._account_base

    def is_team_mode(self) -> bool:
        """True if the CTF is in team mode (the relevant account is a team)."""
        return self._account().startswith("/api/v1/teams")

    def solved_ids(self) -> set[int]:
        """Set of ids solved by the relevant account (TEAM in team mode, otherwise self)."""
        try:
            data = self._get(self._account() + "/solves").get("data", []) or []
        except CTFdError:
            return set()
        out = set()
        for s in data:
            cid = s.get("challenge_id") or (s.get("challenge") or {}).get("id")
            if cid is not None:
                out.add(int(cid))
        return out

    def submit(self, cid: int, flag: str) -> tuple[str, str]:
        """Submit a flag. Returns (status, message): status in
        {correct, incorrect, already_solved, ratelimited, ...}."""
        data = self._post(
            "/api/v1/challenges/attempt", {"challenge_id": cid, "submission": flag}
        ).get("data", {})
        return data.get("status", "?"), data.get("message", "")

    def me(self) -> dict:
        """Relevant account: {name, score, place, team}. In team mode, returns the TEAM
        (team name, score and rank) so the header, the stats and the scoreboard highlight
        match the real ranking. Empty if unavailable."""
        base = self._account()
        try:
            d = self._get(base).get("data", {}) or {}
        except CTFdError:
            return {}
        return {"name": d.get("name"), "score": d.get("score"),
                "place": d.get("place"), "team": base.startswith("/api/v1/teams")}

    def me_user(self) -> dict:
        """INDIVIDUAL profile (always /users/me): {id, name, score, place}. Useful in team
        mode to show your personal stats alongside the team's. Empty if unavailable."""
        try:
            d = self._get("/api/v1/users/me").get("data", {}) or {}
        except CTFdError:
            return {}
        return {"id": d.get("id"), "name": d.get("name"),
                "score": d.get("score"), "place": d.get("place")}

    def team_member_stats(self) -> list[dict]:
        """Team mode: per-member contribution, from the team's solves.

        Each CTFd solve carries the member who solved it (`user: {id, name}`), so a single call
        is enough. Returns [{user_id, name, count, solved_ids}] (members with at least 1 solve).
        """
        if not self.is_team_mode():
            return []
        try:
            data = self._get("/api/v1/teams/me/solves").get("data", []) or []
        except CTFdError:
            return []
        agg: dict[int, dict] = {}
        for s in data:
            u = s.get("user") or {}
            uid = u.get("id")
            if uid is None:
                continue
            m = agg.setdefault(int(uid), {"user_id": int(uid),
                                          "name": u.get("name", f"#{uid}"),
                                          "count": 0, "solved_ids": []})
            cid = s.get("challenge_id") or (s.get("challenge") or {}).get("id")
            m["count"] += 1
            if cid is not None:
                m["solved_ids"].append(int(cid))
        return list(agg.values())

    def first_blood(self, cid: int) -> str | None:
        """Name of the first solver of a challenge (first blood), if available."""
        try:
            d = self._get(f"/api/v1/challenges/{cid}/solves").get("data", []) or []
        except CTFdError:
            return None
        return d[0].get("name") if d else None

    def challenge_solvers(self, cid: int) -> list[dict]:
        """Everyone who solved a challenge, earliest first (team name in team mode, player name
        in solo). Returns [] once the CTF has ended: CTFd locks this endpoint to during-event
        only."""
        try:
            d = self._get(f"/api/v1/challenges/{cid}/solves").get("data", []) or []
        except CTFdError:
            return []
        return [{"name": s.get("name", "?"), "date": s.get("date")} for s in d]

    def scoreboard(self, top: int = 50) -> list[dict]:
        """Ranking: list of {pos, name, score} (truncated to `top`)."""
        try:
            data = self._get("/api/v1/scoreboard").get("data", []) or []
        except CTFdError:
            return []
        out = []
        for i, row in enumerate(data[:top], 1):
            out.append({
                "pos": row.get("pos", i),
                "name": row.get("name", "?"),
                "score": row.get("score", 0),
            })
        return out

    def unlock_hint(self, hint_id: int) -> str:
        """Unlock a hint (⚠️ costs points). Returns its content."""
        self._post("/api/v1/unlocks", {"target": hint_id, "type": "hints"})
        # the content is more reliable via the challenge detail; the direct endpoint is also tried
        try:
            data = self._get(f"/api/v1/hints/{hint_id}").get("data", {}) or {}
            return data.get("content", "") or ""
        except CTFdError:
            return ""

    def download(self, file_path: str, dest, max_bytes: int = 2 * 1024**3) -> tuple[str, str]:
        """Download a file hosted by the platform (authenticated).

        Returns (status, detail): "ok" | "manual" (too large) | "error".
        """
        u = file_path if file_path.startswith("http") else self.url + file_path
        try:
            r = self._session.get(u, timeout=self.timeout * 4, stream=True)
            r.raise_for_status()
        except requests.RequestException as e:
            return "error", str(e)
        size = int(r.headers.get("Content-Length") or 0)
        if size and size > max_bytes:
            r.close()
            return "manual", f"{size/1024**3:.1f} GB > 2 GB"
        return _stream_to(r, dest, max_bytes)

    def file_url(self, file_path: str) -> str:
        """Full URL (with file token) as provided by the API."""
        return file_path if file_path.startswith("http") else self.url + file_path


def _stream_to(r: "requests.Response", dest, max_bytes: int) -> tuple[str, str]:
    """Write the stream to dest while honouring a max size (2 GB safeguard)."""
    written = 0
    try:
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    try:
                        import os
                        os.remove(dest)
                    except OSError:
                        pass
                    return "manual", "> 2 GB (aborted)"
                f.write(chunk)
    except (OSError, requests.RequestException) as e:
        # remove the partial file so a later retry can download it again
        try:
            import os
            os.remove(dest)
        except OSError:
            pass
        return "error", str(e)
    return "ok", f"{written} B"
