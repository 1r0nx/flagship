"""Flagship: Textual TUI for a CTFd instance.

Challenges / Scoreboard / Stats / Flags / Notifications / Log tabs; light listing by default, download on
demand (`d`), per category (`C`) or full (`D`, parallel + progress bar); search, sort, filters;
flag submission, hint unlock, copy connection info, external notes, PROGRESS_flagship.md and
FLAGS_flagship.md export; the Notifications tab shows the CTFd platform announcements, while the
Log tab shows Flagship's own events (also toasts + .flagship/notifications.log). The token is never displayed.

Usage: python -m flagship [path/config.sh]
"""

from __future__ import annotations
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import colorsys
import zlib
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
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual import events
from rich.text import Text
from rich.markup import escape
from rich.console import Group
from rich.table import Table
from rich import box
from rich.segment import Segment
from rich.style import Style
from rich.cells import cell_len


def _fmt_when(raw: str | None) -> str:
    """Format a CTFd timestamp for display in the viewer's LOCAL time. CTFd timestamps are
    ISO 8601 in UTC (sometimes without an explicit offset); we parse, assume UTC when the
    offset is missing, then convert to the machine's local zone. Falls back to the raw
    (UTC) value if parsing fails."""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return raw[:19].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


class _CenterRule:
    """A full-width separator line (`────o────`) with a centered 'o'. Being a Rich renderable, it
    is re-measured to the available width on every render, so it spans the pane and re-centers on
    resize without any manual width tracking."""

    def __rich_console__(self, console, options):
        w = max(1, options.max_width)
        left = (w - 1) // 2
        yield Text("─" * left + "o" + "─" * (w - 1 - left), style="dim")

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
        # remember the position as a % of the Challenges area (terminal-size independent), captured
        # here where `total` is reliable, so it survives restarts
        if total:
            self.app._tree_width = f"{max(5, min(95, round(width * 100 / total)))}%"
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
            self.app._tree_width = "42%"
            self.app._save_ui_state()
            self.app._refresh_detail_width()


FILTERS = ("all", "unsolved", "solved", "bookmarked")
FILTER_LABEL = {"all": "all", "unsolved": "unsolved", "solved": "solved", "bookmarked": "bookmarked"}
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


def _md_cell(value) -> str:
    """Escape a value for a Markdown table cell: a literal `|` would start a new column and a
    newline would break the row, so neutralise both (names/categories are arbitrary user text)."""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


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
        md.append(f"| {_md_cell(cat)} | {d['s']}/{d['n']} | {d['pw']}/{d['pt']} |")
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


class SolversScreen(ModalScreen[None]):
    """Who solved a challenge (opened by clicking "N solves" in the detail panel), most recent
    first. Team mode: rows are team names ; your own team's row is starred and names the teammate
    who solved it, via the same per-member breakdown the Stats tab uses."""
    BINDINGS = [("escape", "dismiss", "Close")]
    CSS = """
    SolversScreen { align: center middle; }
    #sbox { width: 70%; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #shead { color: $text-muted; }
    """

    def __init__(self, chal_name: str, solvers: list[dict], team_mode: bool,
                my_team: str | None, my_member: str | None):
        super().__init__()
        self._chal_name = chal_name
        self._solvers = solvers
        self._team_mode = team_mode
        self._my_team = my_team
        self._my_member = my_member

    def compose(self) -> ComposeResult:
        with Vertical(id="sbox"):
            yield Static("Esc to close", id="shead")
            with VerticalScroll():
                yield Markdown(self._build_md(), open_links=False)

    def _build_md(self) -> str:
        who = "team" if self._team_mode else "player"
        md = [f"# {self._chal_name}", "", f"**{len(self._solvers)} {who}(s) solved this**", ""]
        if not self._solvers:
            md.append("*No solves yet, or the CTF has ended (solver list locked by CTFd).*")
            return "\n".join(md)
        header = "Team" if self._team_mode else "Player"
        md += [f"| {header} | When |", "|---|---|"]
        for s in self._solvers:
            name = s.get("name", "?")
            when = _fmt_when(s.get("date"))
            mine = self._team_mode and self._my_team and name == self._my_team
            cell = _md_cell(name)
            label = f"⭐ **{cell}**" + (f" ({_md_cell(self._my_member)})" if mine and self._my_member else "")
            md.append(f"| {label if mine else cell} | {when} |")
        return "\n".join(md)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class AccountSolvesScreen(ModalScreen[None]):
    """Solve history of a scoreboard account (clicking a row): challenge, category, points and the
    exact time, most recent first. In team mode, also the teammate who scored each one."""
    BINDINGS = [("escape", "dismiss", "Close")]
    CSS = """
    AccountSolvesScreen { align: center middle; }
    #abox { width: 80%; height: 85%; border: thick $accent; background: $surface; padding: 1 2; }
    #ahead { color: $text-muted; }
    """

    def __init__(self, name: str, solves: list[dict], team_mode: bool):
        super().__init__()
        self._name = name
        self._solves = solves
        self._team_mode = team_mode

    def compose(self) -> ComposeResult:
        with Vertical(id="abox"):
            yield Static("Esc to close", id="ahead")
            with VerticalScroll():
                yield Markdown(self._build_md(), open_links=False)

    def _build_md(self) -> str:
        total = sum(int(s.get("value") or 0) for s in self._solves)
        md = [f"# {self._name}", "",
              f"**{len(self._solves)} solve(s)** · {total} pts", ""]
        if not self._solves:
            md.append("*No solves to show (or the CTF has ended: CTFd locks this list).*")
            return "\n".join(md)
        member = self._team_mode and any(s.get("member") for s in self._solves)
        head = "| Challenge | Category | Pts" + (" | By | When |" if member else " | When |")
        sep = "|---|---|---" + ("|---|---|" if member else "|---|")
        md += [head, sep]
        for s in self._solves:
            when = _fmt_when(s.get("date"))
            row = f"| {_md_cell(s.get('name','?'))} | {_md_cell(s.get('category',''))} | {s.get('value','')}"
            row += f" | {_md_cell(s.get('member') or '')} | {when} |" if member else f" | {when} |"
            md.append(row)
        return "\n".join(md)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class DoubleClickDataTable(DataTable):
    """DataTable where a single mouse click only *selects* (highlights) a row; opening it
    (posting RowSelected) needs a DOUBLE-click. Keyboard Enter still opens on a single
    press. Used for the scoreboard, where a single click shouldn't open the solve history.

    Note: Textual dispatches `_on_click` for EVERY class in the MRO, so overriding it does
    NOT replace `DataTable._on_click` — both run. On a single click we therefore call
    `event.prevent_default()`, which makes the dispatcher stop before the base handler (it
    breaks on `_no_default_action`), and move the cursor ourselves so the row still selects.
    On a double-click we do nothing and let the base handler post RowSelected as usual."""

    def _on_click(self, event) -> None:
        if getattr(event, "chain", 1) >= 2:
            return  # double-click: let DataTable._on_click run → posts RowSelected → opens
        row = (event.style.meta or {}).get("row")
        if row is None or row < 0 or not self.show_cursor or self.cursor_type == "none":
            return  # header/label/empty click: leave the base behaviour untouched
        # single click on a data row: select only (suppress the base open), move the cursor
        event.prevent_default()
        event.stop()
        self._set_hover_cursor(True)
        self.move_cursor(row=row)


class CategoryTree(Tree):
    """Tree whose highlighted (selected) node is drawn in its category's colour + bold.
    `render_label` re-applies that style AFTER the base cursor style, so it wins over the
    cursor's own colour — the selected challenge then matches its category, like the Flags
    tab. Category of a leaf = its `category`; of a category header = its `_cat`."""

    def render_label(self, node, base_style, style):
        text = super().render_label(node, base_style, style)
        if node is self.cursor_node:
            data = node.data
            cat = (data.get("_cat") or data.get("category")) if isinstance(data, dict) else None
            cat_color = getattr(self.app, "_cat_color", None)
            if cat and cat_color:
                text.stylize(Style(color=cat_color(cat), bold=True))
        return text


class Flagship(App):
    CSS = """
    Header HeaderIcon { display: none; }  /* drop the "⭘" command-palette icon, top-left */
    /* clicking the header normally toggles it to 3 rows (Textual's HeaderTitle.-tall) ;
       pin it to 1 row always, so a stray click never opens a gap above the tabs */
    Header.-tall { height: 1; }
    /* the screen itself must never scroll: every pane that needs it (tree, detail, stats,
       notifications) already has its own scrollbar, so a 1-row layout mismatch must never
       spawn a second, screen-wide scrollbar next to a pane's real one */
    Screen { overflow-y: hidden; layers: base overlay; }
    /* thinner scrollbars everywhere (tree, detail, scoreboard, stats, notifications, member
       popup) : Textual's default is 2 cells tall/wide, 1 is plenty and less visually heavy */
    VerticalScroll, Tree, DataTable {
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    #treecol { width: 42%; }
    #legend_icons { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #legend_row { height: 1; background: $panel; }
    #legend_labels { width: auto; padding: 0 0 0 1; color: $text-muted; }
    #search { border: none; height: 1; width: 1fr; padding: 0 1; background: $panel; }
    /* the challenge list's own horizontal scrollbar, specifically, is hidden: against the
       narrow treecol its track is short, so the thumb reads as a big block even at the
       minimum 1-row thickness ; scrolling right on a long name still works via wheel/keys */
    #tree { height: 1fr; scrollbar-size-horizontal: 0; }
    /* calmer selection/hover: a subtle $boost tint instead of the theme's bright block
       cursor (which forced a white foreground, washing out the per-category colours) */
    #tree > .tree--cursor { background: $boost; }
    #tree:focus > .tree--cursor { color: $text; background: $boost; text-style: bold; }
    #tree > .tree--highlight-line { background: $boost; }
    #rightcol { width: 1fr; }
    #detailwrap { height: 1fr; }
    #detail { padding: 0 1; }
    #flag { height: 3; border: solid $accent; padding: 0 1; }
    #progress { dock: bottom; height: 1; display: none; }
    #scoreboard { height: 1fr; }
    /* hover/selection on the scoreboard = just bold, no highlight bar. Background transparent
       removes the cursor/hover bar; with cursor_foreground_priority="renderable" the cells keep
       their own colours (Gap green/red, your own row), plain cells fall back to $foreground. */
    #scoreboard > .datatable--cursor { background: transparent; color: $foreground; text-style: bold; }
    #scoreboard:focus > .datatable--cursor { background: transparent; color: $foreground; text-style: bold; }
    #scoreboard > .datatable--hover { background: transparent; }
    /* sticky "your rank" line, docked under the scoreboard ; hidden when your row is on screen */
    #me_sticky { dock: bottom; height: 1; display: none; background: $panel; padding: 0 1; }
    /* hide the horizontal scrollbar (long rows still scroll via wheel/keys, just stay truncated) */
    #flags { height: 1fr; scrollbar-size-horizontal: 0; }
    /* subtle cursor so the selected row's category colour (set per-row) stays readable */
    #flags > .datatable--cursor { background: $boost; }
    #flags:focus > .datatable--cursor { background: $boost; }
    #stats { padding: 0 1; }
    #notifs { padding: 0 1; }
    #log { padding: 0 1; }
    /* toasts default to bottom-right, right over the flag field ; top-right stays clear */
    ToastRack { dock: top; align: right top; }
    ToastHolder { align-horizontal: right; }
    /* connection indicator, floated over the far right of the tab row (1 line below the
       Header), so it costs no height and never shifts a tab */
    #connstatus {
        layer: overlay; dock: right; width: auto; height: 1;
        offset: 0 1; padding: 0 1;
        background: $panel; color: $text-muted;
    }
    #connstatus.-online  { color: $success; }
    #connstatus.-offline { color: $warning; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("d", "download", "Download"),
        ("D", "sync_all", "Sync all"),
        ("C", "download_category", "Cat. dl"),
        ("f", "cycle_filter", "Filter"),
        ("o", "cycle_sort", "Sort"),
        ("x", "collapse_expand_all", "Fold/unfold"),
        ("t", "cycle_theme", "Theme"),
        ("l", "toggle_log_full", "Log all/500"),
        ("slash", "focus_search", "Search"),
        ("s", "focus_flag", "Submit"),
        ("u", "unlock_hint", "Hint"),
        ("b", "toggle_bookmark", "Bookmark"),
        ("c", "copy_conn", "Copy"),
        ("w", "open_folder", "Folder"),
        ("e", "edit_notes", "Notes"),
        ("p", "export_progress", "Progress"),
        ("P", "export_flags", "Flags"),
        ("A", "cache_all_solves", "Cache solves"),
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
        self.bookmarked: set[int] = set()  # challenge ids pinned with `b`, persisted
        self._building = False                  # re-entrancy guard while the tree is being rebuilt
        self.me: dict = {}
        self._personal: dict = {}             # individual stats (team mode only)
        self._members: list[dict] = []        # per-member team contribution (team mode)
        self._last_scoreboard: list[dict] = []
        self._my_sb_row: int | None = None   # our own row index in the scoreboard (for the sticky)
        self._my_sb_text: str | None = None
        self._sb_hint_row: int | None = None  # scoreboard row currently showing the "↵ solves" hint
        self._solves_loading = False  # a solve-history modal is being fetched: block a 2nd open (double-click)
        self._detail_cache: dict[int, dict] = {}
        self._fb_cache: dict[int, str] = {}
        self._fb_backoff = False  # True once a whole fb_worker batch failed (e.g. CTF over)
        self.notifications: list[str] = []   # internal activity journal (toasts + .flagship/notifications.log)
        self._log_full = False               # Log tab: False = last 500 (in memory), True = whole file
        self._platform_notifs: list[dict] = []  # CTFd platform announcements, shown in the Notifications tab
        self._notifs_seen: set = set()           # ids already seen (to toast only genuinely new ones)
        self._first_sync = True
        self._online: bool | None = None    # connection state, to log online/offline transitions once
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
                        yield CategoryTree("Challenges", id="tree")
                    yield Splitter("treecol", id="splitter")
                    with Vertical(id="rightcol"):
                        with VerticalScroll(id="detailwrap"):
                            yield Markdown("*Select a challenge on the left.*", id="detail")
                        yield BeamInput(placeholder="Submit 🚩", id="flag", center=True)
            with TabPane("Scoreboard", id="tab-score"):
                yield DoubleClickDataTable(id="scoreboard")
                # sticky one-line reminder of your own rank, shown at the bottom while your real
                # row is scrolled out of view (so the list can start at rank 1)
                yield Static("", id="me_sticky")
            with TabPane("Stats", id="tab-stats"):
                with VerticalScroll():
                    yield Markdown("*Statistics…*", id="stats", open_links=False)
                    # "Progress by category" lives in a Static (not the Markdown) so the
                    # category names and bars can be coloured per category
                    yield Static("", id="progress_bars")
            with TabPane("Flags", id="tab-flags"):
                yield DataTable(id="flags")
            with TabPane("Notifications", id="tab-notifs"):
                with VerticalScroll():
                    yield Static("No notifications.", id="notifs")
            with TabPane("Log", id="tab-log"):
                with VerticalScroll():
                    yield Static("No activity yet.", id="log")
        yield Static("", id="connstatus")
        yield ProgressBar(id="progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tree", Tree).show_root = False
        dt = self.query_one("#scoreboard", DataTable)
        # "Gap" = signed gap of each row vs YOUR score (+ = they lead you,
        # - = you lead them, — on your own row) ; last col = the "↵ solves" hint
        dt.add_columns("#", "Team / Player", "Score", "Gap", "")
        dt.cursor_type = "row"
        # cursor/hover = bold only (no bar, see CSS): keep each cell's own colour on that row
        dt.cursor_foreground_priority = "renderable"
        # keep the sticky "your rank" line in sync as the scoreboard scrolls
        self.watch(dt, "scroll_y", lambda *_: self._update_me_sticky())
        # make the row cursor follow the mouse, so the bold row tracks the pointer (and a
        # double-click opens whatever row is under it) (dt captured: fires on every mouse move)
        self.watch(dt, "hover_coordinate", lambda *_: self._sb_cursor_follow_hover(dt))
        fdt = self.query_one("#flags", DataTable)
        fdt.add_columns("Category", "Challenge", "Points", "Flag")
        fdt.cursor_type = "row"
        # let a cell's own colour win over the cursor's: the selected row is coloured by
        # category (see on_data_table_row_highlighted), every other row stays default
        fdt.cursor_foreground_priority = "renderable"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        try:  # show the persisted activity journal (last 500 lines) in the Log tab across restarts
            self.notifications = self._log_path.read_text(encoding="utf-8").splitlines()[-500:]
        except OSError:
            pass
        self._render_log()
        cached_fb = store.load_json(self.cfg.base_dir, "fb_cache.json", {}) or {}
        self._fb_cache = {int(k): v for k, v in cached_fb.items()}
        self._restore_ui_state()
        self._update_legend()
        th = getattr(self, "_pref_theme", None) or self.cfg.theme
        if th in self.available_themes:
            self.theme = th
        self._update_title()
        # show whatever we last synced right away, flagged Offline, so the UI is never empty while
        # the network workers (which may be slow) are still in flight ; they flip it to Online.
        self._set_conn(False)
        cached = store.load_cache(self.cfg.base_dir)
        if cached:
            self._apply_challenges(cached, [])
        cached_sb = store.load_json(self.cfg.base_dir, "scoreboard_cache.json")
        if cached_sb:
            self._fill_scoreboard(cached_sb)
        cached_me = store.load_json(self.cfg.base_dir, "me_cache.json")
        if cached_me and cached_me.get("me"):
            self._apply_me(cached_me["me"], cached_me.get("personal"), cached_me.get("members"))
        cached_notifs = store.load_json(self.cfg.base_dir, "notifications_cache.json")
        if cached_notifs:
            self._apply_notifs(cached_notifs, initial=True)
        self.list_worker()
        self.scoreboard_worker()
        self.me_worker()
        self.notifications_worker()
        if self.cfg.poll_interval and self.cfg.poll_interval > 0:
            self.set_interval(self.cfg.poll_interval, self.list_worker)
            self.set_interval(self.cfg.poll_interval, self.scoreboard_worker)
            self.set_interval(self.cfg.poll_interval, self.me_worker)
            self.set_interval(self.cfg.poll_interval, self.notifications_worker)
            self.set_interval(self.cfg.poll_interval, self.refresh_cached_solves_worker)

    def on_unmount(self) -> None:
        self._save_ui_state()

    def on_resize(self, event: events.Resize) -> None:
        self._update_me_sticky()  # the visible-rows count changed

    def on_tabbed_content_tab_activated(self, event) -> None:
        # the scoreboard pane has a real size only once shown: re-evaluate the sticky then
        if self.query_one(TabbedContent).active == "tab-score":
            self.call_after_refresh(self._update_me_sticky)


    # -- persistent UI state ------------------------------------
    def _restore_ui_state(self) -> None:
        try:
            s = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.sort_mode = s.get("sort", self.sort_mode)
            self.collapsed_cats = set(s.get("collapsed", []))
            self.bookmarked = set(s.get("bookmarked", []))
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
        """Persisted list width as a % of the Challenges area (independent of terminal size). It is
        captured on drag/double-click into `_tree_width`; a failed live measurement must never wipe
        a previously saved value, so we return the last known width."""
        return getattr(self, "_tree_width", None)

    def _save_ui_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "sort": self.sort_mode,
                "selected": (self.selected or {}).get("id"),
                "collapsed": sorted(self.collapsed_cats),
                "bookmarked": sorted(self.bookmarked),
                "theme": self.theme,
                "tree_width": self._tree_width_str(),
            }), encoding="utf-8")
        except OSError:
            pass

    # -- notifications ---------------------------------------------------
    def _emit(self, msg: str, severity: str = "information", timeout: float = 5) -> None:
        """Flagship's own activity journal: a toast + a line in .flagship/notifications.log.
        It does NOT feed the Notifications tab (that tab shows only the platform feed)."""
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        self.notifications.append(line)
        del self.notifications[:-500]
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        self._render_log()
        self.notify(msg, severity=severity, timeout=timeout)

    def _render_log(self) -> None:
        """Log tab: Flagship's own activity journal (.flagship/notifications.log), newest first.
        Shows the last 500 entries by default, or the whole file when `_log_full` (toggle: `l`)."""
        try:
            w = self.query_one("#log", Static)
        except Exception:  # noqa: BLE001  (widget not mounted yet)
            return
        if self._log_full:
            try:
                lines = self._log_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = list(self.notifications)
        else:
            lines = list(self.notifications)
        # Text() => no markup interpretation (the [YYYY-MM-DD HH:MM:SS] timestamps stay literal)
        w.update(Text("\n".join(reversed(lines)) or "No activity yet."))

    def action_toggle_log_full(self) -> None:
        """Toggle the Log tab between the last 500 entries and the full history (the whole
        .flagship/notifications.log since first use). Switches to the Log tab so it shows."""
        self._log_full = not self._log_full
        try:
            self.query_one(TabbedContent).active = "tab-log"
        except Exception:  # noqa: BLE001  (not mounted yet)
            pass
        self._render_log()

    def _apply_notifs(self, items: list[dict], initial: bool = False) -> None:
        """Store the platform announcements and render them. After the first batch is known,
        a newly appeared announcement also raises a toast (and lands in the internal log)."""
        # newest first, even if a hand-edited/older cache arrived unsorted
        items = sorted(items, key=lambda n: (n.get("date") or "", n.get("id") or 0), reverse=True)
        if not initial and self._notifs_seen:
            for it in items:
                if it.get("id") not in self._notifs_seen:
                    self._emit(f"📢 {it.get('title') or 'Notification'}", "information", 8)
        self._notifs_seen |= {it.get("id") for it in items}
        self._platform_notifs = items
        self._render_notifs()

    def _render_notifs(self) -> None:
        """Notifications tab: the CTFd platform announcements (GET /api/v1/notifications),
        most recent first. Not Flagship's internal journal (that stays in the log file)."""
        try:
            w = self.query_one("#notifs", Static)
        except Exception:  # noqa: BLE001  (widget not mounted yet)
            return
        if not self._platform_notifs:
            w.update(Text("No notifications from the platform."))
            return
        parts = []
        for i, n in enumerate(self._platform_notifs):
            if i:
                parts.append(_CenterRule())  # full-width separator, centered 'o', self-sizing
            block = Text()
            when = _fmt_when(n.get("date"))
            block.append(n.get("title") or "(untitled)", style="bold")
            if when:
                block.append(f"   {when}", style="dim")
            body = (n.get("content") or "").strip()
            if body:
                block.append("\n" + body)  # literal, no markup interpretation
            parts.append(block)
        w.update(Group(*parts))

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
            changed = self.call_from_thread(self._set_conn, False)
            cached = store.load_cache(self.cfg.base_dir)  # offline mode
            if cached:
                if changed:  # log the offline transition once (not on every failed poll)
                    self.call_from_thread(self._emit, f"📴 Offline — showing cached data{hint}", "warning", 7)
                self.call_from_thread(self._apply_challenges, cached, [])
            else:
                self.call_from_thread(self._emit, f"Cannot list challenges: {e}{hint}", "error", 8)
            return
        self.call_from_thread(self._set_conn, True)
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

    def _set_conn(self, online: bool) -> None:
        """Flip the connection indicator on the far right of the tab row. Online = live API ;
        offline = showing the cached list, stamped with the last successful sync time."""
        try:
            w = self.query_one("#connstatus", Static)
        except Exception:  # noqa: BLE001  (not mounted yet)
            return
        if online:
            w.update("● Online")
        else:
            at = store.last_sync_at(self.cfg.base_dir)
            w.update(f"⚠ Offline · sync {at.strftime('%d/%m %H:%M')}" if at
                     else "⚠ Offline · jamais synchronisé")
        w.set_class(online, "-online")
        w.set_class(not online, "-offline")
        changed = self._online is not None and self._online != online
        self._online = online
        if changed and online:  # log the transition back to live data (offline is logged by the
            self._emit("🟢 Online — live data", "information", 3)  # caller, with its diagnostic)
        return changed

    def _render_flags(self) -> None:
        """Update the Flags tab: every solved challenge, showing its flag when a `flag.txt` holds
        one. A teammate's solve (team mode) shows as solved with an "(unknown)" flag until you save
        the flag yourself in the challenge folder."""
        try:
            dt = self.query_one("#flags", DataTable)
        except Exception:  # noqa: BLE001  (widget not mounted yet)
            return
        dt.clear()
        rows = [(c.get("category", "?"), c.get("name", "?"), c.get("value", ""),
                 store.read_flag(c.get("path")) or "(unknown)")
                for c in self.challenges if c.get("solved")]
        rows.sort(key=lambda r: (r[0], r[1]))
        # category per row (same order) so the highlighted row can be coloured by category
        self._flag_rowcats = [r[0] for r in rows]
        self._flags_hl_row = None
        for cat, name, value, flag in rows:
            dt.add_row(cat, name, str(value), flag)

    # Fallback palette (used before any challenge is loaded).
    _CAT_COLORS = [
        "#5fafff", "#ff875f", "#5fd75f", "#d75fff", "#ffd75f", "#ff5f87",
        "#5fd7d7", "#ffaf00", "#87d7ff", "#af87ff", "#87ff5f", "#ff87d7",
        "#00d7af", "#d7d75f", "#ff5fff", "#5f87ff",
    ]

    def _cat_color(self, cat: str) -> str:
        """A distinct colour per category, the SAME in every view (challenges tree and the
        'Progress by category' table). Hues are spread evenly over all current categories
        with a golden-ratio step, so even neighbours (Crypto / Crypto I / CryptoHack) differ.
        The map is cached and rebuilt only when the challenge list changes (invalidated in
        _apply_challenges); a category not in it yet falls back to a fixed palette.

        Called per visible node on every tree repaint, so it stays O(1) after the first build
        (no per-call set/sort)."""
        m = getattr(self, "_cc_map", None)
        if m is None:
            cats = sorted({c.get("category", "?") for c in self.challenges})
            m = {}
            for i, c in enumerate(cats):
                # vivid but still harmonious on dark themes
                r, g, b = colorsys.hsv_to_rgb((i * 0.61803398875) % 1.0, 0.58, 0.98)
                m[c] = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            self._cc_map = m
        return m.get(cat) or self._CAT_COLORS[zlib.crc32(cat.encode()) % len(self._CAT_COLORS)]

    def _render_progress_bars(self, cats: dict[str, dict]) -> None:
        """The single 'Progress by category' section (#progress_bars Static): a bordered
        Rich table with, per category, the progress bar plus Solved / Points / Downloaded.
        The name and bar share the category's colour (same as the challenges tree).
        `cats[cat]` holds 's','n','pw','pt','dl'. A Rich table is needed to colour cells."""
        try:
            w = self.query_one("#progress_bars", Static)
        except Exception:  # noqa: BLE001
            return
        order = sorted(cats)
        if not order:
            w.update("")
            return
        tbl = Table(box=box.SIMPLE_HEAVY, pad_edge=False, header_style="bold")
        tbl.add_column("Category")
        tbl.add_column("Progress")
        tbl.add_column("Solved", justify="right")
        tbl.add_column("Points", justify="right")
        tbl.add_column("Downloaded", justify="right")
        for cat in order:
            d = cats[cat]
            color = self._cat_color(cat)
            filled = round((d["s"] / d["n"]) * 12) if d["n"] else 0
            bar = Text()
            bar.append("█" * filled, style=color)
            bar.append("░" * (12 - filled), style="grey37")  # empty part stays neutral
            # style=color colours the WHOLE row (name, bar, Solved, Points, Downloaded)
            tbl.add_row(Text(cat, style="bold"), bar,
                        f"{d['s']}/{d['n']}", f"{d['pw']}/{d['pt']}", f"{d['dl']}/{d['n']}",
                        style=color)
        w.update(Group(Text("Progress by category", style="bold underline"), Text(), tbl))

    def _render_stats(self) -> None:
        try:
            w = self.query_one("#stats", Markdown)
        except Exception:  # noqa: BLE001
            return
        chs = self.challenges
        if not chs:
            w.update("*No data yet. Run a sync (`r`).*")
            try:
                self.query_one("#progress_bars", Static).update("")
            except Exception:  # noqa: BLE001
                pass
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
        w.update("\n".join(md))
        # single per-category section (bar + Solved/Points/Downloaded), coloured and
        # rendered in its own Static (category colours match the challenges tree)
        self._render_progress_bars(cats)

    def on_markdown_link_clicked(self, event) -> None:
        """Click on a name (href 'member:<id>') in the Stats tab → opens their detail box, or on
        "N solves" (href 'solves:<id>') in the challenge detail panel → opens the solver list.
        Other links (external links in the detail, http) are ignored here."""
        href = getattr(event, "href", "") or ""
        if href.startswith("member:"):
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
        elif href.startswith("solves:"):
            if self._solves_loading:  # a list is already opening: ignore a double-click
                return
            try:
                cid = int(href.split(":", 1)[1])
            except ValueError:
                return
            c = next((x for x in self.challenges if int(x.get("id", -1)) == cid), None)
            self._solves_loading = True
            self.solvers_worker(cid, c.get("name", "?") if c else "?")

    def _restyle_flag_row(self, dt: DataTable, row: int, color: str | None) -> None:
        """Rewrite each cell of a Flags row as plain Text (color=None) or coloured bold
        Text (the category colour). Re-reads the current text so it's idempotent."""
        for col in range(4):
            try:
                cell = dt.get_cell_at(Coordinate(row, col))
            except Exception:  # noqa: BLE001  (row gone after a refill)
                return
            text = cell.plain if isinstance(cell, Text) else str(cell)
            dt.update_cell_at(Coordinate(row, col),
                              Text(text, style=Style(color=color, bold=True)) if color else Text(text))

    def _color_flag_row(self, dt: DataTable, row: int | None) -> None:
        """Colour the highlighted Flags row with its category colour (+ bold); revert the
        previously highlighted one to the default white."""
        cats = getattr(self, "_flag_rowcats", [])
        prev = getattr(self, "_flags_hl_row", None)
        if prev is not None and prev != row and 0 <= prev < len(cats):
            self._restyle_flag_row(dt, prev, None)
        if row is not None and 0 <= row < len(cats):
            self._restyle_flag_row(dt, row, self._cat_color(cats[row]))
        self._flags_hl_row = row

    def on_data_table_row_highlighted(self, event) -> None:
        """Flags tab: colour the highlighted row by its category. Scoreboard: move the
        "↵ solves" affordance onto the row under the cursor (only that row shows it)."""
        tid = getattr(event.data_table, "id", None)
        if tid == "flags":
            self._color_flag_row(event.data_table, event.cursor_row)
            return
        if tid != "scoreboard":
            return
        dt = event.data_table
        new = event.cursor_row
        if self._sb_hint_row is not None and self._sb_hint_row != new:
            try:
                dt.update_cell_at(Coordinate(self._sb_hint_row, 4), "")
            except Exception:  # noqa: BLE001  (row gone after a refill)
                pass
        try:
            dt.update_cell_at(Coordinate(new, 4), Text("↵ solves", style="dim"))
            self._sb_hint_row = new
        except Exception:  # noqa: BLE001
            self._sb_hint_row = None

    def _sb_cursor_follow_hover(self, dt: DataTable) -> None:
        """Move the scoreboard's row cursor onto the row under the mouse, so the highlight bar
        follows the pointer instead of leaving a fixed bar plus a separate hover highlight. Only
        when the Scoreboard tab is active ; `scroll=False` so hovering never scrolls the view, and
        the hint column moves along via the normal row_highlighted event."""
        try:
            if self.query_one(TabbedContent).active != "tab-score":
                return
        except Exception:  # noqa: BLE001  (not mounted yet)
            return
        row = dt.hover_row
        if row is None or not (0 <= row < dt.row_count) or row == dt.cursor_row:
            return
        try:
            dt.move_cursor(row=row, scroll=False)
        except Exception:  # noqa: BLE001
            pass

    def on_data_table_row_selected(self, event) -> None:
        """Double-click / Enter on a Scoreboard row → open that account's solve history (a single
        click only selects the row; see DoubleClickDataTable). Other tables are ignored here."""
        if getattr(event.data_table, "id", None) != "scoreboard":
            return
        if self._solves_loading:  # a history is already opening: ignore a double-click / double-Enter
            return
        i = event.cursor_row
        if i is None or not (0 <= i < len(self._last_scoreboard)):
            return
        row = self._last_scoreboard[i]
        aid = row.get("account_id")
        if aid is None:  # old cache without account ids: a refresh (`r`) repopulates them
            self.notify("Re-sync (r) to enable solve history for this row.", severity="warning", timeout=4)
            return
        # CTFd exposes account_type ("user"/"team"); fall back to the URL/mode if absent
        atype = row.get("account_type") or ""
        url = row.get("account_url") or ""
        team = atype == "team" or url.startswith("/teams") or bool((self.me or {}).get("team"))
        self._solves_loading = True
        self.notify(f"Loading {row.get('name','?')}'s solves…", timeout=2)
        self.account_solves_worker(int(aid), team, row.get("name", "?"))

    @work(thread=True, exclusive=True, group="acctsolves")
    def account_solves_worker(self, account_id: int, team: bool, name: str) -> None:
        # cache every consulted history (per account) so it stays available offline / after the CTF
        try:
            solves = self.client.account_solves(account_id, team)
            cache = store.load_json(self.cfg.base_dir, "solves_cache.json", {}) or {}
            key = str(account_id)
            if solves is not None:
                cache[key] = solves
                store.save_json(self.cfg.base_dir, "solves_cache.json", cache)
            else:
                solves = cache.get(key, [])  # unreachable: fall back to the last known
            self.call_from_thread(self.push_screen, AccountSolvesScreen(name, solves, team))
        finally:
            self._solves_loading = False  # release the guard once opened (or on failure)

    @work(thread=True, exclusive=True, group="solvescache")
    def refresh_cached_solves_worker(self) -> None:
        """Each poll, re-fetch and re-cache ONLY the solve histories / solver lists already viewed
        (bounded by what you opened), keeping them fresh without fetching every account on the
        scoreboard (which would hammer the API and trip rate limits)."""
        team = bool((self.me or {}).get("team"))
        sc = store.load_json(self.cfg.base_dir, "solves_cache.json", {}) or {}
        if sc:
            changed = False
            for key in list(sc.keys()):
                try:
                    r = self.client.account_solves(int(key), team)
                except (ValueError, CTFdError):
                    r = None
                if r is not None:
                    sc[key] = r
                    changed = True
            if changed:
                store.save_json(self.cfg.base_dir, "solves_cache.json", sc)
        vc = store.load_json(self.cfg.base_dir, "solvers_cache.json", {}) or {}
        if vc:
            changed = False
            for key in list(vc.keys()):
                try:
                    r = self.client.challenge_solvers(int(key))
                except (ValueError, CTFdError):
                    r = None
                if r is not None:
                    vc[key] = r
                    changed = True
            if changed:
                store.save_json(self.cfg.base_dir, "solvers_cache.json", vc)

    @work(thread=True, exclusive=True, group="preload")
    def preload_all_solves_worker(self) -> None:
        """One-shot: fetch and cache the solve history of EVERY scoreboard account (bounded
        parallelism), so the whole board is browsable offline / after the CTF. Triggered on demand
        (`A`), never on the poll, to avoid hammering the API every cycle."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        team = bool((self.me or {}).get("team"))
        accounts = [r.get("account_id") for r in self._last_scoreboard
                    if r.get("account_id") is not None]
        if not accounts:
            self.call_from_thread(self._emit, "No scoreboard accounts to cache (sync first).", "warning", 5)
            return
        cache = store.load_json(self.cfg.base_dir, "solves_cache.json", {}) or {}
        self.call_from_thread(self._emit, f"⏳ Caching solve history of {len(accounts)} accounts…", "information", 4)
        ok = fail = 0
        def task(aid):
            return aid, self.client.account_solves(aid, team)
        with ThreadPoolExecutor(max_workers=self.cfg.download_workers) as ex:
            for fut in as_completed([ex.submit(task, a) for a in accounts]):
                aid, res = fut.result()
                if res is not None:
                    cache[str(aid)] = res; ok += 1
                else:
                    fail += 1
        store.save_json(self.cfg.base_dir, "solves_cache.json", cache)
        msg = f"✅ Cached {ok} account(s)' solve history" + (f" · {fail} failed (rate limit? press A again)" if fail else "")
        self.call_from_thread(self._emit, msg, "warning" if fail else "information", 7)

    @work(thread=True, exclusive=True, group="solvers")
    def solvers_worker(self, cid: int, name: str) -> None:
        # cache every consulted solver list (per challenge) for offline / post-CTF viewing
        try:
            solvers = self.client.challenge_solvers(cid)
            cache = store.load_json(self.cfg.base_dir, "solvers_cache.json", {}) or {}
            key = str(cid)
            if solvers is not None:
                cache[key] = solvers
                store.save_json(self.cfg.base_dir, "solvers_cache.json", cache)
            else:
                solvers = cache.get(key, [])  # unreachable: fall back to the last known
            team_mode = bool(self.me.get("team"))
            self.call_from_thread(self.push_screen, SolversScreen(
                name, solvers, team_mode, self.me.get("name") if team_mode else None,
                self._solver_name(cid) if team_mode else None))
        finally:
            self._solves_loading = False  # release the guard once opened (or on failure)

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
        # _apply_challenges refreshes the tree (left) but not the detail panel (right):
        # re-render it so the "downloaded / folder" line updates at once for this challenge
        if self.selected and int(self.selected.get("id", -1)) == cid:
            self.selected["downloaded"] = downloaded
            self.selected["path"] = path
            self._render_detail({**self.selected, **self._detail_cache.get(cid, {})})

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

    @work(thread=True, exclusive=True, group="notifs")
    def notifications_worker(self) -> None:
        items = self.client.notifications()
        if items is not None:  # reachable (possibly an empty list = no announcements yet)
            store.save_json(self.cfg.base_dir, "notifications_cache.json", items)
            self.call_from_thread(self._apply_notifs, items)
        else:  # offline / endpoint unavailable: keep showing the last known feed
            cached = store.load_json(self.cfg.base_dir, "notifications_cache.json")
            if cached:
                self.call_from_thread(self._apply_notifs, cached)

    @staticmethod
    def _score_diff(row_score, my_score, is_me: bool) -> str:
        """Signed gap of a scoreboard row vs OUR score, for the "Gap" column:
        "—" on our own row, "+N" when they lead us, "-N" when we lead them, "0" on a tie.
        Empty string if we have no reference score (not on the board yet)."""
        if is_me:
            return "—"
        if my_score is None:
            return ""
        try:
            d = int(row_score) - int(my_score)
        except (TypeError, ValueError):
            return ""
        return f"+{d}" if d > 0 else str(d)

    def _fill_scoreboard(self, rows: list[dict]) -> None:
        self._last_scoreboard = rows
        dt = self.query_one("#scoreboard", DataTable)
        dt.clear()
        self._sb_hint_row = None  # rows were cleared; the hint is reapplied to the cursor row below
        me_name = (self.me or {}).get("name")
        my_row = None
        # our own score, used as the reference for the "Gap" column. Prefer the value
        # from the board itself (same source as everyone else) ; fall back to the cached profile if
        # we're not on the board yet.
        my_score = next((r["score"] for r in rows if me_name and r["name"] == me_name), None)
        if my_score is None:
            my_score = (self.me or {}).get("score")
        # "$warning" is a Textual CSS variable, meaningless to Rich's Text(style=...): resolve it
        # to the active theme's actual color first, or the highlight silently does nothing
        warning = self._sb_accent()
        # per-theme colours for the "Gap" cell: green when we lead a row, red when it
        # leads us. Resolved from the theme (like `warning`) so every theme stays readable.
        lead_c = self._theme_color("success", "green")   # we're ahead  (negative diff)
        behind_c = self._theme_color("error", "red")     # we're behind (positive diff)
        for i, r in enumerate(rows):
            is_me = bool(me_name) and r["name"] == me_name
            st = f"bold {warning}" if is_me else ""
            diff_txt = self._score_diff(r["score"], my_score, is_me)
            diff_st = self._diff_style(diff_txt, is_me, st, lead_c, behind_c)
            dt.add_row(
                Text(str(r["pos"]), style=st),
                Text(str(r["name"]), style=st),
                Text(str(r["score"]), style=st),
                Text(diff_txt, style=diff_st),
                "",  # hint cell, filled only on the cursor row
            )
            if is_me:
                my_row = i
        # start the view at rank 1 (don't scroll to our own row) ; our rank stays reachable via
        # the sticky bottom line below
        self._my_sb_row = my_row
        self._my_sb_text = None
        if my_row is not None:
            r = rows[my_row]
            self._my_sb_text = f"{r['pos']}   {r['name']}   {r['score']}"
        try:
            dt.scroll_to(y=0, animate=False)
            dt.move_cursor(row=0)
            if rows:  # show the "↵ solves" hint on the top row right away
                dt.update_cell_at(Coordinate(0, 4), Text("↵ solves", style="dim"))
                self._sb_hint_row = 0
        except Exception:  # noqa: BLE001
            pass
        self._update_me_sticky()

    def _update_me_sticky(self) -> None:
        """Show a truncated one-line reminder of our own rank while our real row is scrolled out of
        view: at the bottom when we haven't reached it yet, at the top (under the header) once we've
        scrolled past it. Hidden while our row is on screen."""
        try:
            sticky = self.query_one("#me_sticky", Static)
            dt = self.query_one("#scoreboard", DataTable)
        except Exception:  # noqa: BLE001  (not mounted yet)
            return
        my = getattr(self, "_my_sb_row", None)
        if my is None or not getattr(self, "_my_sb_text", None):
            sticky.display = False
            return
        vis = max(0, dt.size.height - 1)        # visible data rows (minus the header row)
        # Default to HIDDEN whenever we can't prove our row is off-screen:
        #  - vis <= 0: the table isn't sized yet (e.g. filled from cache before the tab is shown) —
        #    showing here is what left the sticky stuck on screen; a later resize/scroll re-runs this.
        #  - max_scroll_y <= 0: the whole board fits, nothing to scroll, so our row is always visible.
        if vis <= 0 or dt.max_scroll_y <= 0:
            sticky.display = False
            return
        top = int(dt.scroll_y)
        if top <= my <= top + vis - 1:
            sticky.display = False
            return
        warning = self._sb_accent()
        sticky.update(Text(self._my_sb_text, style=f"bold {warning}"))
        # off-screen: put the reminder on the side our row actually is, so it's coherent.
        if my < top:
            # scrolled PAST our row (it's above the view): float the reminder just UNDER the
            # table header (overlay layer + a 1-row top margin for the header), so it sits below
            # the "# / Team / Score" header instead of being pushed above it by a top dock.
            sticky.styles.layer = "overlay"
            sticky.styles.dock = "top"
            sticky.styles.margin = (1, 0, 0, 0)
        else:
            # haven't reached our row yet (it's below the view): reserve a line at the bottom.
            sticky.styles.layer = "base"
            sticky.styles.dock = "bottom"
            sticky.styles.margin = 0
        sticky.display = True

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
    def _tree_sig_of(self, challenges: list[dict]) -> tuple:
        """Signature of everything the tree shows (id, solved, downloaded, solves, value, name,
        category). A rebuild only happens when this changes, so the cursor never jumps on a poll
        that brought nothing new."""
        return tuple((int(c.get("id", 0)), bool(c.get("solved")), bool(c.get("downloaded")),
                      c.get("solves"), c.get("value"), c.get("name"), c.get("category"))
                     for c in sorted(challenges, key=lambda x: int(x.get("id", 0))))

    def _refresh_tree_if_changed(self) -> None:
        sig = self._tree_sig_of(self.challenges)
        if sig != self._tree_sig:
            self._tree_sig = sig
            self._rebuild_tree()

    def _merge_detail_into_list(self, cid: int, detail: dict) -> None:
        """A freshly fetched detail carries a newer solve count (and dynamic point value) than the
        last list poll: fold those back into the list entry so the tree matches the detail panel
        at once, instead of lagging until the next poll."""
        changed = False
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                for k in ("solves", "value"):
                    v = detail.get(k)
                    if v is not None and c.get(k) != v:
                        c[k] = v
                        changed = True
                break
        if changed:
            self._refresh_tree_if_changed()
            self._render_stats()
            self._render_flags()

    def _apply_challenges(self, challenges: list[dict], events: list[dict] | None = None) -> None:
        prev_ids = {int(c["id"]) for c in self.challenges}
        prev_solved = {int(c["id"]) for c in self.challenges if c.get("solved")}
        for c in challenges:
            if c.get("_detail"):
                self._detail_cache[int(c["id"])] = c["_detail"]
        self.challenges = challenges
        self._cc_map = None  # categories may have changed: rebuild the colour map lazily
        if not self._first_sync:  # newly solved: keep it visible under the "unsolved" filter
            self._session_solved |= {int(c["id"]) for c in challenges
                                     if c.get("solved") and int(c["id"]) not in prev_solved}
        # only rebuild the tree if the display really changes (otherwise the cursor would jump on poll)
        self._refresh_tree_if_changed()
        self._render_stats()
        self._render_flags()
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
        """Status filter (`f`): all / unsolved / solved / bookmarked."""
        if self.filter_mode == "unsolved":
            return not c.get("solved") or int(c.get("id", -1)) in self._session_solved
        if self.filter_mode == "solved":
            return bool(c.get("solved"))
        if self.filter_mode == "bookmarked":
            return int(c.get("id", -1)) in self.bookmarked
        return True

    def _matches_search(self, c: dict) -> bool:
        """Name, category, and the description if its detail happens to be cached already
        (never fetched just for this: typing in the search box must never trigger network
        calls)."""
        if not self.search:
            return True
        cid = int(c.get("id", -1))
        desc = self._detail_cache.get(cid, {}).get("description") or ""
        haystack = f"{c.get('name', '')} {c.get('category', '')} {desc}".lower()
        return self.search in haystack

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        self._building = True
        try:
            tree.clear()
            cats: dict[str, list[dict]] = {}
            for c in self.challenges:
                if not self._passes_filter(c):
                    continue
                if not self._matches_search(c):
                    continue
                cats.setdefault(c.get("category", "?"), []).append(c)
            for cat in sorted(cats):
                items = sorted(cats[cat], key=self._sort_key)
                n_solved = sum(1 for i in items if i.get("solved"))
                # keep the remembered collapsed/expanded state for this category
                node = tree.root.add(
                    f"[b {self._cat_color(cat)}]{escape(cat)}[/] ({n_solved}/{len(items)})",
                    data={"_cat": cat}, expand=cat not in self.collapsed_cats)
                for c in items:
                    # column 1 = downloaded (square/box) · column 2 = solved (circle)
                    mark = "[b green]●[/b green]" if c.get("solved") else "[grey42]○[/grey42]"
                    dlm = "[b cyan]▣[/b cyan]" if c.get("downloaded") else "[grey42]▢[/grey42]"
                    star = "[yellow]★[/yellow] " if int(c.get("id", -1)) in self.bookmarked else ""
                    slv = c.get("solves")
                    stail = f"   [dim]{c.get('value','')}pt · {slv} solves[/dim]" if slv is not None else f"   [dim]{c.get('value','')}pt[/dim]"
                    node.add_leaf(f"{dlm} {mark}  {star}{c.get('name','?')}{stail}", data=c)
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
        # the detail's solve count / dynamic value is fresher than the last list poll: push it
        # back into the list so the tree matches the detail panel at once (not only on next poll)
        self.call_from_thread(self._merge_detail_into_list, cid, detail)
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

    def _solver_name(self, cid: int) -> str | None:
        """Team mode only: which teammate's own solve this challenge is, from the per-member
        breakdown already fetched for the Stats tab (no extra API call). None in solo mode, or
        if that data hasn't loaded yet."""
        for m in self._members:
            if cid in m.get("solved_ids", []):
                return m.get("name")
        return None

    def _rel_path(self, p) -> str:
        """Display a challenge folder relative to the config.sh directory, e.g.
        `./MonCTF/CHALLENGES/<Category>/<Challenge>`; falls back to the absolute path if it lies
        outside that directory."""
        try:
            return "./" + str(Path(p).resolve().relative_to(self.cfg.config_dir))
        except (ValueError, OSError, TypeError):
            return str(p)

    def _chal_label(self, cid) -> str:
        """Readable 'Name [Category]' for a challenge id, so a log line always says WHICH challenge
        it is about. Falls back to '#<id>' if the challenge isn't in the current list."""
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return "?"
        c = next((x for x in self.challenges if int(x.get("id", -1)) == cid), None)
        return f"{c.get('name','?')} [{c.get('category','?')}]" if c else f"#{cid}"

    def _render_detail(self, c: dict, loading: bool = False) -> None:
        cid = int(c.get("id", -1))
        # the list is the single source of truth for the volatile fields (the poll keeps them
        # fresh, and detail fetches are merged back into it): let it win over a cached detail so
        # the panel never shows a solve count the tree has already moved past.
        live = next((x for x in self.challenges if int(x.get("id", -1)) == cid), None)
        if live:
            c = {**c, **{k: live[k] for k in ("solves", "value", "solved", "downloaded")
                         if k in live}}
        files = [Path(f.split("?")[0]).name for f in (c.get("files") or [])]
        status = "● solved" if c.get("solved") else "○ unsolved"
        tried = store.load_attempts(self.cfg.base_dir).get(str(cid), [])  # our own rejected flags
        meta = f"**Category**: {c.get('category','?')}  ·  **Points**: {c.get('value','?')}  ·  **{status}**"
        if c.get("decay") is not None:  # dynamic-value challenge: points drop as more solve it
            meta += f"  (dynamic: {c.get('initial','?')} → {c.get('minimum','?')})"
        if c.get("solves") is not None:
            # clickable (href 'solves:<id>') intercepted by on_markdown_link_clicked, same pattern
            # as the member links in the Stats tab
            meta += f"  ·  [{c['solves']} solves](solves:{cid})"
        if c.get("max_attempts"):  # 0/None = unlimited, nothing to show then
            # CTFd's own "attempts" count (server-side, authoritative) when the detail has
            # loaded ; before that, or if the server omits it, our own rejection log is a stand-in
            used = c.get("attempts")
            if used is None:
                used = len(tried)
            left = max(0, int(c["max_attempts"]) - int(used))
            meta += f"  ·  **Attempts**: {used}/{c['max_attempts']} ({left} left)"
        fb = self._fb_cache.get(cid)
        md = [f"# {c.get('name','?')}", self._rule("INFO"), meta]
        if c.get("solved") and self.me.get("team"):
            solver = self._solver_name(cid)
            if solver:
                md.append(f"👤 **Solved by**: {solver}")
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
            md.append(f"**Folder**: `{self._rel_path(c['path'])}`  ·  {'▣ downloaded' if c.get('downloaded') else '▢ not downloaded (press d)'}")
        if files:
            md.append("**Files** (→ work/): " + ", ".join(f"`{f}`" for f in files))
        ext = store.extract_links(c.get("description"))
        if ext:
            md.append("**External links**: " + ", ".join(f"[{store.classify_link(u)}] {u}" for u in ext))
        if tried:
            md.append("**Tried & rejected**: " + ", ".join(f"`{f}`" for f in tried))
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

    def action_collapse_expand_all(self) -> None:
        """One key, both directions: every category expanded -> collapse them all ; otherwise
        expand them all back. `node.expand()`/`collapse()` post the same Tree messages a manual
        click would, so `collapsed_cats` and the saved state stay in sync for free."""
        cats = list(self.query_one("#tree", Tree).root.children)
        if not cats:
            return
        if all(not node.is_collapsed for node in cats):
            for node in cats:
                node.collapse()
            self.notify("📁 Collapsed all categories", timeout=2)
        else:
            for node in cats:
                node.expand()
            self.notify("📂 Expanded all categories", timeout=2)

    def action_cycle_theme(self) -> None:
        names = list(self.available_themes)
        try:
            i = names.index(self.theme)
        except ValueError:
            i = -1
        self.theme = names[(i + 1) % len(names)]
        self._emit(f"🎨 Theme: {self.theme}", "information", 3)
        # theme-dependent colours (our row accent + the green/red diff cells) are resolved per
        # theme: re-apply them in place, and refresh the sticky, after switching theme
        self._recolor_sb_theme()
        self._update_me_sticky()
        self._save_ui_state()

    def _sb_accent(self) -> str:
        """Colour used to highlight our own scoreboard row. The DataTable silently drops
        ANSI-named colours (e.g. `ansi_yellow` renders as the terminal default), which is why
        the highlight vanished under the `ansi-dark`/`ansi-light` themes. Fall back to the plain
        standard-colour name (`ansi_yellow` -> `yellow`), which renders in every theme."""
        c = self.get_css_variables().get("warning", "yellow")
        return c[5:] if c.startswith("ansi_") else c

    def _theme_color(self, var: str, fallback: str) -> str:
        """Resolve a theme semantic colour (e.g. `success`, `error`) to a name the DataTable can
        render, with the same `ansi_*` -> plain-name fix as `_sb_accent`. Used to colour the
        "Gap" cell (green when we lead, red when we're behind) per theme."""
        c = self.get_css_variables().get(var, fallback)
        return c[5:] if c.startswith("ansi_") else c

    @staticmethod
    def _diff_style(diff_txt: str, is_me: bool, accent: str, lead_c: str, behind_c: str) -> str:
        """Style for a "Gap" cell (single source of truth, used both when filling and
        when recolouring): our own row keeps the accent, "+N" (they lead us) is red, "-N" (we lead
        them) is green, "0"/"" stays neutral."""
        if is_me:
            return accent
        if diff_txt.startswith("+"):
            return behind_c
        if diff_txt.startswith("-"):
            return lead_c
        return ""

    def _recolor_sb_theme(self) -> None:
        """Re-apply the theme-dependent colours to the scoreboard in place (no refill, so the scroll
        position is kept). Used after a theme change: the accent on our own row AND the green/red of
        every "Gap" cell depend on the active theme."""
        rows = self._last_scoreboard
        if not rows:
            return
        try:
            dt = self.query_one("#scoreboard", DataTable)
        except Exception:  # noqa: BLE001
            return
        warning = self._sb_accent()
        lead_c = self._theme_color("success", "green")
        behind_c = self._theme_color("error", "red")
        me_name = (self.me or {}).get("name")
        my_score = next((r["score"] for r in rows if me_name and r["name"] == me_name), None)
        if my_score is None:
            my_score = (self.me or {}).get("score")
        my = getattr(self, "_my_sb_row", None)
        st = f"bold {warning}"
        for i, r in enumerate(rows):
            is_me = i == my
            try:
                diff_txt = self._score_diff(r["score"], my_score, is_me)
                diff_st = self._diff_style(diff_txt, is_me, st, lead_c, behind_c)
                if is_me:
                    # restore the accent on our whole row (pos/name/score + the "—" cell)
                    dt.update_cell_at(Coordinate(i, 0), Text(str(r["pos"]), style=st))
                    dt.update_cell_at(Coordinate(i, 1), Text(str(r["name"]), style=st))
                    dt.update_cell_at(Coordinate(i, 2), Text(str(r["score"]), style=st))
                dt.update_cell_at(Coordinate(i, 3), Text(diff_txt, style=diff_st))
            except Exception:  # noqa: BLE001  (row gone after a refill)
                pass

    def _update_legend(self) -> None:
        """Always-visible reminder of the active filter and sort, on the same row as the
        (always-on, borderless) search field, so searching never costs extra terminal height."""
        self.query_one("#legend_icons", Static).update(
            "[cyan]▣[/cyan] [grey42]▢[/grey42] files    "
            "[green]●[/green] [grey42]○[/grey42] solved    "
            "[yellow]★[/yellow] bookmarked (`b`)")
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
        self.notifications_worker()
        self.refresh_cached_solves_worker()

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
        self._emit(f"📄 Progress exported: {self._rel_path(p)}", "information", 5)

    def action_export_flags(self) -> None:
        if not self.challenges:
            self.notify("Nothing to export.", severity="warning")
            return
        try:
            p = store.write_flags(self.cfg.base_dir, self.challenges, self.cfg.ctf_name)
        except OSError as e:
            self._emit(f"Flags export failed: {e}", "error")
            return
        self._emit(f"🚩 Flags exported: {self._rel_path(p)}", "information", 5)

    def action_cache_all_solves(self) -> None:
        n = len([r for r in self._last_scoreboard if r.get("account_id") is not None])
        if not n:
            self.notify("Scoreboard not loaded yet (sync with r).", severity="warning")
            return
        def cb(ok: bool) -> None:
            if ok:
                self.preload_all_solves_worker()
        self.push_screen(ConfirmScreen(
            f"Cache the solve history of all {n} scoreboard accounts?\n"
            f"One request per account — do it before the CTF ends (CTFd locks it afterwards)."), cb)

    # -- copy connection / notes ---------------------------------------
    def _copy_to_clipboard(self, text: str) -> str | None:
        """Copy text to the system clipboard. Return the method used, or None.

        Tries real clipboard tools first: under tmux (and often over SSH) the
        OSC 52 escape used by Textual's copy_to_clipboard is swallowed and never
        reaches the terminal, so the copy silently fails. A CLI tool avoids that.
        OSC 52 stays as a last resort for remote terminals with no such tool.
        """
        data = text.encode("utf-8", "replace")
        candidates = (
            ["wl-copy"],                               # Wayland
            ["xclip", "-selection", "clipboard", "-in"],  # X11
            ["xsel", "--clipboard", "--input"],        # X11
            ["pbcopy"],                                # macOS
            ["clip.exe"],                              # WSL / Windows
        )
        for argv in candidates:
            if not shutil.which(argv[0]):
                continue
            try:
                subprocess.run(argv, input=data, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return argv[0]
            except Exception:  # noqa: BLE001
                continue
        try:
            self.copy_to_clipboard(text)  # terminal OSC 52, best effort
            return "osc52"
        except Exception:  # noqa: BLE001
            return None

    def action_copy_conn(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        detail = self._detail_cache.get(int(self.selected["id"]), self.selected)
        text = detail.get("connection_info") or self.selected.get("path") or self.selected.get("name", "")
        if not text:
            self.notify("Nothing to copy for this challenge.", severity="warning")
            return
        method = self._copy_to_clipboard(text)
        if method == "osc52":
            self.notify(f"Sent via terminal (OSC 52): {text}\n"
                        f"If your clipboard stays empty (tmux/SSH), copy manually.",
                        timeout=7)
        elif method:
            self.notify(f"Copied: {text}", timeout=4)
        else:
            self.notify(f"Copy this manually: {text}", severity="warning", timeout=8)

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
            self.notify(f"📂 Opening: {self._rel_path(path)}", timeout=3)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Cannot open ({e}): {self._rel_path(path)}", severity="warning", timeout=6)

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
        # EDITOR from config.sh wins (the explicit choice for Flagship), then $EDITOR/$VISUAL, then nano.
        # A full command line is allowed (e.g. "subl -w", "code -w") and split into args.
        editor = self.cfg.editor or os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        try:
            cmd = shlex.split(editor) + [str(notes)]
        except ValueError:  # malformed quoting in EDITOR: fall back to the raw string
            cmd = [editor, str(notes)]
        try:
            with self.suspend():
                subprocess.call(cmd)
            self._emit(f"📝 Notes edited: {self._rel_path(notes)}", "information", 4)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Editor unavailable ({e}). File: {self._rel_path(notes)}", severity="warning", timeout=6)

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
        label = self._chal_label(cid)
        path = self.selected.get("path", "")
        # already rejected once: no confirmation window, just the "already tried" message
        if store.was_attempted(self.cfg.base_dir, cid, flag):
            self._emit(f"⚠️ {label}: flag already tried (incorrect), not resubmitted: {flag}", "warning", 6)
            event.input.value = ""
            return
        # limited-attempts challenge: confirm before spending one. max_attempts lives on the
        # loaded detail; merge it over the list row (which may not carry it yet).
        det = {**self.selected, **(self._detail_cache.get(cid) or {})}
        max_att = det.get("max_attempts")
        if max_att:  # 0 / None = unlimited -> submit straight away (no window)
            used = det.get("attempts")  # CTFd's authoritative count when the detail has loaded
            if used is None:            # fallback: our own local rejection log
                used = len(store.load_attempts(self.cfg.base_dir).get(str(cid), []))
            left = max(0, int(max_att) - int(used))
            name = det.get("name") or label
            inp = event.input
            def _confirm_submit(ok: bool, cid=cid, flag=flag, path=path, label=label, inp=inp) -> None:
                if ok:
                    inp.value = ""
                    self.submit_worker(cid, flag, path, label)
            self.push_screen(
                ConfirmScreen(
                    f"Submit this flag to {escape(name)}?\n"
                    f"{escape(flag)}\n\n"
                    f"Limited attempts: {used}/{max_att} used, {left} left — this uses one."),
                _confirm_submit)
            return
        self.submit_worker(cid, flag, path, label)
        event.input.value = ""

    @work(thread=True, exclusive=True, group="submit")
    def submit_worker(self, cid: int, flag: str, path: str, label: str = "") -> None:
        label = label or f"#{cid}"
        try:
            status, message = self.client.submit(cid, flag)
        except CTFdError as e:
            self.call_from_thread(self._emit, f"Submission failed ({label}): {e}", "error")
            return
        if status == "correct":
            store.record_attempt(self.cfg.base_dir, cid, flag, True, path)
            if self.cfg.write_flag_on_solve and path:
                store.write_flag(path, flag)
            # _after_solve runs on the UI thread and also relaunches the scoreboard/profile
            # workers from there (never start a worker from this background thread)
            self.call_from_thread(self._after_solve, cid, message)
        elif status == "already_solved":
            self.call_from_thread(self._emit, f"Already solved: {label}", "information")
        elif status == "incorrect":
            store.record_attempt(self.cfg.base_dir, cid, flag, False, path)
            # _after_reject runs on the UI thread: refresh the detail panel at once
            # (Tried & rejected, Attempts count) instead of waiting for the next poll
            self.call_from_thread(self._after_reject, cid, status, message)
        else:
            # paused / ratelimited / unknown: NOT a wrong flag — do not record it (so it is never
            # blocked from resubmission by the attempts guard), just surface what the server said
            self.call_from_thread(self._emit, f"⚠ {label}: {status}: {message}".strip(), "warning", 6)

    def _after_solve(self, cid: int, message: str) -> None:
        name, cat = "?", "?"
        for c in self.challenges:
            if int(c.get("id", -1)) == cid:
                c["solved"] = True
                name, cat = c.get("name", "?"), c.get("category", "?")
                # optimistic +1 so the solve count moves at once (tree tail + detail panel),
                # instead of staying stale until the next poll ; the resync below makes it
                # authoritative (and fixes it if others solved concurrently).
                if isinstance(c.get("solves"), int):
                    c["solves"] += 1
        self._session_solved.add(cid)
        self._tree_sig = None  # force a rebuild so the new state shows immediately
        # name the solved challenge in the log/toast (not just the server's "Correct")
        extra = f" — {message}" if message and message.strip().lower() != "correct" else ""
        self._emit(f"✔ Solved: {name} [{cat}]{extra}", "information", 6)
        self._apply_challenges(self.challenges)
        # re-render the open detail right away (reads the fresh solved/solves from the list)
        if self.selected and int(self.selected["id"]) == cid:
            self._render_detail({**self.selected, **self._detail_cache.get(cid, {})})
        # authoritative refresh of THIS challenge (true solve count, solver list, first blood),
        # without waiting for the periodic poll: drop its cached detail and refetch it now.
        self._detail_cache.pop(cid, None)
        self.detail_worker(cid)
        # our own score/rank and the scoreboard just changed too
        self.scoreboard_worker()
        self.me_worker()
        # a solve can unlock/reveal other challenges (prerequisites, flag chains): re-list now
        # instead of waiting for the next poll, so any newly visible challenge appears right away
        # (_apply_challenges announces each one with a "🆕 New" toast).
        self.list_worker()

    def _after_reject(self, cid: int, status: str, message: str) -> None:
        """A flag was rejected: reflect it in the detail panel immediately."""
        # optimistic +1: the server just counted one more attempt, so the "Attempts: used/max"
        # line moves at once instead of staying stale until the detail is refetched below.
        det = self._detail_cache.get(cid)
        if det is not None and isinstance(det.get("attempts"), int):
            det["attempts"] += 1
        if self.selected and int(self.selected.get("id", -1)) == cid and isinstance(self.selected.get("attempts"), int):
            self.selected["attempts"] += 1
        detail = f": {message.strip()}" if message and message.strip().lower() != status.lower() else ""
        self._emit(f"✘ {self._chal_label(cid)}: {status}{detail}", "warning", 5)
        # re-render now: picks up the fresh "Tried & rejected" (written to disk just above)
        # and the bumped Attempts count
        if self.selected and int(self.selected["id"]) == cid:
            self._render_detail({**self.selected, **self._detail_cache.get(cid, {})})
        # authoritative refresh of THIS challenge's detail (exact attempts count, updated
        # remaining tries) without waiting for the periodic poll
        self._detail_cache.pop(cid, None)
        self.detail_worker(cid)

    # -- bookmark ---------------------------------------------
    def action_toggle_bookmark(self) -> None:
        if not self.selected:
            self.notify("Select a challenge first.", severity="warning")
            return
        cid = int(self.selected["id"])
        if cid in self.bookmarked:
            self.bookmarked.discard(cid)
            self.notify(f"☆ Unbookmarked: {self.selected.get('name', '?')}", timeout=3)
        else:
            self.bookmarked.add(cid)
            self.notify(f"★ Bookmarked: {self.selected.get('name', '?')}", timeout=3)
        self._rebuild_tree()
        self._save_ui_state()

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
