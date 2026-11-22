"""Synchronisation logic against the fake platform: folders, statements, files, versions, cache."""

import pytest

from flagship import store
from flagship.ctfd import CTFd


@pytest.fixture
def client(fake):
    return CTFd(fake.url, "test-token")


def summary_of(fake, cid):
    c = fake.challenges[cid]
    return {"id": cid, "name": c["name"], "category": c["category"], "value": c["value"]}


def test_ensure_challenge_creates_folder_statement_and_files(fake, client, base_dir):
    fake.add_challenge(1, "Chall One", category="web", description="Find it.",
                       files=["chall.zip"])
    fake.add_file("/files/1/chall.zip", b"ZIP")
    d, events, detail = store.ensure_challenge(client, base_dir, summary_of(fake, 1), True)
    assert d == base_dir / "CHALLENGES" / "web" / "Chall-One"
    assert (d / "Chall-One.txt").read_text(encoding="utf-8").count("Find it.") == 1
    assert (d / "work" / "chall.zip").read_bytes() == b"ZIP"
    assert [e["kind"] for e in events] == ["new"]
    assert (d / ".flagship.json").exists()


def test_second_pass_without_change_is_silent(fake, client, base_dir):
    fake.add_challenge(2, "Quiet", category="web", description="same")
    summary = summary_of(fake, 2)
    store.ensure_challenge(client, base_dir, summary, True)
    _, events, _ = store.ensure_challenge(client, base_dir, summary, True)
    assert events == []


def test_description_change_creates_new_version_file(fake, client, base_dir):
    fake.add_challenge(3, "Evolve", category="web", description="v1 text")
    summary = summary_of(fake, 3)
    d, _, _ = store.ensure_challenge(client, base_dir, summary, True)
    fake.challenges[3]["description"] = "v2 text"
    _, events, _ = store.ensure_challenge(client, base_dir, summary, True)
    kinds = [e["kind"] for e in events]
    assert "desc" in kinds
    v2 = d / "Evolve-v2.txt"
    assert v2.exists() and "v2 text" in v2.read_text(encoding="utf-8")
    assert "v1 text" in (d / "Evolve.txt").read_text(encoding="utf-8")  # original untouched


def test_hint_unlock_is_reported_and_versioned(fake, client, base_dir):
    fake.add_challenge(4, "Hints", category="web", description="d", hints=[{"id": 1, "cost": 0}])
    summary = summary_of(fake, 4)
    d, _, _ = store.ensure_challenge(client, base_dir, summary, True)
    fake.unlocked_hints.add(1)
    _, events, _ = store.ensure_challenge(client, base_dir, summary, True)
    msgs = [e["msg"] for e in events if e["kind"] == "hint"]
    assert msgs == ["hint #1 unlocked"]
    assert (d / "Hints-v2.txt").exists()


def test_watch_disabled_does_not_refetch_existing_statement(fake, client, base_dir):
    fake.add_challenge(5, "NoWatch", category="web", description="x")
    summary = summary_of(fake, 5)
    store.ensure_challenge(client, base_dir, summary, True)
    before = fake.hits["GET /api/v1/challenges/5"]
    store.ensure_challenge(client, base_dir, summary, False)
    assert fake.hits["GET /api/v1/challenges/5"] == before


def test_auto_free_hints_unlocks_cost_zero_hints(fake, client, base_dir):
    fake.add_challenge(6, "Free", category="web", description="x",
                       hints=[{"id": 1, "cost": 0}, {"id": 2, "cost": 100}])
    store.ensure_challenge(client, base_dir, summary_of(fake, 6), True, auto_free_hints=True)
    assert 1 in fake.unlocked_hints and 2 not in fake.unlocked_hints  # paid hint untouched


def test_auto_notes_creates_md_only_when_enabled(fake, client, base_dir):
    fake.add_challenge(7, "Noted", category="web", description="x")
    d, _, _ = store.ensure_challenge(client, base_dir, summary_of(fake, 7), True)
    assert not (d / "Noted.md").exists()
    store.ensure_challenge(client, base_dir, summary_of(fake, 7), True, auto_notes=True)
    assert (d / "Noted.md").exists()


def test_legacy_desc_txt_is_migrated_on_sync(fake, client, base_dir):
    fake.add_challenge(8, "Legacy", category="web", description="old")
    d = base_dir / "CHALLENGES" / "web" / "Legacy"
    d.mkdir(parents=True)
    (d / "desc.txt").write_text("legacy statement", encoding="utf-8")
    store.ensure_challenge(client, base_dir, summary_of(fake, 8), False)
    assert (d / "Legacy.txt").read_text(encoding="utf-8") == "legacy statement"
    assert not (d / "desc.txt").exists()


def test_list_state_renders_downloaded_and_solved_flags(fake, client, base_dir):
    fake.add_challenge(10, "Got", category="web", description="x")
    fake.add_challenge(11, "Not", category="web", description="y")
    fake.mark_solved(10, by="me")
    store.ensure_challenge(client, base_dir, summary_of(fake, 10), True)
    chs, events = store.list_state(client, base_dir, watch=False)
    by = {c["id"]: c for c in chs}
    assert by[10]["downloaded"] and by[10]["solved"]
    assert not by[11]["downloaded"] and not by[11]["solved"]
    assert store.load_cache(base_dir)  # the list is cached for --offline


def test_list_state_watch_detects_changes_on_downloaded_only(fake, client, base_dir):
    fake.add_challenge(12, "Watched", category="web", description="v1")
    fake.add_challenge(13, "Ignored", category="web", description="v1")
    store.ensure_challenge(client, base_dir, summary_of(fake, 12), True)
    fake.challenges[12]["description"] = "v2"
    chs, events = store.list_state(client, base_dir, watch=True)
    assert any(e["kind"] == "desc" and e["name"] == "Watched" for e in events)
    assert fake.hits["GET /api/v1/challenges/13"] == 0  # not downloaded -> no detail GET


def test_list_state_stop_callback_halts_watch_loop(fake, client, base_dir):
    for cid in range(20, 26):
        fake.add_challenge(cid, f"S{cid}", category="web", description="x")
        store.ensure_challenge(client, base_dir, summary_of(fake, cid), True)
    chs, _ = store.list_state(client, base_dir, watch=True, should_stop=lambda: True, workers=1)
    assert len(chs) == 6  # the list itself is still complete


def test_list_state_on_listed_called_before_watch(fake, client, base_dir):
    fake.add_challenge(30, "Order", category="web", description="x")
    store.ensure_challenge(client, base_dir, summary_of(fake, 30), True)
    calls = []
    store.list_state(client, base_dir, watch=True, on_listed=lambda chs: calls.append(len(chs)))
    assert calls == [1]


def test_sync_downloads_everything_and_reports_progress(fake, client, base_dir):
    fake.add_challenge(40, "A", category="web", description="a", files=["a.bin"])
    fake.add_challenge(41, "B", category="pwn", description="b")
    fake.add_file("/files/40/a.bin", b"AAA")
    seen = []
    chs, events = store.sync(client, base_dir, True, False, 2, lambda done, total, name: seen.append((done, total)))
    assert seen[-1] == (2, 2)
    assert all(c["downloaded"] for c in chs)
    assert (base_dir / "CHALLENGES" / "web" / "A" / "work" / "a.bin").read_bytes() == b"AAA"
    assert store.load_json(base_dir, "challenges_cache.json")


def test_sync_is_idempotent(fake, client, base_dir):
    fake.add_challenge(42, "Idem", category="web", description="x")
    store.sync(client, base_dir, True, False, 2)
    _, events = store.sync(client, base_dir, True, False, 2)
    assert events == []


def test_sync_completes_missing_work_files_of_known_challenge(fake, client, base_dir):
    """A challenge whose statement exists but whose file is missing must get the file on a
    full sync (self-healing), not only on a single-challenge download."""
    fake.add_challenge(43, "Heal", category="web", description="x", files=["h.zip"])
    fake.add_file("/files/43/h.zip", b"HEAL")
    store.sync(client, base_dir, True, False, 2)
    work = base_dir / "CHALLENGES" / "web" / "Heal" / "work" / "h.zip"
    work.unlink()
    store.sync(client, base_dir, True, False, 2)
    assert work.exists(), "sync must re-download a missing work/ file"


def test_download_one_for_known_challenge_completes_files(fake, client, base_dir):
    fake.add_challenge(44, "One", category="web", description="x", files=["o.zip"])
    fake.add_file("/files/44/o.zip", b"O")
    s = summary_of(fake, 44)
    path, events = store.download_one(client, base_dir, s, True)
    assert (base_dir / "CHALLENGES" / "web" / "One" / "work" / "o.zip").exists()
    assert path.endswith("One")


def test_download_subset_only_touches_given_challenges(fake, client, base_dir):
    fake.add_challenge(50, "InCat", category="crypto", description="x")
    fake.add_challenge(51, "OutCat", category="web", description="x")
    subset = [summary_of(fake, 50)]
    store.assign_paths(subset, base_dir)
    store.download_subset(client, base_dir, subset, True, False, 2)
    assert (base_dir / "CHALLENGES" / "crypto" / "InCat").exists()
    assert not (base_dir / "CHALLENGES" / "web" / "OutCat").exists()


def test_sync_survives_one_failing_challenge(fake, client, base_dir):
    fake.add_challenge(60, "Good", category="web", description="g")
    fake.add_challenge(61, "Bad", category="web", description="b")
    fake.set_override("GET", "/api/v1/challenges/61", 500)
    chs, _ = store.sync(client, base_dir, True, False, 2)
    by = {c["id"]: c for c in chs}
    assert by[60]["downloaded"] is True and by[61]["downloaded"] is False


def test_first_bloods_cached_and_not_refetched_once_known(fake, client):
    fake.add_challenge(70, "FB")
    fake.mark_solved(70, by="alice")
    new, errors = store.fetch_first_bloods(client, [70], {})
    assert new == {70: "alice"} and errors == 0
    before = fake.hits["GET /api/v1/challenges/70/solves"]
    new2, _ = store.fetch_first_bloods(client, [70], {70: "alice"})
    assert new2 == {} and fake.hits["GET /api/v1/challenges/70/solves"] == before


def test_first_bloods_counts_errors_for_backoff(fake, client):
    fake.add_challenge(71, "Locked")
    fake.set_override("GET", "/api/v1/challenges/71/solves", 403)
    new, errors = store.fetch_first_bloods(client, [71], {})
    assert new == {} and errors == 1


def test_first_bloods_unknown_is_not_cached(fake, client):
    fake.add_challenge(72, "NoSolveYet")
    new, errors = store.fetch_first_bloods(client, [72], {})
    assert new == {} and errors == 0  # "nobody yet" must stay retriable


def test_write_flag_from_sync_path_roundtrip(fake, client, base_dir):
    fake.add_challenge(80, "Flagged", category="web", description="x", flag="HLB{x}")
    chs, _ = store.sync(client, base_dir, True, False, 1)
    path = chs[0]["path"]
    store.write_flag(path, "HLB{x}")
    assert store.read_flag(path) == "HLB{x}"
