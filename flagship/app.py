"""Flagship — TUI Textual pour un CTFd.

Onglets Challenges / Scoreboard ; listing léger par défaut, téléchargement à la demande
(`d`) ou complet (`D`, parallèle + barre de progression) ; recherche, tri, filtres ;
soumission, déblocage d'indice, copier la connexion, notes externes, export PROGRESS.md ;
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
from rich.text import Text

from .config import Config
from .ctfd import CTFd, CTFdError
from . import store

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


class NotificationsScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Fermer"), ("n", "dismiss", "Fermer")]
    CSS = """
    NotificationsScreen { align: center middle; }
    #nbox { width: 90%; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    """

    def __init__(self, lines: list[str]):
        super().__init__()
        self.lines = lines

    def compose(self) -> ComposeResult:
        with Vertical(id="nbox"):
            yield Static("[b]Notifications[/b] (Échap pour fermer)")
            with VerticalScroll():
                yield Static("\n".join(reversed(self.lines)) or "[dim]aucune notification[/dim]")

    def action_dismiss(self) -> None:
        self.dismiss(None)


class Flagship(App):
    CSS = """
    #search { dock: top; }
    #tree { width: 42%; border-right: solid $accent; }
    #rightcol { width: 1fr; }
    #detailwrap { height: 1fr; }
    #detail { padding: 0 1; }
    #flag { height: 3; border-top: solid $accent; }
    #progress { dock: bottom; height: 1; display: none; }
    #scoreboard { height: 1fr; }
    """

    BINDINGS = [
        ("r", "refresh", "Rafraîchir"),
        ("d", "download", "Télécharger"),
        ("D", "sync_all", "Tout sync"),
        ("f", "cycle_filter", "Filtre"),
        ("o", "cycle_sort", "Tri"),
        ("t", "cycle_theme", "Thème"),
        ("slash", "focus_search", "Rechercher"),
        ("s", "focus_flag", "Soumettre"),
        ("u", "unlock_hint", "Indice"),
        ("c", "copy_conn", "Copier"),
        ("e", "edit_notes", "Notes"),
        ("p", "export_progress", "Progress"),
        ("n", "show_notifs", "Notifs"),
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
        self._last_scoreboard: list[dict] = []
        self._detail_cache: dict[int, dict] = {}
        self._fb_cache: dict[int, str | None] = {}
        self.notifications: list[str] = []
        self._first_sync = True
        self._log_path = cfg.base_dir / ".flagship" / "notifications.log"
        self._state_path = cfg.base_dir / ".flagship" / "state.json"

    # -- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="🔎 Rechercher…  ( / )", id="search")
        with TabbedContent(initial="tab-chal"):
            with TabPane("Challenges", id="tab-chal"):
                with Horizontal():
                    yield Tree("Challenges", id="tree")
                    with Vertical(id="rightcol"):
                        with VerticalScroll(id="detailwrap"):
                            yield Markdown("*Sélectionne un challenge à gauche.*", id="detail")
                        yield Input(placeholder="🚩 Flag (Entrée = soumettre le challenge sélectionné)…", id="flag")
            with TabPane("Scoreboard", id="tab-score"):
                yield DataTable(id="scoreboard")
        yield ProgressBar(id="progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Flagship — {self.cfg.ctf_name}"
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
        self.notify(msg, severity=severity, timeout=timeout)

    # -- workers réseau --------------------------------------------------
    @work(thread=True, exclusive=True, group="sync")
    def list_worker(self) -> None:
        try:
            challenges, events = store.list_state(
                self.client, self.cfg.base_dir, self.cfg.watch_changes, self.cfg.auto_unlock_free_hints)
        except CTFdError as e:
            cached = store.load_cache(self.cfg.base_dir)  # mode hors-ligne
            if cached:
                self.call_from_thread(self._emit, f"📴 Hors-ligne : liste en cache ({e})", "warning", 6)
                self.call_from_thread(self._apply_challenges, cached, [])
            else:
                self.call_from_thread(self._emit, f"Liste impossible : {e}", "error", 6)
            return
        self.call_from_thread(self._apply_challenges, challenges, events)

    @work(thread=True, exclusive=True, group="me")
    def me_worker(self) -> None:
        me = self.client.me()
        if me:
            self.call_from_thread(self._apply_me, me)

    def _apply_me(self, me: dict) -> None:
        self.me = me
        s, p = me.get("score"), me.get("place")
        extra = ""
        if s is not None:
            extra = f" — score {s}" + (f" (#{p})" if p else "")
        self.title = f"Flagship — {self.cfg.ctf_name}{extra}"
        if self._last_scoreboard:  # re-surligner ta ligne sans refetch
            self._fill_scoreboard(self._last_scoreboard)

    @work(thread=True, exclusive=True, group="sync")
    def sync_all_worker(self) -> None:
        self.call_from_thread(self._show_progress, True)

        def progress(done, total):
            self.call_from_thread(self._set_progress, done, total)

        self.call_from_thread(self._emit, "⏳ Synchronisation complète…", "information", 3)
        try:
            challenges, events = store.sync(
                self.client, self.cfg.base_dir, self.cfg.watch_changes,
                self.cfg.auto_unlock_free_hints, self.cfg.download_workers, progress)
        except CTFdError as e:
            self.call_from_thread(self._show_progress, False)
            self.call_from_thread(self._emit, f"Sync complète impossible : {e}", "error", 6)
            return
        n = sum(1 for c in challenges if c.get("downloaded"))
        self.call_from_thread(self._apply_challenges, challenges, events)
        self.call_from_thread(self._show_progress, False)
        self.call_from_thread(self._emit, f"✅ Sync complète : {n} challenges téléchargés.", "information", 6)

    def _show_progress(self, on: bool) -> None:
        pb = self.query_one("#progress", ProgressBar)
        pb.display = on
        if on:
            pb.update(total=100, progress=0)

    def _set_progress(self, done: int, total: int) -> None:
        self.query_one("#progress", ProgressBar).update(total=total, progress=done)

    @work(thread=True, exclusive=True, group="download")
    def download_worker(self, summary: dict, retry: bool = False) -> None:
        try:
            if retry:
                report = store.redownload(self.client, self.cfg.base_dir, summary, self.cfg.auto_unlock_free_hints)
                ok = sum(1 for r in report if r.startswith("[ok]"))
                self.call_from_thread(self._emit, f"↻ {summary.get('name','?')} : {ok} fichier(s) OK", "information", 5)
                events = []
            else:
                path, events = store.download_one(
                    self.client, self.cfg.base_dir, summary, self.cfg.watch_changes, self.cfg.auto_unlock_free_hints)
                for c in self.challenges:
                    if int(c.get("id", -1)) == int(summary["id"]):
                        c["downloaded"] = True
                        c["path"] = path
                self.call_from_thread(self._emit, f"⬇ Téléchargé : {summary.get('name','?')}", "information", 5)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Téléchargement KO : {e}", "error")
            return
        self.call_from_thread(self._apply_challenges, self.challenges, events)

    @work(thread=True, exclusive=True, group="score")
    def scoreboard_worker(self) -> None:
        rows = self.client.scoreboard()
        self.call_from_thread(self._fill_scoreboard, rows)

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
        self._rebuild_tree()
        solved = sum(1 for c in challenges if c.get("solved"))
        dl = sum(1 for c in challenges if c.get("downloaded"))
        self.sub_title = (f"{solved}/{len(challenges)} résolus · {dl} téléchargés · "
                          f"filtre : {FILTER_LABEL[self.filter_mode]} · tri : {SORT_LABEL[self.sort_mode]}")

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
                    mark = "[green]✔[/green]" if c.get("solved") else "[grey50]○[/grey50]"
                    dlm = "[cyan]✓[/cyan]" if c.get("downloaded") else "[yellow]⬇[/yellow]"
                    slv = c.get("solves")
                    stail = f"  [dim]{c.get('value','')}pt · {slv}✓[/dim]" if slv is not None else f"  [dim]{c.get('value','')}pt[/dim]"
                    node.add_leaf(f"{mark}{dlm} {c.get('name','?')}{stail}", data=c)
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
        status = "✔ résolu" if c.get("solved") else "○ non résolu"
        cid = int(c.get("id", -1))
        meta = f"**Catégorie** : {c.get('category','?')}  ·  **Points** : {c.get('value','?')}  ·  **{status}**"
        if c.get("solves") is not None:
            meta += f"  ·  **Solves** : {c['solves']}"
        fb = self._fb_cache.get(cid)
        md = [f"# {c.get('name','?')}", meta]
        if fb:
            md.append(f"🩸 **First blood** : {fb}")
        md.append(f"**Connexion** : `{c.get('connection_info') or 'aucune'}`")
        if c.get("path"):
            md.append(f"**Dossier** : `{c['path']}`  ·  téléchargé : {'oui' if c.get('downloaded') else 'non (touche d)'}")
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
                    hl.append(f"- **#{h.get('id')}** (verrouillé, {tag}) — `u` pour débloquer")
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
        self.query_one("#flag", Input).focus()

    def action_show_notifs(self) -> None:
        self.push_screen(NotificationsScreen(self.notifications))

    # -- téléchargement / sync ------------------------------------------
    def action_download(self) -> None:
        if not self.selected:
            self.notify("Sélectionne d'abord un challenge.", severity="warning")
            return
        if self.selected.get("downloaded"):
            self.notify(f"Re-téléchargement (retry) de {self.selected.get('name','?')}…", timeout=2)
            self.download_worker(dict(self.selected), retry=True)
        else:
            self.notify(f"Téléchargement de {self.selected.get('name','?')}…", timeout=2)
            self.download_worker(dict(self.selected), retry=False)

    def action_sync_all(self) -> None:
        n = len(self.challenges)
        q = (f"Tout synchroniser : télécharger les {n} challenges (parallèle) ?\n"
             f"Cela peut être long et volumineux.")

        def cb(ok):
            if ok:
                self.sync_all_worker()

        self.push_screen(ConfirmScreen(q), cb)

    def action_export_progress(self) -> None:
        if not self.challenges:
            self.notify("Rien à exporter.", severity="warning")
            return
        p = store.write_progress(self.cfg.base_dir, self.challenges, self.cfg.ctf_name)
        self._emit(f"📄 PROGRESS.md écrit : {p}", "information", 5)

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
        self.submit_worker(int(self.selected["id"]), flag, self.selected.get("path", ""))
        event.input.value = ""

    @work(thread=True, exclusive=True, group="submit")
    def submit_worker(self, cid: int, flag: str, path: str) -> None:
        try:
            status, message = self.client.submit(cid, flag)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Soumission KO : {e}", "error")
            return
        if status == "correct":
            if self.cfg.write_flag_on_solve and path:
                store.write_flag(path, flag)
            for c in self.challenges:
                if int(c.get("id", -1)) == cid:
                    c["solved"] = True
            self.call_from_thread(self._emit, f"✔ Correct ! {message}".strip(), "information", 6)
            self.call_from_thread(self._apply_challenges, self.challenges)
            self.scoreboard_worker()
            self.me_worker()
        elif status == "already_solved":
            self.call_from_thread(self._emit, "Déjà résolu.", "information")
        else:
            self.call_from_thread(self._emit, f"✘ {status}: {message}".strip(), "warning", 5)

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
