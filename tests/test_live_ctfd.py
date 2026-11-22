"""End-to-end tests against a REAL CTFd instance (a local, fictional lab platform).

Skipped unless these environment variables are set (the token is read from the env and never printed):
    FLAGSHIP_LIVE_URL    e.g. http://127.0.0.1:8101
    FLAGSHIP_LIVE_TOKEN  an API token of the PLAYER (what Flagship uses)
    FLAGSHIP_LIVE_ADMIN_TOKEN  an API token of the lab admin (only to create fresh test challenges)
    FLAGSHIP_LIVE_MODE   "solo" or "team"  (default "solo")

The lab is seeded by tests/lab/seed_ctfd.py (challenges, files, hints, a prerequisite, solves).
"""

import os
from pathlib import Path

import pytest

from flagship import store
from flagship.ctfd import CTFd, CTFdError

URL = os.environ.get("FLAGSHIP_LIVE_URL", "")
TOKEN = os.environ.get("FLAGSHIP_LIVE_TOKEN", "")
ADMIN_TOKEN = os.environ.get("FLAGSHIP_LIVE_ADMIN_TOKEN", "")
MODE = os.environ.get("FLAGSHIP_LIVE_MODE", "solo")

pytestmark = pytest.mark.skipif(not (URL and TOKEN), reason="no live CTFd (set FLAGSHIP_LIVE_URL/TOKEN)")


@pytest.fixture
def live(tmp_path):
    client = CTFd(URL, TOKEN)
    base = tmp_path / "live"
    base.mkdir()
    return client, base


@pytest.fixture
def admin():
    if not ADMIN_TOKEN:
        pytest.skip("no FLAGSHIP_LIVE_ADMIN_TOKEN: cannot create fresh challenges")
    return CTFd(URL, ADMIN_TOKEN)


def test_authentication_and_mode_detection(live):
    client, _ = live
    assert client.auth_ok() is True
    assert client.is_team_mode() is (MODE == "team")


def test_only_visible_challenges_are_listed(live):
    """Hidden challenges and challenges locked by a prerequisite must not appear for the player."""
    client, _ = live
    names = {c["name"] for c in client.challenges()}
    assert "Hidden Draft" not in names
    assert {"Welcome Board", "Ocean's Eleven"} <= names


def test_sync_downloads_statements_and_files(live):
    client, base = live
    chs, events = store.sync(client, base, True, False, 4)
    by = {c["name"]: c for c in chs}
    assert by["Ocean's Eleven"]["downloaded"] is True
    oceans = Path(by["Ocean's Eleven"]["path"])
    assert (oceans / "Oceans-Eleven.txt").exists()
    assert (oceans / "work" / "message.zip").read_bytes().startswith(b"PK")
    assert all(e["kind"] == "new" for e in events if e.get("name") in by)


def test_second_sync_is_idempotent(live):
    client, base = live
    store.sync(client, base, True, False, 4)
    _, events = store.sync(client, base, True, False, 4)
    assert events == []


@pytest.fixture
def fresh_challenge(admin):
    """A brand-new, never-solved challenge with a unique flag, created through the admin API.
    The lab keeps its state between runs, so a fixed challenge would not stay unsolved."""
    import uuid
    client = admin
    token = uuid.uuid4().hex[:8]
    name = f"Live Box {token}"
    flag = f"HLB{{live_{token}}}"
    ch = client._post("/api/v1/challenges", {"name": name, "category": "misc", "value": 50,
                                             "description": "created by the live test", "state": "visible",
                                             "type": "standard"})["data"]
    client._post("/api/v1/flags", {"challenge_id": ch["id"], "content": flag, "type": "static"})
    return name, flag


def test_wrong_then_right_flag_is_recorded(live, fresh_challenge):
    client, base = live
    name, flag = fresh_challenge
    chs, _ = store.sync(client, base, True, False, 4)
    box = next(c for c in chs if c["name"] == name)
    assert store.read_flag(box["path"]) is None  # not solved locally yet
    cid = int(box["id"])
    assert client.submit(cid, "HLB{definitely_wrong}")[0] == "incorrect"
    store.record_attempt(base, cid, "HLB{definitely_wrong}", False, box["path"])
    assert store.was_attempted(base, cid, "HLB{definitely_wrong}")
    status, _ = client.submit(cid, flag)
    assert status == "correct"
    store.write_flag(box["path"], flag)
    assert store.read_flag(box["path"]) == flag
    assert cid in client.solved_ids()
    assert client.submit(cid, flag)[0] == "already_solved"


def test_auto_free_hints_unlock_only_free(live):
    client, base = live
    store.sync(client, base, True, True, 4)  # auto_free_hints=True
    wb = int(next(c["id"] for c in client.challenges() if c["name"] == "Welcome Board"))
    hints = {h["cost"]: h for h in client.challenge(wb)["hints"]}
    assert hints[0].get("content"), "free hint must be unlocked"
    assert not hints[50].get("content"), "paid hint must stay locked"


def test_scoreboard_and_solved_set(live):
    client, _ = live
    assert client.solved_ids()  # the lab already has solves
    assert client.scoreboard()


@pytest.mark.skipif(MODE != "team", reason="team-mode lab only")
def test_team_member_breakdown(live):
    client, _ = live
    members = {m["name"]: m for m in client.team_member_stats()}
    # only members with at least one solve are listed (documented in team_member_stats)
    assert "mate" in members and members["mate"]["count"] >= 1
    assert all(m["count"] >= 1 for m in members.values())


def test_bad_token_is_rejected_cleanly(live):
    bad = CTFd(URL, "not-a-real-token")
    assert bad.auth_ok() is False
    with pytest.raises(CTFdError, match="access denied"):
        bad.challenges()
