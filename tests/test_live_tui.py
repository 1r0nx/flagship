"""The TUI against a REAL CTFd lab (same env vars as test_live_ctfd.py; skipped otherwise)."""

import asyncio
import os

import pytest

from flagship import app as tui
from flagship.config import Config
from conftest import write_config

URL = os.environ.get("FLAGSHIP_LIVE_URL", "")
TOKEN = os.environ.get("FLAGSHIP_LIVE_TOKEN", "")
MODE = os.environ.get("FLAGSHIP_LIVE_MODE", "solo")
pytestmark = pytest.mark.skipif(not (URL and TOKEN), reason="no live CTFd (set FLAGSHIP_LIVE_URL/TOKEN)")


async def settle(app, pilot, rounds=4):
    for _ in range(rounds):
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)


def test_tui_against_live_platform(tmp_path):
    base = tmp_path / "live"
    cfg = Config.load(write_config(tmp_path / "config.sh", URL, base, token=TOKEN,
                                   POLL_INTERVAL="0", WATCH_INTERVAL="0"))

    async def scenario():
        app = tui.Flagship(cfg)
        async with app.run_test(size=(180, 60)) as pilot:
            await settle(app, pilot)
            names = {c["name"] for c in app.challenges}
            assert {"Welcome Board", "Ocean's Eleven"} <= names
            assert "Hidden Draft" not in names and "Locked Vault" not in names  # hidden / prerequisite
            assert app.query_one("#scoreboard").row_count >= 1
            assert "Online" in str(app.query_one("#connstatus").render())
            if MODE == "team":
                assert app._members, "team mode must load the per-member breakdown"
                for m in app._members:  # every member solve carries its real timestamp
                    assert m["solves"] and all(s["date"] for s in m["solves"])
            # the detail panel renders for a real challenge
            app.selected = next(c for c in app.challenges if c["name"] == "Ocean's Eleven")
            app._render_detail(app.selected)
            await pilot.pause(0.1)
    asyncio.run(scenario())
