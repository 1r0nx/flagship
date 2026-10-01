"""Client minimal de l'API CTFd (lecture + soumission).

Ne journalise jamais le token. Toutes les méthodes lèvent CTFdError en cas
de problème réseau/API, avec un message exploitable par la TUI.
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

    # -- helpers ---------------------------------------------------------
    def _get(self, path: str) -> dict:
        try:
            r = self._session.get(self.url + path, timeout=self.timeout)
        except requests.RequestException as e:
            raise CTFdError(f"réseau: {e}") from e
        return self._json(r)

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = self._session.post(self.url + path, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise CTFdError(f"réseau: {e}") from e
        return self._json(r)

    @staticmethod
    def _json(r: requests.Response) -> dict:
        # messages clairs selon le code HTTP
        if r.status_code in (401, 403):
            raise CTFdError("accès refusé — token invalide/expiré ou challenge verrouillé (HTTP %d)" % r.status_code)
        if r.status_code == 429:
            raise CTFdError("trop de requêtes (429) — réessaie dans un instant (rate-limit CTFd)")
        if r.status_code == 404:
            raise CTFdError("introuvable (404) — mauvais URL/endpoint ou ressource absente")
        if r.status_code >= 500:
            raise CTFdError(f"erreur serveur CTFd (HTTP {r.status_code})")
        try:
            data = r.json()
        except ValueError:
            raise CTFdError(f"réponse non-JSON (HTTP {r.status_code}) — l'URL pointe-t-elle bien vers un CTFd ?")
        if isinstance(data, dict) and data.get("success") is False:
            raise CTFdError(str(data.get("message") or data.get("errors") or "échec API"))
        # certains messages (CTF terminé/pas commencé) arrivent sans "success"
        if isinstance(data, dict) and "message" in data and "data" not in data and "success" not in data:
            raise CTFdError(str(data["message"]))
        return data

    # -- endpoints -------------------------------------------------------
    def challenges(self) -> list[dict]:
        """Liste des challenges visibles (id, name, category, value, solves...)."""
        return self._get("/api/v1/challenges").get("data", []) or []

    def challenge(self, cid: int) -> dict:
        """Détail d'un challenge (description, files, hints, connection_info...)."""
        return self._get(f"/api/v1/challenges/{cid}").get("data", {}) or {}

    def solved_ids(self) -> set[int]:
        """Ensemble des ids résolus par l'utilisateur courant."""
        try:
            data = self._get("/api/v1/users/me/solves").get("data", []) or []
        except CTFdError:
            return set()
        out = set()
        for s in data:
            cid = s.get("challenge_id") or (s.get("challenge") or {}).get("id")
            if cid is not None:
                out.add(int(cid))
        return out

    def submit(self, cid: int, flag: str) -> tuple[str, str]:
        """Soumet un flag. Retourne (status, message) : status in
        {correct, incorrect, already_solved, ratelimited, ...}."""
        data = self._post(
            "/api/v1/challenges/attempt", {"challenge_id": cid, "submission": flag}
        ).get("data", {})
        return data.get("status", "?"), data.get("message", "")

    def me(self) -> dict:
        """Profil courant : {name, score, place}. Vide si indisponible."""
        try:
            d = self._get("/api/v1/users/me").get("data", {}) or {}
        except CTFdError:
            return {}
        return {"name": d.get("name"), "score": d.get("score"), "place": d.get("place")}

    def first_blood(self, cid: int) -> str | None:
        """Nom du premier solveur d'un challenge (first blood), si dispo."""
        try:
            d = self._get(f"/api/v1/challenges/{cid}/solves").get("data", []) or []
        except CTFdError:
            return None
        return d[0].get("name") if d else None

    def scoreboard(self, top: int = 50) -> list[dict]:
        """Classement : liste de {pos, name, score} (tronquée à `top`)."""
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
        """Débloque un indice (⚠️ coûte des points). Retourne son contenu."""
        self._post("/api/v1/unlocks", {"target": hint_id, "type": "hints"})
        # le contenu est plus fiable via le détail du challenge ; on tente aussi l'endpoint direct
        try:
            data = self._get(f"/api/v1/hints/{hint_id}").get("data", {}) or {}
            return data.get("content", "") or ""
        except CTFdError:
            return ""

    def download(self, file_path: str, dest, max_bytes: int = 2 * 1024**3) -> tuple[str, str]:
        """Télécharge un fichier hébergé par la plateforme (authentifié).

        Retourne (statut, détail) : "ok" | "manual" (trop volumineux) | "error".
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
            return "manual", f"{size/1024**3:.1f} Go > 2 Go"
        return _stream_to(r, dest, max_bytes)

    def file_url(self, file_path: str) -> str:
        """URL complète (avec token de fichier) telle que fournie par l'API."""
        return file_path if file_path.startswith("http") else self.url + file_path


def _stream_to(r: "requests.Response", dest, max_bytes: int) -> tuple[str, str]:
    """Écrit le flux dans dest en respectant une taille maxi (garde-fou 2 Go)."""
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
                    return "manual", "> 2 Go (interrompu)"
                f.write(chunk)
    except (OSError, requests.RequestException) as e:
        # supprimer le fichier partiel pour qu'un futur retry puisse le re-télécharger
        try:
            import os
            os.remove(dest)
        except OSError:
            pass
        return "error", str(e)
    return "ok", f"{written} o"
