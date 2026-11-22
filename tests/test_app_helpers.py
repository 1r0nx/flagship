"""Pure helpers of the TUI module (formatting, stats text, scoreboard gap), no terminal needed."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from flagship import app as tui


def test_fmt_when_converts_utc_to_local_and_handles_garbage():
    raw = "2026-11-20T10:00:00Z"
    expected = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert tui._fmt_when(raw) == expected
    assert tui._fmt_when("2026-11-20T10:00:00") == datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert tui._fmt_when("not a date") == "not a date"
    assert tui._fmt_when(None) == "" and tui._fmt_when("") == ""


@pytest.mark.parametrize("n,expected", [(512, "512 B"), (4300, "4.2 KB"), (210 * 1024**2, "210.0 MB"),
                                        (3 * 1024**4, "3.0 TB"), (None, "?"), ("x", "?")])
def test_human_size(n, expected):
    assert tui._human_size(n) == expected


def test_fmt_download_progress_with_and_without_total():
    assert tui._fmt_dl(50, 200).startswith("25% (")
    assert tui._fmt_dl(300, 200).startswith("100% (")  # never above 100
    assert tui._fmt_dl(2048, 0) == "2.0 KB"             # unknown size: just bytes so far


@pytest.mark.parametrize("num,den,expected", [(0, 0, 0), (23, 24, 96), (24, 24, 100), (0, 5, 0), (1, 1000, 0)])  # 0.1% rounds to 0%
def test_pct_capped_never_shows_100_unless_complete(num, den, expected):
    assert tui._pct_capped(num, den) == expected


def test_score_diff_signs_and_neutral_cases():
    assert tui.Flagship._score_diff(120, 100, is_me=False) == "+20"   # they lead us
    assert tui.Flagship._score_diff(80, 100, is_me=False) == "-20"    # we lead them
    assert tui.Flagship._score_diff(100, 100, is_me=False) == "0"
    assert tui.Flagship._score_diff(100, 100, is_me=True) == "—"
    assert tui.Flagship._score_diff(50, None, is_me=False) == ""
    assert tui.Flagship._score_diff("x", 10, is_me=False) == ""


def test_diff_style_colours():
    assert tui.Flagship._diff_style("+5", False, "acc", "green", "red") == "red"
    assert tui.Flagship._diff_style("-5", False, "acc", "green", "red") == "green"
    assert tui.Flagship._diff_style("0", False, "acc", "green", "red") == ""
    assert tui.Flagship._diff_style("—", True, "acc", "green", "red") == "acc"


def test_md_cell_escapes_table_breakers():
    assert tui._md_cell("a|b\nc\rd") == "a\\|b c d"


def test_member_history_most_recent_first_with_challenge_details():
    chs = [{"id": 1, "name": "Alpha", "category": "web", "value": 100},
           {"id": 2, "name": "Beta", "category": "pwn", "value": 200}]
    solves = [{"challenge_id": 1, "date": "2026-11-01T10:00:00"},
              {"challenge_id": 2, "date": "2026-11-03T09:00:00"}]
    rows = tui.member_history(chs, solves)
    assert [r["name"] for r in rows] == ["Beta", "Alpha"]  # newest first
    assert rows[0] == {"name": "Beta", "category": "pwn", "value": 200, "date": "2026-11-03T09:00:00"}


def test_member_history_keeps_solves_of_hidden_challenges_named_by_id():
    rows = tui.member_history([], [{"challenge_id": 42, "date": "2026-11-01T00:00:00"}])
    assert rows == [{"name": "#42", "category": "", "value": 0, "date": "2026-11-01T00:00:00"}]


def test_member_history_empty_and_bad_points():
    assert tui.member_history([], []) == []
    rows = tui.member_history([{"id": 1, "name": "X", "category": "web", "value": None}],
                              [{"challenge_id": 1, "date": ""}])
    assert rows[0]["value"] == 0 and rows[0]["date"] == ""


def test_cat_color_is_stable_per_category(fake):
    """Same category -> same colour, across calls and instances (the colour map is cached)."""
    from flagship.config import Config
    cfg = Config(url="http://x", token="t", base_dir=Path("/tmp/x"),
                 ctf_name="c", poll_interval=0, write_flag_on_solve=True, watch_changes=True,
                 watch_interval=0, auto_unlock_free_hints=False, download_workers=1,
                 theme="textual-dark", editor="", config_dir=Path("/tmp"),
                 auto_notes=False)
    app = tui.Flagship(cfg, offline=True)
    app.challenges = [{"category": "web"}, {"category": "pwn"}]
    a = app._cat_color("web")
    assert a == app._cat_color("web") and a != app._cat_color("pwn")
    fallback = app._cat_color("unknown-cat")  # not in the map yet: fixed palette, still a hex colour
    assert fallback.startswith("#") and len(fallback) == 7
