"""Flagship: Textual TUI for a CTFd instance.

Challenges / Scoreboard / Stats / Notifications tabs; light listing by default, download on demand
(`d`), per category (`C`) or full (`D`, parallel + progress bar); search, sort, filters;
flag submission, hint unlock, copy connection info, external notes, PROGRESS_flagship.md export;
notifications (toasts + log + history). The token is never displayed.

Usage: python -m flagship [path/config.sh]
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
from textual.widget import Widget
from textual import events
from rich.text import Text
from rich.segment import Segment
from rich.style import Style
from rich.cells import cell_len

from .config import Config
from .ctfd import CTFd, CTFdError
from . import store

BEAM_CHAR = "│"  # thin vertical bar (U+2502), centered in its cell so both neighbouring
                 # characters sit flush against it ; "▏" (U+258F) hugs the left edge only,
                 # leaving a visible gap before the character on the right


class BeamInput(Input):
    """Input field whose cursor is a vertical bar ("I-beam") instead of the default
    reversed block.

    The bar is INSERTED in its own cell between the character before and the character after
    the cursor, never drawn on top of (replacing) either one: with a block cursor, the
    character right after the cursor is hidden every time the cursor blinks on, which is the
    one thing an insertion-point cursor must never do. That cell is reserved at all times
    (focused, regardless of blink phase) and just toggles between the bar glyph and a blank, so
    the rest of the line does not visibly shift back and forth as it blinks. Delete/Backspace
    behave exactly as before: this only changes how the cursor is drawn, not Input's own
    editing logic. On any incompatibility, it silently falls back to the standard cursor.

    `center=True` (the flag field): placeholder and typed text are centered in the box instead
    of hugging the left edge, cursor included. Falls back to the normal left-aligned rendering
    whenever the content is too long to fit (a flag that overflows the box still needs Textual's
    own scrolling, which the centered path doesn't attempt to replicate)."""

    _suppress_native_cursor = False

    def __init__(self, *args, center: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._center = center

    def get_component_rich_style(self, *names, **kwargs):
        # only neutralise the native cursor style during our own render
        if self._suppress_native_cursor and names == ("input--cursor",):
            return Style()
        return super().get_component_rich_style(*names, **kwargs)

    def render_line(self, y: int) -> Strip:
        if y != 0:
            return super().render_line(y)
        if self._center:
            try:
                centered = self._render_centered()
                if centered is not None:
                    return centered
            except Exception:
                pass  # fall through to the normal (left-aligned) rendering below
        if not self.has_focus:
            return super().render_line(0)
        try:
            return self._render_insertion_cursor()
        except Exception:
            return super().render_line(0)  # fallback: default cursor

    def _cursor_slot_style(self) -> Style:
        # bar colour = fill colour of the native block (follows the theme)
        cur = super().get_component_rich_style("input--cursor")
        return self.rich_style + Style(color=cur.bgcolor, bold=True)

    def _insert_slot(self, strip: Strip, col: int, width: int) -> Strip:
        """Insert a one-cell slot (the cursor bar, or a blank when blinked off) right at `col`,
        shifting everything from `col` onward by one cell instead of overwriting it, then crop
        back to `width` so the box keeps its size (the cell pushed past the right edge is simply
        the one that becomes hidden, same as any text editor scrolling/clipping its tail)."""
        glyph = BEAM_CHAR if self._cursor_visible else " "
        style = self._cursor_slot_style() if self._cursor_visible else self.rich_style
        slot = Strip([Segment(glyph, style)])
        left = strip.crop(0, col)
        right = strip.crop(col, width)  # nothing dropped: the char that was at `col` moves to col+1
        return Strip.join([left, slot, right]).crop(0, width)

    def _render_insertion_cursor(self) -> Strip:
        # 1) normal render but WITHOUT the native cursor block
        self._suppress_native_cursor = True
        strip = super().render_line(0)
        self._suppress_native_cursor = False
        width = strip.cell_length

        # 2) visual column of the cursor (handles wide characters)
        col = cell_len(self.value[: self.cursor_position]) - self.scroll_offset.x
        if col < 0 or col > width:
            return strip
        return self._insert_slot(strip, col, width)

    def _render_centered(self) -> Strip | None:
        """Placeholder or value, centered in the box ; the I-beam cursor (if focused) sits
        wherever that centered text puts it. Returns None to signal "doesn't fit, use the
        normal rendering instead" rather than attempting to crop/scroll it."""
        width = self.scrollable_content_region.width
        showing_placeholder = not self.value
        text = self.placeholder if showing_placeholder else self.value
        content_len = cell_len(text)
        if content_len > width:
            return None
        pad_left = (width - content_len) // 2

        text_style = (self.get_component_rich_style("input--placeholder") if showing_placeholder
                     else self.rich_style)
        strip = Strip([Segment(" " * pad_left), Segment(text, text_style)])
        # one extra column of slack: if the text exactly fills `width` and the cursor sits right
        # at the end, _insert_slot needs somewhere to put it without just cropping it away
        strip = strip.extend_cell_length(width + 1, self.rich_style)

        if self.has_focus:
            col = pad_left if showing_placeholder else pad_left + cell_len(self.value[: self.cursor_position])
            if 0 <= col <= width:
                strip = self._insert_slot(strip, col, width + 1)
        # final width is `width + 1`, matching what Textual's own Input always renders at
        # (`scrollable_content_region.width` is 1 less than the strip it actually expects)
        return strip.apply_style(self.rich_style)

class Splitter(Widget):
    """Vertical separator draggable with the mouse between the challenge list and the detail.
    Drag = resize the left column; double-click = back to the default width."""

    DEFAULT_CSS = """
    Splitter { width: 1; height: 1fr; color: $accent; }
    Splitter:hover, Splitter.-dragging { color: $warning; background: $boost; }
    """
    MIN_LEFT = 16
    MIN_RIGHT = 24

    def __init__(self, left_id: str, **kw):
        super().__init__(**kw)
        self._left_id = left_id
        self._dragging = False

    def render(self) -> Text:
        return Text("\n".join("┃" for _ in range(max(1, self.size.height))))

    def _left(self) -> Widget:
        return self.screen.query_one(f"#{self._left_id}")

    def _right(self) -> Widget:
        return self.screen.query_one("#rightcol")

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        left = self._left()
        total = left.region.width + self.region.width + self._right().region.width
        width = event.screen_x - left.region.x
        width = max(self.MIN_LEFT, min(width, total - self.MIN_RIGHT - self.region.width))
        left.styles.width = width
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("-dragging")
            self.release_mouse()
            self.app._save_ui_state()
            self.app._refresh_detail_width()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        if event.chain >= 2:
            self._left().styles.width = "42%"
            self.app._save_ui_state()
            self.app._refresh_detail_width()


FILTERS = ("all", "unsolved", "solved")
FILTER_LABEL = {"all": "all", "unsolved": "unsolved", "solved": "solved"}
SORTS = ("category", "points", "solves", "fewest", "name", "id", "downloaded", "unsolved")
SORT_LABEL = {
    "category": "category", "points": "points", "solves": "solves", "fewest": "fewest solves",
    "name": "name A→Z", "id": "CTFd id", "downloaded": "downloaded first", "unsolved": "unsolved first",
}


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
                yield Button("Yes", variant="warning", id="yes")
                yield Button("No", variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


def build_member_md(name: str, challenges: list[dict], solved_ids: set[int],
                    fb_cache: dict[int, str] | None = None,
                    team_name: str | None = None) -> str:
    """Markdown for a member's detail: "By category" + "Progress by category",
    computed from the challenges they solved (ranked by descending points).

    `fb_cache` (optional): {challenge_id: first-solver-name}. In team mode, CTFd's public
    solves list attributes a solve to the TEAM, not the member, so a first blood is counted for
    this member when `fb_cache[cid] == team_name` (the team's own first blood) AND the
    challenge is in this member's personal `solved_ids` (which DOES come from a per-member
    source: `/teams/me/solves`'s `user` field), meaning they personally made that winning
    submission. `team_name` defaults to `name` for the solo-player case."""
    fb_cache = fb_cache or {}
    fb_name = team_name if team_name is not None else name
    cats: dict[str, dict] = {}
    total_s = total_p = total_fb = 0
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
            if fb_cache.get(cid) == fb_name:
                total_fb += 1
    fb_note = f"  ·  **First bloods**: {total_fb}" if fb_cache else ""
    md = [f"# {name}", "", f"**Solved**: {total_s}  ·  **Points**: {total_p}{fb_note}"]
    done = {k: v for k, v in cats.items() if v["s"] > 0}
    if not done:
        md += ["", "*No challenge solved yet.*"]
        return "\n".join(md)
    order = sorted(done, key=lambda k: (-done[k]["pw"], -done[k]["s"], k.lower()))
    md += ["", "## By category (ranked by points)", "",
           "| Category | Solved | Points |", "|----------|--------|--------|"]
    for cat in order:
        d = done[cat]
        md.append(f"| {cat} | {d['s']}/{d['n']} | {d['pw']}/{d['pt']} |")
    md += ["", "## Progress by category", "", "```"]
    wname = max(len(c) for c in order)
    for cat in order:
        d = done[cat]
        filled = round((d["s"] / d["n"]) * 12) if d["n"] else 0
        md.append(f"{cat.ljust(wname)}  {'█' * filled}{'░' * (12 - filled)}  {d['s']}/{d['n']}")
    md.append("```")
    return "\n".join(md)


class MemberStatsScreen(ModalScreen[None]):
    """Member detail window (opened by clicking their name in the Stats tab)."""
    BINDINGS = [("escape", "dismiss", "Close")]
    CSS = """
    MemberStatsScreen { align: center middle; }
    #mbox { width: 80%; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #mhead { color: $text-muted; }
    """

    def __init__(self, name: str, challenges: list[dict], solved_ids: set[int],
                fb_cache: dict[int, str] | None = None, team_name: str | None = None):
        super().__init__()
        self._name = name
        self._challenges = challenges
        self._solved = solved_ids
        self._fb_cache = fb_cache
        self._team_name = team_name

    def compose(self) -> ComposeResult:
        with Vertical(id="mbox"):
            yield Static("Esc to close", id="mhead")
            with VerticalScroll():
                yield Markdown(build_member_md(self._name, self._challenges, self._solved,
                                               self._fb_cache, self._team_name),
                               open_links=False)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class Flagship(App):
    CSS = """
    Header HeaderIcon { display: none; }  /* drop the "⭘" command-palette icon, top-left */
    /* clicking the header normally toggles it to 3 rows (Textual's HeaderTitle.-tall) ;
       pin it to 1 row always, so a stray click never opens a gap above the tabs */
    Header.-tall { height: 1; }
    /* the screen itself must never scroll: every pane that needs it (tree, detail, stats,
       notifications) already has its own scrollbar, so a 1-row layout mismatch must never
       spawn a second, screen-wide scrollbar next to a pane's real one */
    Screen { overflow-y: hidden; }
    #treecol { width: 42%; }
    #legend_icons { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #legend_row { height: 1; background: $panel; }
    #legend_labels { width: auto; padding: 0 0 0 1; color: $text-muted; }
    #search { border: none; height: 1; width: 1fr; padding: 0 1; background: $panel; }
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
        ("r", "refresh", "Refresh"),
        ("d", "download", "Download"),
        ("D", "sync_all", "Sync all"),
        ("C", "download_category", "Cat. dl"),
        ("f", "cycle_filter", "Filter"),
        ("o", "cycle_sort", "Sort"),
        ("t", "cycle_theme", "Theme"),
        ("slash", "focus_search", "Search"),
        ("s", "focus_flag", "Submit"),
        ("u", "unlock_hint", "Hint"),
        ("c", "copy_conn", "Copy"),
        ("w", "open_folder", "Folder"),
        ("e", "edit_notes", "Notes"),
        ("p", "export_progress", "Progress"),
        ("q", "quit", "Quit"),
        Binding("escape", "unfocus", "Leave field", show=False),
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
        self._session_solved: set[int] = set()  # solved during this session: stay visible under "unsolved"
        self.collapsed_cats: set[str] = set()  # collapsed categories (default = expanded)
        self._building = False                  # re-entrancy guard while the tree is being rebuilt
        self.me: dict = {}
        self._personal: dict = {}             # individual stats (team mode only)
        self._members: list[dict] = []        # per-member team contribution (team mode)
        self._last_scoreboard: list[dict] = []
        self._detail_cache: dict[int, dict] = {}
        self._fb_cache: dict[int, str] = {}
        self._fb_backoff = False  # True once a whole fb_worker batch failed (e.g. CTF over)
        self.notifications: list[str] = []
        self._first_sync = True
        self._syncing = False               # True during "Sync all" (prevents the poll from cancelling it)
        self._tree_sig = None               # signature of the displayed data (avoids useless rebuilds)
        self._log_path = cfg.base_dir / ".flagship" / "notifications.log"
        self._state_path = cfg.base_dir / ".flagship" / "state.json"

    # -- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="tab-chal"):
            with TabPane("Challenges", id="tab-chal"):
                with Horizontal():
                    with Vertical(id="treecol"):
                        # icons line ; filled in by _update_legend() (single source of truth)
                        yield Static(id="legend_icons")
                        with Horizontal(id="legend_row"):
                            # "filter: … sort: …" ; filled in by _update_legend() too
                            yield Static(id="legend_labels")
                            # no separate row, no border: lives right on the filter/sort line,
                            # so it never costs any extra terminal height, focused or not (`/`)
                            yield BeamInput(placeholder="(type to filter)", id="search")
                        yield Tree("Challenges", id="tree")
                    yield Splitter("treecol", id="splitter")
                    with Vertical(id="rightcol"):
                        with VerticalScroll(id="detailwrap"):
                            yield Markdown("*Select a challenge on the left.*", id="detail")
                        yield BeamInput(placeholder="Submit 🚩", id="flag", center=True)
            with TabPane("Scoreboard", id="tab-score"):
                yield DataTable(id="scoreboard")
            with TabPane("Stats", id="tab-stats"):
                with VerticalScroll():
                    yield Markdown("*Statistics…*", id="stats", open_links=False)
            with TabPane("Notifications", id="tab-notifs"):
                with VerticalScroll():
                    yield Static("No notifications.", id="notifs")
        yield ProgressBar(id="progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tree", Tree).show_root = False
        dt = self.query_one("#scoreboard", DataTable)
        dt.add_columns("#", "Team / Player", "Score")
        dt.cursor_type = "row"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        cached_fb = store.load_json(self.cfg.base_dir, "fb_cache.json", {}) or {}
        self._fb_cache = {int(k): v for k, v in cached_fb.items()}
        self._restore_ui_state()
        self._update_legend()
        th = getattr(self, "_pref_theme", None) or self.cfg.theme
        if th in self.available_themes:
            self.theme = th
        self._update_title()
        self.list_worker()
        self.scoreboard_worker()
        self.me_worker()
        if self.cfg.poll_interval and self.cfg.poll_interval > 0:
            self.set_interval(self.cfg.poll_interval, self.list_worker)
            self.set_interval(self.cfg.poll_interval, self.scoreboard_worker)
            self.set_interval(self.cfg.poll_interval, self.me_worker)

    def on_unmount(self) -> None:
        self._save_ui_state()

    # -- persistent UI state ------------------------------------
    def _restore_ui_state(self) -> None:
        try:
            s = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.sort_mode = s.get("sort", self.sort_mode)
            self.collapsed_cats = set(s.get("collapsed", []))
            self._last_selected_id = s.get("selected")
            self._pref_theme = s.get("theme")
            self._tree_width = s.get("tree_width")
        except (OSError, ValueError):
            self._last_selected_id = None
            self._pref_theme = None
            self._tree_width = None
        w = getattr(self, "_tree_width", None)
        if isinstance(w, str) and w.endswith("%"):
            self.query_one("#treecol").styles.width = w

    def _tree_width_str(self) -> str | None:
        """List width as a % of the Challenges area (independent of terminal size)."""
        try:
            col = self.query_one("#treecol")
            total = col.parent.region.width
            return f"{max(5, min(95, round(col.region.width * 100 / total)))}%" if total else None
        except Exception:
            return getattr(self, "_tree_width", None)

    def _save_ui_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "sort": self.sort_mode,
                "selected": (self.selected or {}).get("id"),
                "collapsed": sorted(self.collapsed_cats),
                "theme": self.theme,
                "tree_width": self._tree_width_str(),
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
        """Update the Notifications tab (most recent on top)."""
        try:
            w = self.query_one("#notifs", Static)
        except Exception:  # noqa: BLE001  (widget not mounted yet)
            return
        # Text() => no markup interpretation (the [HH:MM:SS] timestamps stay literal)
        w.update(Text("\n".join(reversed(self.notifications)) or "No notifications."))

    # -- network workers --------------------------------------------------
    @work(thread=True, exclusive=True, group="sync")
    def list_worker(self) -> None:
        if self._syncing:  # a full sync is running: do not interfere
            return
        try:
            challenges, events = store.list_state(
                self.client, self.cfg.base_dir, self.cfg.watch_changes, self.cfg.auto_unlock_free_hints)
        except CTFdError as e:
            # diagnosis: valid token but challenges unreachable (CTF over/hidden)?
            hint = ""
            if "403" in str(e) or "access denied" in str(e):
                if self.client.auth_ok():
                    hint = " (token OK: challenges hidden, CTF over or not started yet)"
                else:
                    hint = " (token rejected: regenerate it in Settings > Access Tokens)"
            cached = store.load_cache(self.cfg.base_dir)  # offline mode
            if cached:
                self.call_from_thread(self._emit, f"📴 Offline: showing cached list{hint}", "warning", 7)
                self.call_from_thread(self._apply_challenges, cached, [])
            else:
                self.call_from_thread(self._emit, f"Cannot list challenges: {e}{hint}", "error", 8)
            return
        self.call_from_thread(self._apply_challenges, challenges, events)

    @work(thread=True, exclusive=True, group="me")
    def me_worker(self) -> None:
        me = self.client.me()
        personal, members = None, None
        if me and self.client.is_team_mode():  # in a team: personal stats + member contributions
            personal = self.client.me_user()
            members = self.client.team_member_stats()
        if me:
            # cache the profile (score/rank/team) to see it again offline / after the CTF
            store.save_json(self.cfg.base_dir, "me_cache.json",
                            {"me": me, "personal": personal, "members": members})
            self.call_from_thread(self._apply_me, me, personal, members)
        else:  # API unavailable (offline or CTF over): show the last known profile again
            cached = store.load_json(self.cfg.base_dir, "me_cache.json")
            if cached and cached.get("me"):
                self.call_from_thread(self._apply_me, cached["me"],
                                      cached.get("personal"), cached.get("members"))

    def _update_title(self) -> None:
        """Just the app name, centered by Header. Score, rank, solved/downloaded counts and the
        active filter/sort are all shown elsewhere already (Stats tab, legend row), so this line
        stays uncluttered."""
        self.title = "Flagship"

    def _render_stats(self) -> None:
        try:
            w = self.query_one("#stats", Markdown)
        except Exception:  # noqa: BLE001
            return
        chs = self.challenges
        if not chs:
            w.update("*No data yet. Run a sync (`r`).*")
            return
        total = len(chs)
        solved = [c for c in chs if c.get("solved")]
        dled = [c for c in chs if c.get("downloaded")]
        pts_won = sum(int(c.get("value") or 0) for c in solved)
        pts_all = sum(int(c.get("value") or 0) for c in chs)
        s, p = self.me.get("score"), self.me.get("place")
        team = self.me.get("team")
        md = [f"# Statistics · {self.cfg.ctf_name}", ""]
        my_name = self.me.get("name")
        solved_ids = {int(c["id"]) for c in solved}
        known_fb = {cid: self._fb_cache[cid] for cid in solved_ids if cid in self._fb_cache}
        fb_count = sum(1 for n in known_fb.values() if n == my_name)
        pending = len(solved_ids) - len(known_fb)
        fb_label = "Team first bloods" if team else "First bloods"

        rows = []
        if my_name:
            rows.append(("Team" if team else "Player", my_name))
        if s is not None:
            score_label = "Score (team)" if team else "Score"
            rows.append((score_label, f"{s}" + (f"  ·  Rank #{p}" if p else "")))
        rows.append(("Solved", f"{len(solved)} / {total}"))
        rows.append(("Points earned", f"{pts_won} / {pts_all}"))
        rows.append(("Downloaded", f"{len(dled)} / {total}"))
        rows.append((fb_label, f"{fb_count} / {len(solved)}" +
                    (f"  ·  _checking {pending} more…_" if pending else "")))
        md += ["| Stat | Value |", "|------|-------|"]
        md += [f"| {k} | {v} |" for k, v in rows]
        if self._personal:  # team mode: each member's contribution
            val = {int(c["id"]): int(c.get("value") or 0) for c in chs if c.get("id") is not None}
            my_id = self._personal.get("id")
            ps, pp = self._personal.get("score"), self._personal.get("place")
            md += ["", "## Team members"]
            if ps is not None:
                rank = f"#{pp}" if pp else "—"
                md.append(f"*Your individual rank: {rank} · your score: {ps}*")
            rows = [(m.get("name", "?"), m.get("count", 0),
                     sum(val.get(cid, 0) for cid in m.get("solved_ids", [])), m.get("user_id"))
                    for m in self._members]
            # guarantee your own row even if you have not solved anything yet
            if my_id is not None and my_id not in {r[3] for r in rows}:
                rows.append((self._personal.get("name", "you"), 0, 0, my_id))
            rows.sort(key=lambda r: (-r[2], -r[1], r[0].lower()))
            md += ["*Click a name to see their breakdown by category.*", "",
                   "| Member | Solved | Points |", "|--------|--------|--------|"]
            for name, cnt, pts, uid in rows:
                me_row = my_id is not None and uid == my_id
                label = f"{name} (you)" if me_row else name
                # clickable name (href 'member:<id>') intercepted by on_markdown_link_clicked
                link = f"[{label}](member:{uid})" if uid is not None else label
                nm = f"**{link}**" if me_row else link
                c2 = f"**{cnt}**" if me_row else str(cnt)
                c3 = f"**{pts}**" if me_row else str(pts)
                md.append(f"| {nm} | {c2} | {c3} |")
            if not rows:
                md.append("| *(no solves yet)* |  |  |")
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
        md += ["", "## By category", "",
               "| Category | Solved | Points | Downloaded |",
               "|----------|--------|--------|------------|"]
        for cat in sorted(cats):
            d = cats[cat]
            md.append(f"| {cat} | {d['s']}/{d['n']} | {d['pw']}/{d['pt']} | {d['dl']}/{d['n']} |")
        md += ["", "## Progress by category", "", "```"]
        wname = max((len(cat) for cat in cats), default=0)
        for cat in sorted(cats):
            d = cats[cat]
            filled = round((d["s"] / d["n"]) * 12) if d["n"] else 0
            bar = "█" * filled + "░" * (12 - filled)
            md.append(f"{cat.ljust(wname)}  {bar}  {d['s']}/{d['n']}")
        md.append("```")
        w.update("\n".join(md))

    def on_markdown_link_clicked(self, event) -> None:
        """Click on a name (href 'member:<id>') in the Stats tab → opens their detail box.
        Other links (external links in the detail, http) are ignored here."""
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
            m.get("name", "?"), self.challenges, set(m.get("solved_ids", [])),
            self._fb_cache, self.me.get("name")))

    def _apply_me(self, me: dict, personal: dict | None = None,
                  members: list | None = None) -> None:
        self.me = me or self.me
        if personal is not None:
            self._personal = personal
        if members is not None:
            self._members = members
        self._render_stats()
        if self._last_scoreboard:  # re-highlight your row without refetching
            self._fill_scoreboard(self._last_scoreboard)

    @work(thread=True, exclusive=True, group="syncall")  # separate group: not cancelled by the poll/list
    def sync_all_worker(self) -> None:
        self._syncing = True
        self.call_from_thread(self._show_progress, True)

        def progress(done, total):
            self.call_from_thread(self._set_progress, done, total)

        self.call_from_thread(self._emit, "⏳ Full sync…", "information", 3)
        try:
            challenges, events = store.sync(
                self.client, self.cfg.base_dir, self.cfg.watch_changes,
                self.cfg.auto_unlock_free_hints, self.cfg.download_workers, progress)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Full sync failed: {e}", "error", 6)
            return
        finally:
            self._syncing = False
            self.call_from_thread(self._show_progress, False)
        n = sum(1 for c in challenges if c.get("downloaded"))
        self.call_from_thread(self._apply_challenges, challenges, events)
        self.call_from_thread(self._emit, f"✅ Full sync: {n} challenges downloaded.", "information", 6)

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
            self.call_from_thread(self._emit, f"Download failed: {e}", "error")
            return
        downloaded = (Path(path) / "desc.txt").exists()  # actual state on disk (self-healed)
        self.call_from_thread(self._after_download, int(summary["id"]), path, downloaded,
                              summary.get("name", "?"), events)

    def _after_download(self, cid: int, path: str, downloaded: bool, name: str, events: list) -> None:
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                c["downloaded"] = downloaded
                c["path"] = path
        self._emit(f"⬇ {name}: up to date", "information", 5)
        self._apply_challenges(self.challenges, events)

    @work(thread=True, exclusive=True, group="score")
    def scoreboard_worker(self) -> None:
        rows = self.client.scoreboard()
        if rows:
            store.save_json(self.cfg.base_dir, "scoreboard_cache.json", rows)
            self.call_from_thread(self._fill_scoreboard, rows)
        else:  # API unavailable: show the last known scoreboard again
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

    @work(thread=True, exclusive=True, group="fb")
    def fb_worker(self) -> None:
        """Background: fetch the first solver of every SOLVED challenge whose first blood isn't
        cached yet, so the Stats tab can show how many of them were our own first blood. Cheap on
        a normal poll (nothing to fetch once the backlog is known), persisted so it is only ever
        paid once per challenge."""
        if self._fb_backoff:  # a previous batch failed entirely (CTF over?) : wait for `r`
            return
        ids = [int(c["id"]) for c in self.challenges if c.get("solved")]
        todo = [cid for cid in ids if cid not in self._fb_cache]
        new, errors = store.fetch_first_bloods(self.client, ids, self._fb_cache, self.cfg.download_workers)
        if todo and errors == len(todo):  # every single lookup failed : stop hammering the API
            self._fb_backoff = True
        if not new:
            return
        self._fb_cache.update(new)
        store.save_json(self.cfg.base_dir, "fb_cache.json",
                        {str(k): v for k, v in self._fb_cache.items()})
        self.call_from_thread(self._render_stats)

    # -- applying data ----------------------------------------
    def _apply_challenges(self, challenges: list[dict], events: list[dict] | None = None) -> None:
        prev_ids = {int(c["id"]) for c in self.challenges}
        prev_solved = {int(c["id"]) for c in self.challenges if c.get("solved")}
        for c in challenges:
            if c.get("_detail"):
                self._detail_cache[int(c["id"])] = c["_detail"]
        self.challenges = challenges
        if not self._first_sync:  # newly solved: keep it visible under the "unsolved" filter
            self._session_solved |= {int(c["id"]) for c in challenges
                                     if c.get("solved") and int(c["id"]) not in prev_solved}
        # only rebuild the tree if the display really changes (otherwise the cursor would jump on poll)
        sig = tuple((int(c.get("id", 0)), bool(c.get("solved")), bool(c.get("downloaded")),
                     c.get("solves"), c.get("value"), c.get("name"), c.get("category"))
                    for c in sorted(challenges, key=lambda x: int(x.get("id", 0))))
        if sig != self._tree_sig:
            self._tree_sig = sig
            self._rebuild_tree()
        self._render_stats()
        self.fb_worker()

        for ev in events or []:
            if ev.get("kind") == "desc":
                self._emit(f"✏️  {ev['name']}: {ev['msg']}", "warning", 7)
            elif ev.get("kind") == "hint":
                self._emit(f"💡 {ev['name']}: {ev['msg']}", "information", 6)
        if not self._first_sync and prev_ids:
            for c in challenges:
                cid = int(c["id"])
                if cid not in prev_ids:
                    self._emit(f"🆕 New: {c.get('name','?')} [{c.get('category','?')}]", "information", 7)
                if c.get("solved") and cid not in prev_solved:
                    self._emit(f"✔ Solved: {c.get('name','?')}", "information", 4)
        if self._first_sync:
            self._reselect_last()
        self._first_sync = False

    def _refresh_detail_width(self) -> None:
        """Re-render the current detail so its section dividers re-center after a pane resize."""
        if not self.selected:
            return
        cid = int(self.selected["id"])
        self._render_detail({**self.selected, **self._detail_cache.get(cid, {})})

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

    # -- tree -----------------------------------------------------------
    def _sort_key(self, c: dict):
        if self.sort_mode == "points":
            return (-int(c.get("value", 0) or 0), c.get("name", ""))
        if self.sort_mode == "solves":
            return (-int(c.get("solves", 0) or 0), c.get("name", ""))
        if self.sort_mode == "fewest":
            return (int(c.get("solves", 0) or 0), c.get("name", ""))
        if self.sort_mode == "name":
            return (c.get("name", "").lower(),)
        if self.sort_mode == "id":
            return (int(c.get("id", 0) or 0),)
        if self.sort_mode == "downloaded":
            return (not c.get("downloaded"), int(c.get("value", 0) or 0), c.get("name", ""))
        if self.sort_mode == "unsolved":
            return (bool(c.get("solved")), int(c.get("value", 0) or 0), c.get("name", ""))
        return (int(c.get("value", 0) or 0), c.get("name", ""))

    def _passes_filter(self, c: dict) -> bool:
        """Status filter (`f`): all / unsolved / solved."""
        if self.filter_mode == "unsolved":
            return not c.get("solved") or int(c.get("id", -1)) in self._session_solved
        if self.filter_mode == "solved":
            return bool(c.get("solved"))
        return True

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        self._building = True
        try:
            tree.clear()
            cats: dict[str, list[dict]] = {}
            for c in self.challenges:
                if not self._passes_filter(c):
                    continue
                if self.search and self.search not in c.get("name", "").lower():
                    continue
                cats.setdefault(c.get("category", "?"), []).append(c)
            for cat in sorted(cats):
                items = sorted(cats[cat], key=self._sort_key)
                n_solved = sum(1 for i in items if i.get("solved"))
                # keep the remembered collapsed/expanded state for this category
                node = tree.root.add(f"[b]{cat}[/b] ({n_solved}/{len(items)})",
                                     data={"_cat": cat}, expand=cat not in self.collapsed_cats)
                for c in items:
                    # column 1 = downloaded (square/box) · column 2 = solved (circle)
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

    # -- selection -> detail ---------------------------------------------
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data or "_cat" in data:  # ignore category nodes
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
                self.call_from_thread(self.notify, f"Details unavailable: {e}", severity="warning")
                return
            self._detail_cache[cid] = detail
        if cid not in self._fb_cache:
            fb = self.client.first_blood(cid)
            if fb is not None:  # "no solver yet" is never cached: it can change later, unlike a
                self._fb_cache[cid] = fb  # real first blood, which is permanent once set
        if self.selected and int(self.selected["id"]) == cid:
            self.call_from_thread(self._render_detail, {**self.selected, **detail})

    def _rule(self, title: str) -> str:
        """Centered section divider (`────TITLE────`), sized to the detail pane's current
        content width so it stays centered after a resize (splitter drag or terminal resize)."""
        try:
            width = self.query_one("#detail").size.width - 2  # minus the left/right padding
        except Exception:
            width = 0
        width = max(width, len(title) + 4)
        left = (width - len(title)) // 2
        return "─" * left + title + "─" * (width - len(title) - left)

    def _render_detail(self, c: dict, loading: bool = False) -> None:
        files = [Path(f.split("?")[0]).name for f in (c.get("files") or [])]
        status = "● solved" if c.get("solved") else "○ unsolved"
        cid = int(c.get("id", -1))
        meta = f"**Category**: {c.get('category','?')}  ·  **Points**: {c.get('value','?')}  ·  **{status}**"
        if c.get("solves") is not None:
            meta += f"  ·  **Solves**: {c['solves']}"
        fb = self._fb_cache.get(cid)
        md = [f"# {c.get('name','?')}", self._rule("INFO"), meta]
        if fb:
            md.append(f"🩸 **First blood**: {fb}")
        md.append(f"**Connection**: `{c.get('connection_info') or 'none'}`")
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
            lock = "unlocked" if all_ok else "🔒 locked"
            md.append(f"**Prerequisites** ({lock}): " + ", ".join(parts))
        if c.get("path"):
            md.append(f"**Folder**: `{c['path']}`  ·  {'▣ downloaded' if c.get('downloaded') else '▢ not downloaded (press d)'}")
        if files:
            md.append("**Files** (→ work/): " + ", ".join(f"`{f}`" for f in files))
        ext = store.extract_links(c.get("description"))
        if ext:
            md.append("**External links**: " + ", ".join(f"[{store.classify_link(u)}] {u}" for u in ext))
        md.append(self._rule("DESCRIPTION"))
        md.append("*Loading…*" if loading else (store.clean_desc(c.get("description")) or "*(no description)*"))
        hints = c.get("hints") or []
        if hints:
            hl = []
            for h in hints:
                tag = "free" if h.get("cost", 0) == 0 else f"{h.get('cost')} pts"
                if h.get("content"):
                    hl.append(f"- **#{h.get('id')}** (unlocked, {tag}): {h['content']}")
                else:
                    hl.append(f"- **#{h.get('id')}** (locked, {tag}): press `u` to unlock")
            md.append(self._rule("HINT(S)"))
            md.append("\n".join(hl))
        self.query_one("#detail", Markdown).update("\n\n".join(md))

    # -- search / filter / sort ---------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search = event.value.strip().lower()
            self._rebuild_tree()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_unfocus(self) -> None:
        """Esc: leave an input field, give focus back to the challenge list. On the search
        field specifically, Esc also CANCELS the search (clears the term, shows everything
        again) rather than leaving the filter running."""
        search = self.query_one("#search", Input)
        if self.focused is search and search.value:
            search.value = ""
            self.search = ""
            self._rebuild_tree()
        self.set_focus(self.query_one("#tree", Tree))

    def action_cycle_filter(self) -> None:
        self.filter_mode = FILTERS[(FILTERS.index(self.filter_mode) + 1) % len(FILTERS)]
        self._session_solved.clear()
        self.notify(f"🔍 Filter: {FILTER_LABEL[self.filter_mode]}", timeout=3)
        self._apply_view()

    def action_cycle_sort(self) -> None:
        self.sort_mode = SORTS[(SORTS.index(self.sort_mode) + 1) % len(SORTS)]
        self.notify(f"↕ Sort: {SORT_LABEL[self.sort_mode]}", timeout=3)
        self._apply_view()

    def action_cycle_theme(self) -> None:
        names = list(self.available_themes)
        try:
            i = names.index(self.theme)
        except ValueError:
            i = -1
        self.theme = names[(i + 1) % len(names)]
        self._emit(f"🎨 Theme: {self.theme}", "information", 3)
        self._save_ui_state()

    def _update_legend(self) -> None:
        """Always-visible reminder of the active filter and sort, on the same row as the
        (always-on, borderless) search field, so searching never costs extra terminal height."""
        self.query_one("#legend_icons", Static).update(
            "[cyan]▣[/cyan] [grey42]▢[/grey42] files    "
            "[green]●[/green] [grey42]○[/grey42] solved")
        flt, srt = FILTER_LABEL[self.filter_mode], SORT_LABEL[self.sort_mode]
        mark = "[b yellow]" if self.filter_mode != "all" else "[b]"  # highlight an active filter
        self.query_one("#legend_labels", Static).update(
            f"filter: {mark}{flt}[/]    sort: [b]{srt}[/b]    search:")

    def _apply_view(self) -> None:
        self._update_legend()
        self._rebuild_tree()
        self._save_ui_state()

    def action_refresh(self) -> None:
        self.notify("Refreshing…", timeout=2)
        self._fb_backoff = False  # a manual refresh always gets to retry first bloods too
        self.list_worker()
        self.scoreboard_worker()
        self.me_worker()

    def action_focus_flag(self) -> None:
        try:  # the flag field lives in the Challenges tab: switch to it first
            self.query_one(TabbedContent).active = "tab-chal"
        except Exception:  # noqa: BLE001
            pass
        self.query_one("#flag", Input).focus()

    # -- download / sync ------------------------------------------
    def action_download(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        # single self-healing path: (re)creates desc.txt if needed + completes the files
        self.notify(f"Downloading / updating {self.selected.get('name','?')}…", timeout=2)
        self.download_worker(dict(self.selected))

    def action_sync_all(self) -> None:
        n = len(self.challenges)
        q = (f"Sync all: download all {n} challenges (in parallel)?\n"
             f"This may take a while and use a lot of disk space.")

        def cb(ok):
            if ok:
                self.sync_all_worker()

        self.push_screen(ConfirmScreen(q), cb)

    def _current_category(self) -> str | None:
        """Category under the cursor (category node or challenge), otherwise the selected one's."""
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
            self.notify("Move to a category or a challenge.", severity="warning")
            return
        subset = [c for c in self.challenges if c.get("category") == cat]
        q = (f"Download the {len(subset)} challenges of \"{cat}\" (in parallel)?\n"
             f"Files already present are skipped.")

        def cb(ok):
            if ok:
                self.download_category_worker(cat)

        self.push_screen(ConfirmScreen(q), cb)

    @work(thread=True, exclusive=True, group="syncall")  # same group as "Sync all": no collision
    def download_category_worker(self, cat: str) -> None:
        subset = [c for c in self.challenges if c.get("category") == cat]
        if not subset:
            return
        self._syncing = True
        self.call_from_thread(self._show_progress, True)

        def progress(done, total):
            self.call_from_thread(self._set_progress, done, total)

        self.call_from_thread(self._emit, f"⏳ Downloading \"{cat}\"…", "information", 3)
        try:
            _, events = store.download_subset(
                self.client, self.cfg.base_dir, subset, self.cfg.watch_changes,
                self.cfg.auto_unlock_free_hints, self.cfg.download_workers, progress)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Category download failed: {e}", "error", 6)
            return
        finally:
            self._syncing = False
            self.call_from_thread(self._show_progress, False)
        n = sum(1 for c in subset if c.get("downloaded"))
        self.call_from_thread(self._apply_challenges, self.challenges, events)
        self.call_from_thread(self._emit, f"✅ \"{cat}\": {n}/{len(subset)} downloaded.", "information", 6)

    def action_export_progress(self) -> None:
        if not self.challenges:
            self.notify("Nothing to export.", severity="warning")
            return
        try:
            p = store.write_progress(self.cfg.base_dir, self.challenges, self.cfg.ctf_name)
        except OSError as e:
            self._emit(f"PROGRESS export failed: {e}", "error")
            return
        self._emit(f"📄 Progress exported: {p}", "information", 5)

    # -- copy connection / notes ---------------------------------------
    def action_copy_conn(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        detail = self._detail_cache.get(int(self.selected["id"]), self.selected)
        text = detail.get("connection_info") or self.selected.get("path") or self.selected.get("name", "")
        try:
            self.copy_to_clipboard(text)
            self.notify(f"Copied: {text}", timeout=4)
        except Exception:  # noqa: BLE001
            self.notify(f"Copy this: {text}", timeout=6)

    def action_open_folder(self) -> None:
        """Open the challenge folder in the system file manager."""
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        path = self.selected.get("path")
        if not path or not Path(path).exists():
            self.notify("Folder missing: download first (press d).", severity="warning")
            return
        opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
        try:
            subprocess.Popen([opener, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.notify(f"📂 Opening: {path}", timeout=3)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Cannot open ({e}): {path}", severity="warning", timeout=6)

    def action_edit_notes(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        d = Path(self.selected.get("path") or store.challenge_dir(
            self.cfg.base_dir, self.selected.get("category", ""), self.selected.get("name", "")))
        d.mkdir(parents=True, exist_ok=True)
        notes = d / "notes.md"
        if not notes.exists():
            notes.write_text(
                f"# {self.selected.get('name','?')}\n"
                f"**Category:** {self.selected.get('category','?')} | "
                f"**Points:** {self.selected.get('value','?')}\n\n## Notes\n\n", encoding="utf-8")
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        try:
            with self.suspend():
                subprocess.call([editor, str(notes)])
            self._emit(f"📝 Notes edited: {notes}", "information", 4)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Editor unavailable ({e}). File: {notes}", severity="warning", timeout=6)

    # -- submission ------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":  # Enter: done typing, keep the filter, back to the list
            self.set_focus(self.query_one("#tree", Tree))
            return
        if event.input.id != "flag":
            return
        flag = event.value.strip()
        if not flag:
            return
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        cid = int(self.selected["id"])
        if store.was_attempted(self.cfg.base_dir, cid, flag):
            self._emit(f"⚠️ Flag already tried (incorrect), not resubmitted: {flag}", "warning", 6)
            event.input.value = ""
            return
        self.submit_worker(cid, flag, self.selected.get("path", ""))
        event.input.value = ""

    @work(thread=True, exclusive=True, group="submit")
    def submit_worker(self, cid: int, flag: str, path: str) -> None:
        try:
            status, message = self.client.submit(cid, flag)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Submission failed: {e}", "error")
            return
        if status == "correct":
            store.record_attempt(self.cfg.base_dir, cid, flag, True, path)
            if self.cfg.write_flag_on_solve and path:
                store.write_flag(path, flag)
            self.call_from_thread(self._after_solve, cid, message)
            self.scoreboard_worker()
            self.me_worker()
        elif status == "already_solved":
            self.call_from_thread(self._emit, "Already solved.", "information")
        else:
            store.record_attempt(self.cfg.base_dir, cid, flag, False, path)
            self.call_from_thread(self._emit, f"✘ {status}: {message}".strip(), "warning", 5)

    def _after_solve(self, cid: int, message: str) -> None:
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                c["solved"] = True
        self._session_solved.add(cid)
        self._tree_sig = None  # force a rebuild so the new state shows immediately
        self._emit(f"✔ Correct! {message}".strip(), "information", 6)
        self._apply_challenges(self.challenges)

    # -- hint unlock ---------------------------------------------
    def action_unlock_hint(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        detail = self._detail_cache.get(int(self.selected["id"]), self.selected)
        locked = [h for h in (detail.get("hints") or []) if not h.get("content")]
        if not locked:
            self.notify("No locked hints.", severity="information")
            return
        h = min(locked, key=lambda x: x.get("cost", 0))
        cost = h.get("cost", 0)
        tag = "free" if cost == 0 else f"{cost} pts"
        q = (f"Unlock hint #{h.get('id')} ({tag}) of \"{self.selected.get('name','?')}\"?\n"
             f"⚠️ A paid hint lowers your score.")

        def cb(ok):
            if ok:
                self.unlock_worker(int(h["id"]), int(self.selected["id"]))

        self.push_screen(ConfirmScreen(q), cb)

    @work(thread=True, exclusive=True, group="unlock")
    def unlock_worker(self, hint_id: int, cid: int) -> None:
        try:
            self.client.unlock_hint(hint_id)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Unlock failed: {e}", "error")
            return
        # the unlock itself succeeded (POST /unlocks: cost already deducted server-side) ; the
        # detail refetch below is best-effort display only. A failure here must NEVER be
        # reported as "unlock failed", since the hint genuinely is unlocked at this point
        try:
            detail = self.client.challenge(cid)
        except CTFdError as e:
            self.call_from_thread(
                self._emit,
                f"💡 Hint #{hint_id} unlocked, but couldn't refresh its content ({e}). Press `r`.",
                "warning", 8)
            return
        self._detail_cache[cid] = detail
        self.call_from_thread(self._emit, f"💡 Hint #{hint_id} unlocked.", "information", 6)
        if self.selected and int(self.selected["id"]) == cid:
            self.call_from_thread(self._render_detail, {**self.selected, **detail})


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cfg_path = argv[0] if argv else "config.sh"
    try:
        cfg = Config.load(cfg_path)
    except Exception as e:  # noqa: BLE001
        print(f"[flagship] config: {e}", file=sys.stderr)
        print("Usage: python -m flagship [path/config.sh]", file=sys.stderr)
        return 2
    Flagship(cfg).run()
    return 0
