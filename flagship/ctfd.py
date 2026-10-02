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
        self._account_base: str | None = None  # '/api/v1/teams/me' (équipe) ou '/api/v1/users/me' (solo)

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
            raise CTFdError("accès refusé : token invalide/expiré ou challenge verrouillé (HTTP %d)" % r.status_code)
        if r.status_code == 429:
            raise CTFdError("trop de requêtes (429) : réessayer dans un instant (rate-limit CTFd)")
        if r.status_code == 404:
            raise CTFdError("introuvable (404) : mauvais URL/endpoint ou ressource absente")
        if r.status_code >= 500:
            raise CTFdError(f"erreur serveur CTFd (HTTP {r.status_code})")
        try:
            data = r.json()
        except ValueError:
            raise CTFdError(f"réponse non-JSON (HTTP {r.status_code}) : l'URL pointe-t-elle bien vers un CTFd ?")
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

    def auth_ok(self) -> bool:
        """True si le token est accepté par l'API (GET /users/me réussit). Sert à distinguer
        un token invalide d'un simple refus d'accès aux challenges (CTF terminé/masqués)."""
        try:
            self._get("/api/v1/users/me")
            return True
        except CTFdError:
            return False

    def challenge(self, cid: int) -> dict:
        """Détail d'un challenge (description, files, hints, connection_info...)."""
        return self._get(f"/api/v1/challenges/{cid}").get("data", {}) or {}

    def _account(self) -> str:
        """Endpoint du « compte » pertinent pour la compétition : l'ÉQUIPE en mode équipe,
        sinon l'utilisateur. Détecté une seule fois puis mémorisé.

        En mode équipe, le score, le rang et surtout les RÉSOLUS qui comptent sont au niveau de
        l'équipe (un flag posé par un coéquipier doit apparaître résolu). `/api/v1/teams/me`
        échoue en mode solo (teams désactivées) : on retombe alors sur l'utilisateur.
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
        """True si le CTF est en mode équipe (le compte pertinent est une équipe)."""
        return self._account().startswith("/api/v1/teams")

    def solved_ids(self) -> set[int]:
        """Ensemble des ids résolus par le compte pertinent (ÉQUIPE en mode équipe, sinon soi)."""
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
        """Soumet un flag. Retourne (status, message) : status in
        {correct, incorrect, already_solved, ratelimited, ...}."""
        data = self._post(
            "/api/v1/challenges/attempt", {"challenge_id": cid, "submission": flag}
        ).get("data", {})
        return data.get("status", "?"), data.get("message", "")

    def me(self) -> dict:
        """Compte pertinent : {name, score, place, team}. En mode équipe, renvoie l'ÉQUIPE
        (nom, score et rang de l'équipe) pour que l'en-tête, les stats et le surlignage du
        scoreboard correspondent au classement réel. Vide si indisponible."""
        base = self._account()
        try:
            d = self._get(base).get("data", {}) or {}
        except CTFdError:
            return {}
        return {"name": d.get("name"), "score": d.get("score"),
                "place": d.get("place"), "team": base.startswith("/api/v1/teams")}

    def me_user(self) -> dict:
        """Profil INDIVIDUEL (toujours /users/me) : {id, name, score, place}. Utile en mode
        équipe pour afficher tes stats perso en plus de celles de l'équipe. Vide si indisponible."""
        try:
            d = self._get("/api/v1/users/me").get("data", {}) or {}
        except CTFdError:
            return {}
        return {"id": d.get("id"), "name": d.get("name"),
                "score": d.get("score"), "place": d.get("place")}

    def team_member_stats(self) -> list[dict]:
        """Mode équipe : contribution par membre, d'après les solves de l'équipe.

        Chaque solve CTFd porte le membre qui l'a résolu (`user: {id, name}`), donc un seul appel
        suffit. Retourne [{user_id, name, count, solved_ids}] (membres ayant au moins 1 solve).
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

    def ctf_end(self) -> float | None:
        """Timestamp (epoch, secondes) de fin du CTF si l'API l'expose, sinon None.

        L'endpoint `/api/v1/configs` est souvent réservé aux admins : en cas de refus
        (401/403) ou d'absence de la clé, on retourne None silencieusement (la fin peut
        alors être fournie manuellement via CTF_END dans config.sh).
        """
        try:
            data = self._get("/api/v1/configs").get("data", [])
        except CTFdError:
            return None
        if isinstance(data, dict):
            data = [{"key": k, "value": v} for k, v in data.items()]
        for row in data or []:
            if isinstance(row, dict) and row.get("key") == "end" and row.get("value"):
                try:
                    return float(row["value"])
                except (TypeError, ValueError):
                    return None
        return None


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
