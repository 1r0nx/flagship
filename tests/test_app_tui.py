"""Drive the real Textual app headless (pilot) against the fake CTFd: keys, actions, screens."""

import asyncio
from pathlib import Path

import pytest

from flagship import app as tui
from flagship.config import Config
from flagship import store
from conftest import write_config


def make_cfg(url: str, base: Path, tmp: Path, **extra) -> Config:
    p = write_config(tmp / "config.sh", url, base, POLL_INTERVAL="0", WATCH_CHANGES="true",
                     WATCH_INTERVAL="0", **extra)
    return Config.load(p)


async def settle(app, pilot, rounds: int = 3):
    for _ in range(rounds):
        await app.workers.wait_for_complete()
        await pilot.pause(0.05)


def leaves(app):
    out = []
    for cat in app.query_one("#tree").root.children:
        out += [leaf.data for leaf in cat.children if leaf.data and "_cat" not in leaf.data]
    return out


@pytest.fixture
def seeded(fake):
    fake.add_challenge(1, "Alpha", category="web", value=100, description="alpha text",
                       files=["a.zip"], hints=[{"id": 11, "cost": 0}, {"id": 12, "cost": 50}],
                       flag="HLB{alpha}")
    fake.add_challenge(2, "Beta", category="pwn", value=200, description="beta text", flag="HLB{beta}")
    fake.add_challenge(3, "Gamma", category="web", value=300, description="gamma", max_attempts=2,
                       flag="HLB{gamma}")
    fake.add_file("/files/1/a.zip", b"AZIP")
    fake.scoreboard = [{"name": "mate", "score": 300, "account_id": 2, "account_type": "user",
                        "account_url": "/users/2"}]
    fake.mark_solved(2, by="me")  # the player (me) solved Beta; mate's solves are not mine
    return fake


def run(coro):
    return asyncio.run(coro)


def test_startup_lists_challenges_and_scoreboard(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            names = sorted(leaf["name"] for leaf in leaves(app))
            assert names == ["Alpha", "Beta", "Gamma"]
            assert app.query_one("#scoreboard").row_count == 1
            assert "Online" in str(app.query_one("#connstatus").render())
    run(scenario())


def test_search_filters_tree_by_name_and_description(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.search = "gamma"
            app._rebuild_tree()
            assert [leaf["name"] for leaf in leaves(app)] == ["Gamma"]
            app.search = "pwn"  # category match
            app._rebuild_tree()
            assert [leaf["name"] for leaf in leaves(app)] == ["Beta"]
            app.search = ""
            app._rebuild_tree()
            assert len(leaves(app)) == 3
    run(scenario())


def test_filter_and_sort_cycle_keys(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            assert app.filter_mode == "all"
            await pilot.press("f")
            assert app.filter_mode == "unsolved"
            assert [leaf["name"] for leaf in leaves(app)] == ["Alpha", "Gamma"]  # Beta is solved
            await pilot.press("f")
            assert app.filter_mode == "solved"
            assert [leaf["name"] for leaf in leaves(app)] == ["Beta"]
            await pilot.press("f")
            await pilot.press("f")
            assert app.filter_mode == "all"
            before = app.sort_mode
            await pilot.press("o")
            assert app.sort_mode != before
    run(scenario())


def test_bookmark_toggle_persists_state(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("b")
            assert 1 in app.bookmarked
            await pilot.press("b")
            assert 1 not in app.bookmarked
            await pilot.press("b")
        saved = (base_dir / ".flagship" / "state.json")
        assert saved.exists() and "1" in saved.read_text(encoding="utf-8")
    run(scenario())


def test_download_action_creates_statement_and_files(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("d")
            await settle(app, pilot, 6)
        d = base_dir / "CHALLENGES" / "web" / "Alpha"
        assert (d / "Alpha.txt").exists() and (d / "work" / "a.zip").read_bytes() == b"AZIP"
    run(scenario())


def test_correct_flag_submission_marks_solved_and_writes_flag_file(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            app.query_one("#flag").value = "HLB{alpha}"
            app.query_one("#flag").post_message(tui.Input.Submitted(app.query_one("#flag"), "HLB{alpha}"))
            await settle(app, pilot, 6)
            assert seeded.submissions[-1] == (1, "HLB{alpha}")
            assert any(c.get("solved") for c in app.challenges if c["id"] == 1)
        assert (base_dir / "CHALLENGES" / "web" / "Alpha" / "flag.txt").read_text(encoding="utf-8").strip() == "HLB{alpha}"
    run(scenario())


def test_wrong_flag_is_remembered_and_not_resent(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            flag_input = app.query_one("#flag")
            flag_input.post_message(tui.Input.Submitted(flag_input, "HLB{nope}"))
            await settle(app, pilot, 6)
            count_after_first = len(seeded.submissions)
            flag_input.post_message(tui.Input.Submitted(flag_input, "HLB{nope}"))
            await settle(app, pilot, 4)
            assert len(seeded.submissions) == count_after_first  # not resent
            assert store.was_attempted(base_dir, 1, "HLB{nope}")
    run(scenario())


def test_limited_attempts_asks_for_confirmation_first(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Gamma")
            app._detail_cache[3] = {"max_attempts": 2, "attempts": 0}
            flag_input = app.query_one("#flag")
            flag_input.post_message(tui.Input.Submitted(flag_input, "HLB{gamma}"))
            await pilot.pause(0.2)
            assert isinstance(app.screen, tui.ConfirmScreen), "a confirmation must be shown"
            assert seeded.submissions == []  # nothing sent before the player confirms
            await pilot.click("#yes")  # the confirmation window has buttons, no shortcut
            await settle(app, pilot, 6)
            assert seeded.submissions[-1] == (3, "HLB{gamma}")
    run(scenario())


def test_offline_mode_shows_cache_and_blocks_api_actions(seeded, base_dir, tmp_path):
    online = make_cfg(seeded.url, base_dir, tmp_path)

    async def prime():
        app = tui.Flagship(online)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
    run(prime())
    off = online  # same cached folder; offline mode must not touch the network at all
    hits_before = sum(seeded.hits.values())

    async def scenario():
        app = tui.Flagship(off, offline=True)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            assert sorted(leaf["name"] for leaf in leaves(app)) == ["Alpha", "Beta", "Gamma"]
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("d")
            await pilot.press("r")
            await settle(app, pilot)
            assert "Offline" in str(app.query_one("#connstatus").render())
    run(scenario())
    assert sum(seeded.hits.values()) == hits_before  # zero network calls in offline mode


def test_export_progress_and_flags_actions(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            await pilot.press("p")
            await pilot.press("P")
            await pilot.pause(0.1)
    run(scenario())
    assert (base_dir / "PROGRESS_flagship.md").exists()
    assert (base_dir / "FLAGS_flagship.md").exists()


def test_notes_action_creates_md_with_editor(seeded, base_dir, tmp_path, monkeypatch):
    cfg = make_cfg(seeded.url, base_dir, tmp_path, EDITOR="true")

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Beta")
            app.action_edit_notes()
            await pilot.pause(0.2)
    run(scenario())
    assert (base_dir / "CHALLENGES" / "pwn" / "Beta" / "Beta.md").exists()


def test_theme_cycle_and_quit(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            before = app.theme
            await pilot.press("t")
            assert app.theme != before
            await pilot.press("q")
            await pilot.pause(0.1)
    run(scenario())


def test_full_sync_action_downloads_everything_after_confirmation(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.action_sync_all()
            await pilot.pause(0.2)
            assert isinstance(app.screen, tui.ConfirmScreen)
            await pilot.click("#yes")  # the confirmation window has buttons, no shortcut
            await settle(app, pilot, 8)
        assert (base_dir / "CHALLENGES" / "web" / "Gamma" / "Gamma.txt").exists()
        assert (base_dir / "CHALLENGES" / "pwn" / "Beta" / "Beta.txt").exists()
    run(scenario())


def test_challenge_name_with_rich_markup_does_not_break_the_tree(seeded, base_dir, tmp_path):
    """Names are arbitrary text: a '[/]' or '[red]' must be shown literally, never crash the tree."""
    seeded.add_challenge(9, "Odd [/] name [red]", category="misc", value=10, description="x")
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            assert any("Odd [/] name [red]" in leaf["name"] for leaf in leaves(app))
            label_texts = [str(n.label) for cat in app.query_one("#tree").root.children
                           for n in cat.children]
            assert any("Odd [/] name [red]" in t for t in label_texts)
    run(scenario())


def test_team_mode_loads_member_breakdown_and_cards(seeded, base_dir, tmp_path):
    seeded.team_mode = True
    seeded.mark_solved(1, by="mate")  # a teammate's solve, for the per-member breakdown
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            assert app.me.get("team") is True
            names = {m["name"] for m in app._members}
            assert "mate" in names
            cards = list(app.query(tui.MemberCard))
            assert len(cards) >= 1
            assert app.query_one("#members_title").display is True
    run(scenario())


def test_repeated_first_blood_failures_trigger_backoff(seeded, base_dir, tmp_path):
    """When every first-blood lookup is refused (CTF over), Flagship must stop retrying each poll."""
    seeded.set_override("GET", "/api/v1/challenges/2/solves", 403)
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app._fb_cache.pop(2, None)
            app.fb_worker()
            await settle(app, pilot)
            assert app._fb_backoff is True
            hits = seeded.hits["GET /api/v1/challenges/2/solves"]
            app.fb_worker()  # still backed off: no new request
            await settle(app, pilot)
            assert seeded.hits["GET /api/v1/challenges/2/solves"] == hits
    run(scenario())


def test_clicking_a_member_card_opens_their_solve_history(seeded, base_dir, tmp_path):
    """Team mode: clicking a member's card opens a table of that member's solves, newest first."""
    seeded.team_mode = True
    seeded.mark_solved(1, by="mate", date="2026-11-05T08:00:00Z")
    seeded.mark_solved(2, by="mate", date="2026-11-07T08:00:00Z")
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            mate = next(m for m in app._members if m["name"] == "mate")
            app.open_member_breakdown(mate["user_id"])
            await pilot.pause(0.2)
            screen = app.screen
            assert isinstance(screen, tui.MemberStatsScreen)
            table = screen.query_one("#mtable")
            rows = [table.get_row_at(i) for i in range(table.row_count)]
            assert [r[0] for r in rows] == ["Beta", "Alpha"]          # 2026-11-07 before 2026-11-05
            assert rows[0][1] == "pwn" and rows[0][2] == "200"
            assert rows[1][1] == "web" and rows[1][2] == "100"
            await pilot.press("escape")
    run(scenario())


def test_cached_solve_histories_are_refreshed_only_when_their_score_changes(seeded, base_dir, tmp_path):
    """After "Cache solves", a poll must not re-fetch every account; only the one whose score changed."""
    seeded.scoreboard = [
        {"name": "mate", "score": 300, "account_id": 2, "account_type": "user", "account_url": "/users/2"},
        {"name": "rival", "score": 50, "account_id": 3, "account_type": "user", "account_url": "/users/3"},
    ]
    cfg = make_cfg(seeded.url, base_dir, tmp_path)

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.preload_all_solves_worker()          # what "A" does, without the confirmation window
            await settle(app, pilot, 6)
            before = seeded.hits["GET /api/v1/users/2/solves"] + seeded.hits["GET /api/v1/users/3/solves"]
            app.refresh_cached_solves_worker()       # a poll, nothing changed
            await settle(app, pilot, 4)
            after_unchanged = seeded.hits["GET /api/v1/users/2/solves"] + seeded.hits["GET /api/v1/users/3/solves"]
            assert after_unchanged == before, "unchanged scores must not cause any request"

            seeded.scoreboard[1]["score"] = 150      # the rival solved something
            app._last_scoreboard = list(seeded.scoreboard)
            app.refresh_cached_solves_worker()
            await settle(app, pilot, 4)
            assert seeded.hits["GET /api/v1/users/3/solves"] == 2 and \
                seeded.hits["GET /api/v1/users/2/solves"] == 1
    run(scenario())


def test_flag_prefix_is_prefilled_and_only_the_inside_is_typed(seeded, base_dir, tmp_path):
    """With FLAG_PREFIX set, pressing s pre-fills it; the player types only what goes between the braces."""
    cfg = make_cfg(seeded.url, base_dir, tmp_path, FLAG_PREFIX="HLB{")

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("s")
            await pilot.pause(0.1)
            flag = app.query_one("#flag")
            assert flag.value == "HLB{"
            await pilot.press("a", "l", "p", "h", "a", "}", "enter")
            await settle(app, pilot, 6)
            assert seeded.submissions[-1] == (1, "HLB{alpha}")
            assert app.query_one("#flag").value == "HLB{"  # back to the prefix, ready for the next flag
    run(scenario())


def test_flag_prefix_alone_is_never_submitted(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path, FLAG_PREFIX="HLB{")

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("s")
            await pilot.pause(0.1)
            before = len(seeded.submissions)
            await pilot.press("enter")          # nothing typed between the braces
            await settle(app, pilot, 4)
            assert len(seeded.submissions) == before
    run(scenario())


def test_flag_prefix_and_suffix_leave_the_cursor_between_them(seeded, base_dir, tmp_path):
    """HLB{|} : the template is shown with the cursor between the braces; the player only types the inside."""
    cfg = make_cfg(seeded.url, base_dir, tmp_path, FLAG_PREFIX="HLB{", FLAG_SUFFIX="}")

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("s")
            await pilot.pause(0.1)
            flag = app.query_one("#flag")
            assert flag.value == "HLB{}"
            assert flag.cursor_position == len("HLB{")
            await pilot.press("a", "l", "p", "h", "a", "enter")
            await settle(app, pilot, 6)
            assert seeded.submissions[-1] == (1, "HLB{alpha}")
            assert app.query_one("#flag").value == "HLB{}"  # template restored after sending
    run(scenario())


def test_suffix_only_template_and_empty_inside_is_not_sent(seeded, base_dir, tmp_path):
    cfg = make_cfg(seeded.url, base_dir, tmp_path, FLAG_SUFFIX="}")

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(170, 55)) as pilot:
            await settle(app, pilot)
            app.selected = next(leaf for leaf in leaves(app) if leaf["name"] == "Alpha")
            await pilot.press("s")
            await pilot.pause(0.1)
            assert app.query_one("#flag").value == "}"
            before = len(seeded.submissions)
            await pilot.press("enter")
            await settle(app, pilot, 4)
            assert len(seeded.submissions) == before
    run(scenario())
