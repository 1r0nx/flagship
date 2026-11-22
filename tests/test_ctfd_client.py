"""flagship.ctfd.CTFd against the fake platform: endpoints, error mapping, team/solo detection."""

import pytest

from flagship.ctfd import CTFd, CTFdError, OfflineCTFd


@pytest.fixture
def client(fake):
    return CTFd(fake.url, "test-token")


def test_challenges_listing(fake, client):
    fake.add_challenge(1, "A", category="web", value=50)
    fake.add_challenge(2, "B", category="pwn", value=200)
    names = sorted(c["name"] for c in client.challenges())
    assert names == ["A", "B"]


def test_challenge_detail_hides_locked_hint_content(fake, client):
    fake.add_challenge(3, "H", hints=[{"id": 9, "cost": 0}, {"id": 10, "cost": 50}])
    d = client.challenge(3)
    assert "content" not in d["hints"][0] and "content" not in d["hints"][1]
    assert client.unlock_hint(9)  # unlock succeeds and returns the hint text
    assert client.challenge(3)["hints"][0].get("content")


def test_submit_correct_then_already_solved(fake, client):
    fake.add_challenge(4, "F", flag="HLB{ok}")
    assert client.submit(4, "HLB{nope}") == ("incorrect", "Incorrect")
    assert client.submit(4, "HLB{ok}") == ("correct", "Correct")
    assert client.submit(4, "HLB{ok}") == ("already_solved", "already solved")
    assert fake.submissions == [(4, "HLB{nope}"), (4, "HLB{ok}"), (4, "HLB{ok}")]


def test_solved_ids_and_me(fake, client):
    fake.add_challenge(5, "S")
    fake.mark_solved(5, by="me")
    assert client.solved_ids() == {5}
    assert client.me()["name"] == "me" and client.me()["team"] is False


def test_solo_mode_detected_when_teams_endpoint_is_404(fake, client):
    fake.team_mode = False
    assert client.is_team_mode() is False


def test_team_mode_uses_team_account_and_member_stats(fake, client):
    fake.team_mode = True
    fake.add_challenge(6, "T", value=100)
    fake.add_challenge(7, "U", value=50)
    fake.mark_solved(6, by="me")
    fake.mark_solved(7, by="mate")
    assert client.is_team_mode() is True
    assert client.me()["team"] is True and client.me()["name"] == "TeamX"
    stats = {m["name"]: m for m in client.team_member_stats()}
    assert stats["me"]["solved_ids"] == [6] and stats["mate"]["solved_ids"] == [7]
    assert stats["mate"]["solves"][0]["challenge_id"] == 7 and stats["mate"]["solves"][0]["date"]
    assert client.solved_ids() == {6, 7}


def test_scoreboard_rows_are_numbered(fake, client):
    fake.scoreboard = [{"name": "a", "score": 10, "account_id": 1, "account_type": "user"},
                       {"name": "b", "score": 5, "account_id": 2, "account_url": "/users/2"}]
    rows = client.scoreboard()
    assert [r["pos"] for r in rows] == [1, 2]
    assert client.scoreboard(top=1) == rows[:1]


def test_notifications_sorted_newest_first(fake, client):
    fake.notifications = [{"id": 1, "title": "old", "date": "2026-01-01T00:00:00"},
                          {"id": 2, "title": "new", "date": "2026-06-01T00:00:00"}]
    assert [n["title"] for n in client.notifications()] == ["new", "old"]


def test_account_solves_sorted_most_recent_first(fake, client):
    fake.add_challenge(8, "X", value=30)
    fake.add_challenge(9, "Y", value=40)
    fake.mark_solved(8, by="me", date="2026-11-01T00:00:00")
    fake.mark_solved(9, by="me", date="2026-11-02T00:00:00")
    rows = client.account_solves(1, team=False)
    assert [r["name"] for r in rows] == ["Y", "X"]  # most recent first
    assert rows[0]["value"] == 40 and rows[0]["category"] == "web"


def test_first_blood_and_solvers(fake, client):
    fake.add_challenge(9, "FB")
    assert client.first_blood(9) is None
    assert client.challenge_solvers(9) == []
    fake.mark_solved(9, by="alice", date="2026-11-01T00:00:00")
    fake.mark_solved(9, by="bob", date="2026-11-03T00:00:00")
    assert client.first_blood(9) == "alice"
    assert [s["name"] for s in client.challenge_solvers(9)] == ["bob", "alice"]


def test_auth_failure_maps_to_ctfd_error(fake):
    bad = CTFd(fake.url, "wrong-token")
    with pytest.raises(CTFdError, match="access denied"):
        bad.challenges()
    assert bad.auth_ok() is False


@pytest.mark.parametrize("status,needle", [
    (404, "not found"), (429, "too many requests"), (500, "server error"),
])
def test_http_error_messages(fake, client, status, needle):
    fake.set_override("GET", "/api/v1/challenges", status, b"{}")
    with pytest.raises(CTFdError, match=needle):
        client.challenges()


def test_non_json_response_is_reported(fake, client):
    fake.set_override("GET", "/api/v1/challenges", 200, b"<html>login</html>", "text/html")
    with pytest.raises(CTFdError, match="non-JSON"):
        client.challenges()


def test_success_false_message_is_surfaced(fake, client):
    fake.set_override("GET", "/api/v1/challenges", 200, b'{"success": false, "message": "CTF not started"}')
    with pytest.raises(CTFdError, match="CTF not started"):
        client.challenges()


def test_network_error_is_wrapped(client, monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(client._session, "get", boom)
    with pytest.raises(CTFdError, match="network"):
        client.challenges()


def test_optional_readers_return_none_when_unreachable(fake, client):
    fake.set_override("GET", "/api/v1/notifications", 500)
    fake.set_override("GET", "/api/v1/teams/1/solves", 403)
    assert client.notifications() is None
    assert client.account_solves(1, team=True) is None


def test_solved_ids_empty_on_error(fake, client):
    fake.set_override("GET", "/api/v1/users/me/solves", 500)
    assert client.solved_ids() == set()


def test_offline_client_returns_none_for_everything(tmp_path):
    off = OfflineCTFd("https://x.example/")
    assert off.url == "https://x.example"
    assert off.challenges() is None and off.scoreboard() is None
    assert off.is_team_mode() is None
    assert off.notifications() is None


def test_offline_client_dunder_lookup_raises():
    with pytest.raises(AttributeError):
        OfflineCTFd().__deepcopy__  # noqa: B018  (dunders must not be proxied)
