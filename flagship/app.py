"""Flagship : TUI Textual pour un CTFd.

Onglets Challenges / Scoreboard / Stats ; listing léger par défaut, téléchargement à la demande
(`d`), par catégorie (`C`) ou complet (`D`, parallèle + barre de progression) ; recherche, tri, filtres ;
soumission, déblocage d'indice, copier la connexion, notes externes, export PROGRESS_flagship.md ;
notifications (toasts + journal + historique). Le token n'est jamais affiché.

Lancement : python -m flagship [chemin/config.sh]
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Header, Footer, Tree, Markdown, Input, Static, DataTable,
    TabbedContent, TabPane, Button, ProgressBar,
)
from textual import work
from textual.binding import Binding
from textual.strip import Strip
from rich.text import Text
from rich.segment import Segment
from rich.style import Style
from rich.cells import cell_len

from .config import Config
from .ctfd import CTFd, CTFdError
from . import store

BEAM_CHAR = "▏"  # barre verticale fine (U+258F) pour simuler un curseur I-beam


class BeamInput(Input):
    """Champ de saisie dont le curseur est une barre verticale (« I-beam ») au lieu du
    bloc inversé par défaut.

    Le bloc natif de Textual est neutralisé (son style est rendu vide le temps du rendu),
    puis une unique barre est dessinée à la position du curseur. On évite ainsi tout
    « double curseur » (barre + reste de bloc) sur le premier caractère d'un placeholder
    large (emoji). En cas d'incompatibilité, repli silencieux sur le curseur standard."""

    _suppress_native_cursor = False

    def get_component_rich_style(self, *names, **kwargs):
        # neutralise seulement le style du curseur natif pendant notre propre rendu
        if self._suppress_native_cursor and names == ("input--cursor",):
            return Style()
        return super().get_component_rich_style(*names, **kwargs)

    def render_line(self, y: int) -> Strip:
        # 1re ligne, champ focus, curseur visible (respecte le clignotement)
        if y != 0 or not self.has_focus or not self._cursor_visible:
            return super().render_line(y)
        try:
            # 1) rendu normal mais SANS le bloc du curseur natif
            self._suppress_native_cursor = True
            strip = super().render_line(y)
            self._suppress_native_cursor = False

            # couleur de la barre = couleur de remplissage du bloc natif (suit le thème)
            cur = super().get_component_rich_style("input--cursor")
            bar_style = self.rich_style + Style(color=cur.bgcolor, bold=True)
            bar = Strip([Segment(BEAM_CHAR, bar_style)])
            width = strip.cell_length

            # 2) colonne visuelle du curseur (gère les caractères larges)
            col = cell_len(self.value[: self.cursor_position]) - self.scroll_offset.x
            if col < 0 or col > width:
                return super().render_line(y)

            # 3) remplace l'unique cellule du curseur par la barre
            left = strip.crop(0, col)
            right = strip.crop(col + 1, width)
            return Strip.join([left, bar, right])
        except Exception:
            self._suppress_native_cursor = False
            return super().render_line(y)  # repli : curseur par défaut

FILTERS = ("all", "unsolved", "solved")
FILTER_LABEL = {"all": "tous", "unsolved": "non résolus", "solved": "résolus"}
SORTS = ("category", "points", "solves")
SORT_LABEL = {"category": "catégorie", "points": "points", "solves": "solves"}


class ConfirmScreen(ModalScreen[bool]):
    CSS = """
    ConfirmScreen { align: center middle; }
    #box { width: 64; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    #row { height: auto; align-horizontal: center; padding-top: 1; }
    Button { margin: 0 1; }
    """

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self.question)
            with Horizontal(id="row"):
                yield Button("Oui", variant="warning", id="yes")
                yield Button("Non", variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


def build_member_md(name: str, challenges: list[dict], solved_ids: set[int]) -> str:
    """Markdown du détail d'un membre : « Par catégorie » + « Progression par catégorie »,
    calculés à partir des challenges qu'il a résolus (classé par points décroissants)."""
    cats: dict[str, dict] = {}
    total_s = total_p = 0
    for c in challenges:
        cid = int(c.get("id", -1))
        d = cats.setdefault(c.get("category", "?"), {"n": 0, "s": 0, "pw": 0, "pt": 0})
        v = int(c.get("value") or 0)
        d["n"] += 1
        d["pt"] += v
        if cid in solved_ids:
            d["s"] += 1
            d["pw"] += v
            total_s += 1
            total_p += v
    md = [f"# {name}", "", f"**Résolus** : {total_s}  ·  **Points** : {total_p}"]
    done = {k: v for k, v in cats.items() if v["s"] > 0}
    if not done:
        md += ["", "*Aucun challenge résolu pour l'instant.*"]
        return "\n".join(md)
    order = sorted(done, key=lambda k: (-done[k]["pw"], -done[k]["s"], k.lower()))
    md += ["", "## Par catégorie (classé par points)", "",
           "| Catégorie | Résolus | Points |", "|-----------|---------|--------|"]
    for cat in order:
        d = done[cat]
        md.append(f"| {cat} | {d['s']}/{d['n']} | {d['pw']}/{d['pt']} |")
    md += ["", "## Progression par catégorie", "", "```"]
    wname = max(len(c) for c in order)
    for cat in order:
        d = done[cat]
        filled = round((d["s"] / d["n"]) * 12) if d["n"] else 0
        md.append(f"{cat.ljust(wname)}  {'█' * filled}{'░' * (12 - filled)}  {d['s']}/{d['n']}")
    md.append("```")
    return "\n".join(md)


class MemberStatsScreen(ModalScreen[None]):
    """Fenêtre du détail d'un membre (ouverte en cliquant sur son pseudo dans l'onglet Stats)."""
    BINDINGS = [("escape", "dismiss", "Fermer")]
    CSS = """
    MemberStatsScreen { align: center middle; }
    #mbox { width: 80%; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #mhead { color: $text-muted; }
    """

    def __init__(self, name: str, challenges: list[dict], solved_ids: set[int]):
        super().__init__()
        self._name = name
        self._challenges = challenges
        self._solved = solved_ids

    def compose(self) -> ComposeResult:
        with Vertical(id="mbox"):
            yield Static("Échap pour fermer", id="mhead")
            with VerticalScroll():
                yield Markdown(build_member_md(self._name, self._challenges, self._solved),
                               open_links=False)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class Flagship(App):
    CSS = """
    #search { dock: top; }
    #treecol { width: 42%; border-right: solid $accent; }
    #legend { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #tree { height: 1fr; }
    #rightcol { width: 1fr; }
    #detailwrap { height: 1fr; }
    #detail { padding: 0 1; }
    #flag { height: 3; border: solid $accent; padding: 0 1; }
    #progress { dock: bottom; height: 1; display: none; }
    #scoreboard { height: 1fr; }
    #stats { padding: 0 1; }
    #notifs { padding: 0 1; }
    """

    BINDINGS = [
        ("r", "refresh", "Rafraîchir"),
        ("d", "download", "Télécharger"),
        ("D", "sync_all", "Tout sync"),
        ("C", "download_category", "Cat. dl"),
        ("f", "cycle_filter", "Filtre"),
        ("o", "cycle_sort", "Tri"),
        ("t", "cycle_theme", "Thème"),
        ("slash", "focus_search", "Rechercher"),
        ("s", "focus_flag", "Soumettre"),
        ("u", "unlock_hint", "Indice"),
        ("c", "copy_conn", "Copier"),
        ("w", "open_folder", "Dossier"),
        ("e", "edit_notes", "Notes"),
        ("p", "export_progress", "Progress"),
        ("q", "quit", "Quitter"),
        Binding("escape", "unfocus", "Quitter le champ", show=False),
    ]

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.client = CTFd(cfg.url, cfg.token)
        self.challenges: list[dict] = []
        self.selected: dict | None = None
        self.filter_mode = "all"
        self.sort_mode = "category"
        self.search = ""
        self.collapsed_cats: set[str] = set()  # catégories repliées (défaut = dépliées)
        self._building = False                  # garde anti-boucle pendant la reconstruction de l'arbre
        self.me: dict = {}
        self._personal: dict = {}             # stats individuelles (mode équipe uniquement)
        self._members: list[dict] = []        # contribution par membre de l'équipe (mode équipe)
        self._last_scoreboard: list[dict] = []
        self._detail_cache: dict[int, dict] = {}
        self._fb_cache: dict[int, str | None] = {}
        self.notifications: list[str] = []
        self._first_sync = True
        self._syncing = False               # True pendant « Tout synchroniser » (évite l'annulation par le poll)
        self._tree_sig = None               # signature des données affichées (évite les rebuilds inutiles)
        self._ctf_end = self._parse_end(cfg.ctf_end)  # epoch de fin (compte à rebours) ou None
        self._log_path = cfg.base_dir / ".flagship" / "notifications.log"
        self._state_path = cfg.base_dir / ".flagship" / "state.json"

    @staticmethod
    def _parse_end(raw: str | None) -> float | None:
        """Interprète CTF_END : epoch (nombre) ou date ISO (ex. 2026-10-05T18:00)."""
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "")).timestamp()
        except ValueError:
            return None

    # -- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        # espace en tête : le curseur I-beam clignote dessus (col 0) sans masquer l'emoji
        yield BeamInput(placeholder=" 🔎 Rechercher…  ( / )", id="search")
        with TabbedContent(initial="tab-chal"):
            with TabPane("Challenges", id="tab-chal"):
                with Horizontal():
                    with Vertical(id="treecol"):
                        yield Static(
                            "[cyan]▣[/cyan] [grey42]▢[/grey42] fichiers    "
                            "[green]●[/green] [grey42]○[/grey42] résolu",
                            id="legend")
                        yield Tree("Challenges", id="tree")
                    with Vertical(id="rightcol"):
                        with VerticalScroll(id="detailwrap"):
                            yield Markdown("*Sélectionne un challenge à gauche.*", id="detail")
                        # espace en tête : le curseur I-beam clignote dessus sans masquer l'emoji
                        yield BeamInput(placeholder=" 🚩", id="flag")
            with TabPane("Scoreboard", id="tab-score"):
                yield DataTable(id="scoreboard")
            with TabPane("Stats", id="tab-stats"):
                with VerticalScroll():
                    yield Markdown("*Statistiques…*", id="stats", open_links=False)
            with TabPane("Notifications", id="tab-notifs"):
                with VerticalScroll():
                    yield Static("Aucune notification.", id="notifs")
        yield ProgressBar(id="progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tree", Tree).show_root = False
        dt = self.query_one("#scoreboard", DataTable)
        dt.add_columns("#", "Équipe / Joueur", "Score")
        dt.cursor_type = "row"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._restore_ui_state()
        th = getattr(self, "_pref_theme", None) or self.cfg.theme
        if th in self.available_themes:
            self.theme = th
        self.list_worker()
        self.scoreboard_worker()
        self.me_worker()
        if self._ctf_end is None:        # fin non fournie par config.sh : tenter l'API
            self.ctf_meta_worker()
        self._update_title()
        self.set_interval(30, self._update_title)  # rafraîchit le compte à rebours
        if self.cfg.poll_interval and self.cfg.poll_interval > 0:
            self.set_interval(self.cfg.poll_interval, self.list_worker)
            self.set_interval(self.cfg.poll_interval, self.scoreboard_worker)
            self.set_interval(self.cfg.poll_interval, self.me_worker)

    def on_unmount(self) -> None:
        self._save_ui_state()

    # -- état d'interface persistant ------------------------------------
    def _restore_ui_state(self) -> None:
        try:
            s = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.filter_mode = s.get("filter", self.filter_mode)
            self.sort_mode = s.get("sort", self.sort_mode)
            self.collapsed_cats = set(s.get("collapsed", []))
            self._last_selected_id = s.get("selected")
            self._pref_theme = s.get("theme")
        except (OSError, ValueError):
            self._last_selected_id = None
            self._pref_theme = None

    def _save_ui_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "filter": self.filter_mode, "sort": self.sort_mode,
                "selected": (self.selected or {}).get("id"),
                "collapsed": sorted(self.collapsed_cats),
                "theme": self.theme,
            }), encoding="utf-8")
        except OSError:
            pass

    # -- notifications ---------------------------------------------------
    def _emit(self, msg: str, severity: str = "information", timeout: float = 5) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.notifications.append(line)
        del self.notifications[:-500]
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        self._render_notifs()
        self.notify(msg, severity=severity, timeout=timeout)

    def _render_notifs(self) -> None:
        """Met à jour l'onglet Notifications (plus récentes en haut)."""
        try:
            w = self.query_one("#notifs", Static)
        except Exception:  # noqa: BLE001  (widget pas encore monté)
            return
        # Text() => pas d'interprétation du balisage (les horodatages [HH:MM:SS] restent littéraux)
        w.update(Text("\n".join(reversed(self.notifications)) or "Aucune notification."))

    # -- workers réseau --------------------------------------------------
    @work(thread=True, exclusive=True, group="sync")
    def list_worker(self) -> None:
        if self._syncing:  # une synchro complète est en cours : ne pas interférer
            return
        try:
            challenges, events = store.list_state(
                self.client, self.cfg.base_dir, self.cfg.watch_changes, self.cfg.auto_unlock_free_hints)
        except CTFdError as e:
            # diagnostic : token valide mais challenges inaccessibles (CTF terminé/masqués) ?
            hint = ""
            if "403" in str(e) or "accès refusé" in str(e):
                if self.client.auth_ok():
                    hint = " (token OK : challenges masqués — CTF terminé ou pas encore commencé)"
                else:
                    hint = " (token refusé : régénère-le dans Settings > Access Tokens)"
            cached = store.load_cache(self.cfg.base_dir)  # mode hors-ligne
            if cached:
                self.call_from_thread(self._emit, f"📴 Hors-ligne : liste en cache{hint}", "warning", 7)
                self.call_from_thread(self._apply_challenges, cached, [])
            else:
                self.call_from_thread(self._emit, f"Liste impossible : {e}{hint}", "error", 8)
            return
        self.call_from_thread(self._apply_challenges, challenges, events)

    @work(thread=True, exclusive=True, group="me")
    def me_worker(self) -> None:
        me = self.client.me()
        personal, members = None, None
        if me and self.client.is_team_mode():  # en équipe : stats perso + contribution des membres
            personal = self.client.me_user()
            members = self.client.team_member_stats()
        if me:
            # mémorise le profil (score/rang/équipe) pour le revoir hors-ligne / après le CTF
            store.save_json(self.cfg.base_dir, "me_cache.json",
                            {"me": me, "personal": personal, "members": members})
            self.call_from_thread(self._apply_me, me, personal, members)
        else:  # API indisponible (hors-ligne ou CTF terminé) : réafficher le dernier profil connu
            cached = store.load_json(self.cfg.base_dir, "me_cache.json")
            if cached and cached.get("me"):
                self.call_from_thread(self._apply_me, cached["me"],
                                      cached.get("personal"), cached.get("members"))

    @work(thread=True, exclusive=True, group="ctfmeta")
    def ctf_meta_worker(self) -> None:
        end = self.client.ctf_end()
        if end:
            self.call_from_thread(self._set_ctf_end, end)

    def _set_ctf_end(self, end: float) -> None:
        self._ctf_end = end
        self._update_title()

    def _countdown_str(self) -> str:
        """Texte du compte à rebours (ou '' si pas de fin connue)."""
        if not self._ctf_end:
            return ""
        rem = int(self._ctf_end - datetime.now().timestamp())
        if rem <= 0:
            return "⏳ terminé"
        mins, _ = divmod(rem, 60)
        hours, mins = divmod(mins, 60)
        days, hours = divmod(hours, 24)
        if days:
            return f"⏳ fin dans {days}j{hours:02d}h"
        if hours:
            return f"⏳ fin dans {hours}h{mins:02d}"
        return f"⏳ fin dans {mins}min"

    def _update_title(self) -> None:
        parts = [f"Flagship · {self.cfg.ctf_name}"]
        s, p = self.me.get("score"), self.me.get("place")
        if s is not None:
            parts.append(f"score {s}" + (f" (#{p})" if p else ""))
        cd = self._countdown_str()
        if cd:
            parts.append(cd)
        self.title = " · ".join(parts)

    def _render_stats(self) -> None:
        try:
            w = self.query_one("#stats", Markdown)
        except Exception:  # noqa: BLE001
            return
        chs = self.challenges
        if not chs:
            w.update("*Aucune donnée pour le moment. Lance une synchro (`r`).*")
            return
        total = len(chs)
        solved = [c for c in chs if c.get("solved")]
        dled = [c for c in chs if c.get("downloaded")]
        pts_won = sum(int(c.get("value") or 0) for c in solved)
        pts_all = sum(int(c.get("value") or 0) for c in chs)
        s, p = self.me.get("score"), self.me.get("place")
        team = self.me.get("team")
        md = [f"# Statistiques · {self.cfg.ctf_name}", ""]
        if self.me.get("name"):
            who = "Équipe" if team else "Joueur"
            md.append(f"**{who}** : {self.me['name']}")
        if s is not None:
            label = "Score (équipe)" if team else "Score"
            md.append(f"**{label}** : {s}" + (f"  ·  **Rang** : #{p}" if p else ""))
        md.append(f"**Résolus** : {len(solved)} / {total}  ·  "
                  f"**Points gagnés** : {pts_won} / {pts_all}")
        md.append(f"**Téléchargés** : {len(dled)} / {total}")
        if self._personal:  # mode équipe : contribution de chaque membre
            val = {int(c["id"]): int(c.get("value") or 0) for c in chs if c.get("id") is not None}
            my_id = self._personal.get("id")
            ps, pp = self._personal.get("score"), self._personal.get("place")
            md += ["", "## Membres de l'équipe"]
            if ps is not None:
                rank = f"#{pp}" if pp else "—"
                md.append(f"*Ton rang individuel : {rank} · ton score : {ps}*")
            rows = [(m.get("name", "?"), m.get("count", 0),
                     sum(val.get(cid, 0) for cid in m.get("solved_ids", [])), m.get("user_id"))
                    for m in self._members]
            # garantit ta propre ligne même si tu n'as encore rien résolu
            if my_id is not None and my_id not in {r[3] for r in rows}:
                rows.append((self._personal.get("name", "toi"), 0, 0, my_id))
            rows.sort(key=lambda r: (-r[2], -r[1], r[0].lower()))
            md += ["*Clique sur un pseudo pour voir son détail par catégorie.*", "",
                   "| Membre | Résolus | Points |", "|--------|---------|--------|"]
            for name, cnt, pts, uid in rows:
                me_row = my_id is not None and uid == my_id
                label = f"{name} (toi)" if me_row else name
                # pseudo cliquable (href 'member:<id>') intercepté par on_markdown_link_clicked
                link = f"[{label}](member:{uid})" if uid is not None else label
                nm = f"**{link}**" if me_row else link
                c2 = f"**{cnt}**" if me_row else str(cnt)
                c3 = f"**{pts}**" if me_row else str(pts)
                md.append(f"| {nm} | {c2} | {c3} |")
            if not rows:
                md.append("| *(aucun solve pour le moment)* |  |  |")
        cats: dict[str, dict] = {}
        for c in chs:
            d = cats.setdefault(c.get("category", "?"), {"n": 0, "s": 0, "dl": 0, "pw": 0, "pt": 0})
            v = int(c.get("value") or 0)
            d["n"] += 1
            d["pt"] += v
            if c.get("solved"):
                d["s"] += 1
                d["pw"] += v
            if c.get("downloaded"):
                d["dl"] += 1
        md += ["", "## Par catégorie", "",
               "| Catégorie | Résolus | Points | Téléchargés |",
               "|-----------|---------|--------|-------------|"]
        for cat in sorted(cats):
            d = cats[cat]
            md.append(f"| {cat} | {d['s']}/{d['n']} | {d['pw']}/{d['pt']} | {d['dl']}/{d['n']} |")
        md += ["", "## Progression par catégorie", "", "```"]
        wname = max((len(cat) for cat in cats), default=0)
        for cat in sorted(cats):
            d = cats[cat]
            filled = round((d["s"] / d["n"]) * 12) if d["n"] else 0
            bar = "█" * filled + "░" * (12 - filled)
            md.append(f"{cat.ljust(wname)}  {bar}  {d['s']}/{d['n']}")
        md.append("```")
        w.update("\n".join(md))

    def on_markdown_link_clicked(self, event) -> None:
        """Clic sur un pseudo (href 'member:<id>') dans l'onglet Stats → ouvre sa box de détail.
        Les autres liens (liens externes du détail, http) sont ignorés ici."""
        href = getattr(event, "href", "") or ""
        if not href.startswith("member:"):
            return
        try:
            uid = int(href.split(":", 1)[1])
        except ValueError:
            return
        m = next((x for x in self._members if x.get("user_id") == uid), None)
        if not m:
            return
        self.push_screen(MemberStatsScreen(
            m.get("name", "?"), self.challenges, set(m.get("solved_ids", []))))

    def _apply_me(self, me: dict, personal: dict | None = None,
                  members: list | None = None) -> None:
        self.me = me or self.me
        if personal is not None:
            self._personal = personal
        if members is not None:
            self._members = members
        self._update_title()
        self._render_stats()
        if self._last_scoreboard:  # re-surligner ta ligne sans refetch
            self._fill_scoreboard(self._last_scoreboard)

    @work(thread=True, exclusive=True, group="syncall")  # groupe distinct : non annulé par le poll/list
    def sync_all_worker(self) -> None:
        self._syncing = True
        self.call_from_thread(self._show_progress, True)

        def progress(done, total):
            self.call_from_thread(self._set_progress, done, total)

        self.call_from_thread(self._emit, "⏳ Synchronisation complète…", "information", 3)
        try:
            challenges, events = store.sync(
                self.client, self.cfg.base_dir, self.cfg.watch_changes,
                self.cfg.auto_unlock_free_hints, self.cfg.download_workers, progress)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Sync complète impossible : {e}", "error", 6)
            return
        finally:
            self._syncing = False
            self.call_from_thread(self._show_progress, False)
        n = sum(1 for c in challenges if c.get("downloaded"))
        self.call_from_thread(self._apply_challenges, challenges, events)
        self.call_from_thread(self._emit, f"✅ Sync complète : {n} challenges téléchargés.", "information", 6)

    def _show_progress(self, on: bool) -> None:
        pb = self.query_one("#progress", ProgressBar)
        pb.display = on
        if on:
            pb.update(total=100, progress=0)

    def _set_progress(self, done: int, total: int) -> None:
        self.query_one("#progress", ProgressBar).update(total=total, progress=done)

    @work(thread=True, exclusive=True, group="download")
    def download_worker(self, summary: dict) -> None:
        try:
            path, events = store.download_one(
                self.client, self.cfg.base_dir, summary, self.cfg.watch_changes, self.cfg.auto_unlock_free_hints)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Téléchargement KO : {e}", "error")
            return
        downloaded = (Path(path) / "desc.txt").exists()  # état réel sur disque (auto-réparé)
        self.call_from_thread(self._after_download, int(summary["id"]), path, downloaded,
                              summary.get("name", "?"), events)

    def _after_download(self, cid: int, path: str, downloaded: bool, name: str, events: list) -> None:
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                c["downloaded"] = downloaded
                c["path"] = path
        self._emit(f"⬇ {name} : à jour", "information", 5)
        self._apply_challenges(self.challenges, events)

    @work(thread=True, exclusive=True, group="score")
    def scoreboard_worker(self) -> None:
        rows = self.client.scoreboard()
        if rows:
            store.save_json(self.cfg.base_dir, "scoreboard_cache.json", rows)
            self.call_from_thread(self._fill_scoreboard, rows)
        else:  # API indisponible : réafficher le dernier scoreboard connu
            cached = store.load_json(self.cfg.base_dir, "scoreboard_cache.json")
            if cached:
                self.call_from_thread(self._fill_scoreboard, cached)

    def _fill_scoreboard(self, rows: list[dict]) -> None:
        self._last_scoreboard = rows
        dt = self.query_one("#scoreboard", DataTable)
        dt.clear()
        me_name = (self.me or {}).get("name")
        my_row = None
        for i, r in enumerate(rows):
            is_me = bool(me_name) and r["name"] == me_name
            st = "bold $warning" if is_me else ""
            dt.add_row(
                Text(("➤ " if is_me else "") + str(r["pos"]), style=st),
                Text(str(r["name"]), style=st),
                Text(str(r["score"]), style=st),
            )
            if is_me:
                my_row = i
        if my_row is not None:
            try:
                dt.move_cursor(row=my_row)
            except Exception:  # noqa: BLE001
                pass

    # -- application des données ----------------------------------------
    def _apply_challenges(self, challenges: list[dict], events: list[dict] | None = None) -> None:
        prev_ids = {int(c["id"]) for c in self.challenges}
        prev_solved = {int(c["id"]) for c in self.challenges if c.get("solved")}
        for c in challenges:
            if c.get("_detail"):
                self._detail_cache[int(c["id"])] = c["_detail"]
        self.challenges = challenges
        # ne reconstruire l'arbre que si l'affichage change réellement (sinon le curseur sauterait au poll)
        sig = tuple((int(c.get("id", 0)), bool(c.get("solved")), bool(c.get("downloaded")),
                     c.get("solves"), c.get("value"), c.get("name"), c.get("category"))
                    for c in sorted(challenges, key=lambda x: int(x.get("id", 0))))
        if sig != self._tree_sig:
            self._tree_sig = sig
            self._rebuild_tree()
        solved = sum(1 for c in challenges if c.get("solved"))
        dl = sum(1 for c in challenges if c.get("downloaded"))
        self.sub_title = (f"{solved}/{len(challenges)} résolus · {dl} téléchargés · "
                          f"filtre : {FILTER_LABEL[self.filter_mode]} · tri : {SORT_LABEL[self.sort_mode]}")
        self._render_stats()

        for ev in events or []:
            if ev.get("kind") == "desc":
                self._emit(f"✏️  {ev['name']} : {ev['msg']}", "warning", 7)
            elif ev.get("kind") == "hint":
                self._emit(f"💡 {ev['name']} : {ev['msg']}", "information", 6)
        if not self._first_sync and prev_ids:
            for c in challenges:
                cid = int(c["id"])
                if cid not in prev_ids:
                    self._emit(f"🆕 Nouveau : {c.get('name','?')} [{c.get('category','?')}]", "information", 7)
                if c.get("solved") and cid not in prev_solved:
                    self._emit(f"✔ Résolu : {c.get('name','?')}", "information", 4)
        if self._first_sync:
            self._reselect_last()
        self._first_sync = False

    def _reselect_last(self) -> None:
        last = getattr(self, "_last_selected_id", None)
        if last is None:
            return
        for c in self.challenges:
            if int(c["id"]) == int(last):
                self.selected = c
                self._render_detail(c, loading=True)
                self.detail_worker(int(c["id"]))
                break

    # -- arbre -----------------------------------------------------------
    def _sort_key(self, c: dict):
        if self.sort_mode == "points":
            return (-int(c.get("value", 0) or 0), c.get("name", ""))
        if self.sort_mode == "solves":
            return (-int(c.get("solves", 0) or 0), c.get("name", ""))
        return (int(c.get("value", 0) or 0), c.get("name", ""))

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        self._building = True
        try:
            tree.clear()
            cats: dict[str, list[dict]] = {}
            for c in self.challenges:
                if self.filter_mode == "unsolved" and c.get("solved"):
                    continue
                if self.filter_mode == "solved" and not c.get("solved"):
                    continue
                if self.search and self.search not in c.get("name", "").lower():
                    continue
                cats.setdefault(c.get("category", "?"), []).append(c)
            for cat in sorted(cats):
                items = sorted(cats[cat], key=self._sort_key)
                n_solved = sum(1 for i in items if i.get("solved"))
                # conserve l'état plié/déplié mémorisé pour cette catégorie
                node = tree.root.add(f"[b]{cat}[/b] ({n_solved}/{len(items)})",
                                     data={"_cat": cat}, expand=cat not in self.collapsed_cats)
                for c in items:
                    # colonne 1 = téléchargé (carré/boîte) · colonne 2 = résolu (cercle)
                    mark = "[b green]●[/b green]" if c.get("solved") else "[grey42]○[/grey42]"
                    dlm = "[b cyan]▣[/b cyan]" if c.get("downloaded") else "[grey42]▢[/grey42]"
                    slv = c.get("solves")
                    stail = f"   [dim]{c.get('value','')}pt · {slv} solves[/dim]" if slv is not None else f"   [dim]{c.get('value','')}pt[/dim]"
                    node.add_leaf(f"{dlm} {mark}  {c.get('name','?')}{stail}", data=c)
        finally:
            self._building = False

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        d = event.node.data
        if self._building or not d or "_cat" not in d:
            return
        self.collapsed_cats.add(d["_cat"])
        self._save_ui_state()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        d = event.node.data
        if self._building or not d or "_cat" not in d:
            return
        self.collapsed_cats.discard(d["_cat"])
        self._save_ui_state()

    # -- sélection -> détail ---------------------------------------------
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data or "_cat" in data:  # ignore les nœuds de catégorie
            return
        self.selected = data
        self._render_detail(data, loading=True)
        self.detail_worker(int(data["id"]))

    @work(thread=True, exclusive=True, group="detail")
    def detail_worker(self, cid: int) -> None:
        detail = self._detail_cache.get(cid)
        if detail is None:
            try:
                detail = self.client.challenge(cid)
            except CTFdError as e:
                self.call_from_thread(self.notify, f"Détail indisponible : {e}", severity="warning")
                return
            self._detail_cache[cid] = detail
        if cid not in self._fb_cache:
            self._fb_cache[cid] = self.client.first_blood(cid)
        if self.selected and int(self.selected["id"]) == cid:
            self.call_from_thread(self._render_detail, {**self.selected, **detail})

    def _render_detail(self, c: dict, loading: bool = False) -> None:
        files = [Path(f.split("?")[0]).name for f in (c.get("files") or [])]
        status = "● résolu" if c.get("solved") else "○ non résolu"
        cid = int(c.get("id", -1))
        meta = f"**Catégorie** : {c.get('category','?')}  ·  **Points** : {c.get('value','?')}  ·  **{status}**"
        if c.get("solves") is not None:
            meta += f"  ·  **Solves** : {c['solves']}"
        fb = self._fb_cache.get(cid)
        md = [f"# {c.get('name','?')}", meta]
        if fb:
            md.append(f"🩸 **First blood** : {fb}")
        md.append(f"**Connexion** : `{c.get('connection_info') or 'aucune'}`")
        prereqs = store.prereq_ids(c)
        if prereqs:
            by_id = {int(x["id"]): x for x in self.challenges if x.get("id") is not None}
            parts, all_ok = [], True
            for pid in prereqs:
                pc = by_id.get(int(pid))
                name = pc.get("name") if pc else f"#{pid}"
                ok = bool(pc and pc.get("solved"))
                all_ok = all_ok and ok
                parts.append(f"{'✔' if ok else '🔒'} {name}")
            lock = "déverrouillé" if all_ok else "🔒 verrouillé"
            md.append(f"**Prérequis** ({lock}) : " + ", ".join(parts))
        if c.get("path"):
            md.append(f"**Dossier** : `{c['path']}`  ·  {'▣ téléchargé' if c.get('downloaded') else '▢ non téléchargé (touche d)'}")
        if files:
            md.append("**Fichiers** (→ work/) : " + ", ".join(f"`{f}`" for f in files))
        ext = store.extract_links(c.get("description"))
        if ext:
            md.append("**Liens externes** : " + ", ".join(f"[{store.classify_link(u)}] {u}" for u in ext))
        hints = c.get("hints") or []
        if hints:
            hl = []
            for h in hints:
                tag = "gratuit" if h.get("cost", 0) == 0 else f"{h.get('cost')} pts"
                if h.get("content"):
                    hl.append(f"- **#{h.get('id')}** (débloqué, {tag}) : {h['content']}")
                else:
                    hl.append(f"- **#{h.get('id')}** (verrouillé, {tag}) : `u` pour débloquer")
            md.append("**Indices**\n" + "\n".join(hl))
        md.append("\n---\n")
        md.append("*Chargement…*" if loading else (store.clean_desc(c.get("description")) or "*(pas de description)*"))
        self.query_one("#detail", Markdown).update("\n\n".join(md))

    # -- recherche / filtre / tri ---------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search = event.value.strip().lower()
            self._rebuild_tree()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_unfocus(self) -> None:
        """Échap : quitter un champ de saisie, redonner le focus à la liste des challenges."""
        self.set_focus(self.query_one("#tree", Tree))

    def action_cycle_filter(self) -> None:
        self.filter_mode = FILTERS[(FILTERS.index(self.filter_mode) + 1) % len(FILTERS)]
        self._apply_view()

    def action_cycle_sort(self) -> None:
        self.sort_mode = SORTS[(SORTS.index(self.sort_mode) + 1) % len(SORTS)]
        self._apply_view()

    def action_cycle_theme(self) -> None:
        names = list(self.available_themes)
        try:
            i = names.index(self.theme)
        except ValueError:
            i = -1
        self.theme = names[(i + 1) % len(names)]
        self._emit(f"🎨 Thème : {self.theme}", "information", 3)
        self._save_ui_state()

    def _apply_view(self) -> None:
        self._rebuild_tree()
        solved = sum(1 for c in self.challenges if c.get("solved"))
        dl = sum(1 for c in self.challenges if c.get("downloaded"))
        self.sub_title = (f"{solved}/{len(self.challenges)} résolus · {dl} téléchargés · "
                          f"filtre : {FILTER_LABEL[self.filter_mode]} · tri : {SORT_LABEL[self.sort_mode]}")
        self._save_ui_state()

    def action_refresh(self) -> None:
        self.notify("Actualisation…", timeout=2)
        self.list_worker()
        self.scoreboard_worker()
        self.me_worker()

    def action_focus_flag(self) -> None:
        try:  # le champ flag est dans l'onglet Challenges : s'y placer d'abord
            self.query_one(TabbedContent).active = "tab-chal"
        except Exception:  # noqa: BLE001
            pass
        self.query_one("#flag", Input).focus()

    # -- téléchargement / sync ------------------------------------------
    def action_download(self) -> None:
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        # chemin unique auto-réparateur : (re)crée desc.txt si besoin + complète les fichiers
        self.notify(f"Téléchargement / mise à jour de {self.selected.get('name','?')}…", timeout=2)
        self.download_worker(dict(self.selected))

    def action_sync_all(self) -> None:
        n = len(self.challenges)
        q = (f"Tout synchroniser : télécharger les {n} challenges (parallèle) ?\n"
             f"Cela peut être long et volumineux.")

        def cb(ok):
            if ok:
                self.sync_all_worker()

        self.push_screen(ConfirmScreen(q), cb)

    def _current_category(self) -> str | None:
        """Catégorie sous le curseur (nœud de catégorie ou challenge), sinon celle du sélectionné."""
        try:
            node = self.query_one("#tree", Tree).cursor_node
        except Exception:  # noqa: BLE001
            node = None
        d = node.data if node else None
        if d:
            if "_cat" in d:
                return d["_cat"]
            if d.get("category"):
                return d["category"]
        return self.selected.get("category") if self.selected else None

    def action_download_category(self) -> None:
        cat = self._current_category()
        if not cat:
            self.notify("Place-toi sur une catégorie ou un challenge.", severity="warning")
            return
        subset = [c for c in self.challenges if c.get("category") == cat]
        q = (f"Télécharger les {len(subset)} challenges de « {cat} » (parallèle) ?\n"
             f"Les fichiers déjà présents sont sautés.")

        def cb(ok):
            if ok:
                self.download_category_worker(cat)

        self.push_screen(ConfirmScreen(q), cb)

    @work(thread=True, exclusive=True, group="syncall")  # même groupe que « Tout sync » : pas de collision
    def download_category_worker(self, cat: str) -> None:
        subset = [c for c in self.challenges if c.get("category") == cat]
        if not subset:
            return
        self._syncing = True
        self.call_from_thread(self._show_progress, True)

        def progress(done, total):
            self.call_from_thread(self._set_progress, done, total)

        self.call_from_thread(self._emit, f"⏳ Téléchargement de « {cat} »…", "information", 3)
        try:
            _, events = store.download_subset(
                self.client, self.cfg.base_dir, subset, self.cfg.watch_changes,
                self.cfg.auto_unlock_free_hints, self.cfg.download_workers, progress)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Catégorie KO : {e}", "error", 6)
            return
        finally:
            self._syncing = False
            self.call_from_thread(self._show_progress, False)
        n = sum(1 for c in subset if c.get("downloaded"))
        self.call_from_thread(self._apply_challenges, self.challenges, events)
        self.call_from_thread(self._emit, f"✅ « {cat} » : {n}/{len(subset)} téléchargés.", "information", 6)

    def action_export_progress(self) -> None:
        if not self.challenges:
            self.notify("Rien à exporter.", severity="warning")
            return
        try:
            p = store.write_progress(self.cfg.base_dir, self.challenges, self.cfg.ctf_name)
        except OSError as e:
            self._emit(f"Export PROGRESS KO : {e}", "error")
            return
        self._emit(f"📄 Progression exportée : {p}", "information", 5)

    # -- copier connexion / notes ---------------------------------------
    def action_copy_conn(self) -> None:
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        detail = self._detail_cache.get(int(self.selected["id"]), self.selected)
        text = detail.get("connection_info") or self.selected.get("path") or self.selected.get("name", "")
        try:
            self.copy_to_clipboard(text)
            self.notify(f"Copié : {text}", timeout=4)
        except Exception:  # noqa: BLE001
            self.notify(f"À copier : {text}", timeout=6)

    def action_open_folder(self) -> None:
        """Ouvre le dossier du challenge dans le gestionnaire de fichiers du système."""
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        path = self.selected.get("path")
        if not path or not Path(path).exists():
            self.notify("Dossier absent : télécharge d'abord (touche d).", severity="warning")
            return
        opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
        try:
            subprocess.Popen([opener, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.notify(f"📂 Ouverture : {path}", timeout=3)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Ouverture impossible ({e}) : {path}", severity="warning", timeout=6)

    def action_edit_notes(self) -> None:
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        d = Path(self.selected.get("path") or store.challenge_dir(
            self.cfg.base_dir, self.selected.get("category", ""), self.selected.get("name", "")))
        d.mkdir(parents=True, exist_ok=True)
        notes = d / "notes.md"
        if not notes.exists():
            notes.write_text(
                f"# {self.selected.get('name','?')}\n"
                f"**Catégorie :** {self.selected.get('category','?')} | "
                f"**Points :** {self.selected.get('value','?')}\n\n## Notes\n\n", encoding="utf-8")
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        try:
            with self.suspend():
                subprocess.call([editor, str(notes)])
            self._emit(f"📝 Notes éditées : {notes}", "information", 4)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Éditeur indisponible ({e}). Fichier : {notes}", severity="warning", timeout=6)

    # -- soumission ------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "flag":
            return
        flag = event.value.strip()
        if not flag:
            return
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        cid = int(self.selected["id"])
        if store.was_attempted(self.cfg.base_dir, cid, flag):
            self._emit(f"⚠️ Flag déjà tenté (incorrect), non resoumis : {flag}", "warning", 6)
            event.input.value = ""
            return
        self.submit_worker(cid, flag, self.selected.get("path", ""))
        event.input.value = ""

    @work(thread=True, exclusive=True, group="submit")
    def submit_worker(self, cid: int, flag: str, path: str) -> None:
        try:
            status, message = self.client.submit(cid, flag)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Soumission KO : {e}", "error")
            return
        if status == "correct":
            store.record_attempt(self.cfg.base_dir, cid, flag, True, path)
            if self.cfg.write_flag_on_solve and path:
                store.write_flag(path, flag)
            self.call_from_thread(self._after_solve, cid, message)
            self.scoreboard_worker()
            self.me_worker()
        elif status == "already_solved":
            self.call_from_thread(self._emit, "Déjà résolu.", "information")
        else:
            store.record_attempt(self.cfg.base_dir, cid, flag, False, path)
            self.call_from_thread(self._emit, f"✘ {status}: {message}".strip(), "warning", 5)

    def _after_solve(self, cid: int, message: str) -> None:
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                c["solved"] = True
        self._emit(f"✔ Correct ! {message}".strip(), "information", 6)
        self._apply_challenges(self.challenges)

    # -- déblocage d'indice ---------------------------------------------
    def action_unlock_hint(self) -> None:
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        detail = self._detail_cache.get(int(self.selected["id"]), self.selected)
        locked = [h for h in (detail.get("hints") or []) if not h.get("content")]
        if not locked:
            self.notify("Aucun indice verrouillé.", severity="information")
            return
        h = min(locked, key=lambda x: x.get("cost", 0))
        cost = h.get("cost", 0)
        tag = "gratuit" if cost == 0 else f"{cost} pts"
        q = (f"Débloquer l'indice #{h.get('id')} ({tag}) de « {self.selected.get('name','?')} » ?\n"
             f"⚠️ Un indice payant réduit ton score.")

        def cb(ok):
            if ok:
                self.unlock_worker(int(h["id"]), int(self.selected["id"]))

        self.push_screen(ConfirmScreen(q), cb)

    @work(thread=True, exclusive=True, group="unlock")
    def unlock_worker(self, hint_id: int, cid: int) -> None:
        try:
            self.client.unlock_hint(hint_id)
            detail = self.client.challenge(cid)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Déblocage KO : {e}", "error")
            return
        self._detail_cache[cid] = detail
        self.call_from_thread(self._emit, f"💡 Indice #{hint_id} débloqué.", "information", 6)
        if self.selected and int(self.selected["id"]) == cid:
            self.call_from_thread(self._render_detail, {**self.selected, **detail})


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cfg_path = argv[0] if argv else "config.sh"
    try:
        cfg = Config.load(cfg_path)
    except Exception as e:  # noqa: BLE001
        print(f"[flagship] config: {e}", file=sys.stderr)
        print("Usage: python -m flagship [chemin/config.sh]", file=sys.stderr)
        return 2
    Flagship(cfg).run()
    return 0
