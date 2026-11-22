"""Pure / filesystem-only behaviour of flagship.store (no network)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from flagship import store


# ----------------------------------------------------------------- naming
@pytest.mark.parametrize("raw,expected", [
    ("Motor City Search", "Motor-City-Search"),
    ("Anakin's PC", "Anakins-PC"),          # shell-special chars dropped, not dashed
    ("a  b\tc", "a-b-c"),
    ("x / y \\ z", "x-y-z"),                 # path separators -> dash
    ("a---b", "a-b"),                        # no consecutive dashes
    ("..", "challenge"),                     # traversal guard
    (".", "challenge"),
    ("   ", "challenge"),
    ("Ocean's Eleven", "Oceans-Eleven"),
])
def test_slugify(raw, expected):
    assert store.slugify(raw) == expected


def test_slugify_filename_keeps_extension_and_guards_dots():
    assert store.slugify_filename("chall.zip") == "chall.zip"
    assert store.slugify_filename("a/b") == "a_b"
    assert store.slugify_filename("..") == "download.bin"
    assert store.slugify_filename("") == "download.bin"


def test_challenge_dir_layout(base_dir):
    assert store.challenge_dir(base_dir, "Web", "Inside Job1") == base_dir / "CHALLENGES" / "Web" / "Inside-Job1"
    assert store.challenge_dir(base_dir, "", "X") == base_dir / "CHALLENGES" / "Uncategorized" / "X"


def test_assign_paths_suffixes_colliding_names_with_id(base_dir):
    chs = [{"id": 1, "name": "Same", "category": "web"},
           {"id": 2, "name": "Same", "category": "web"},
           {"id": 3, "name": "Other", "category": "web"}]
    store.assign_paths(chs, base_dir)
    assert chs[0]["path"].endswith("web/Same-1")
    assert chs[1]["path"].endswith("web/Same-2")
    assert chs[2]["path"].endswith("web/Other")


def test_assign_paths_same_name_different_category_is_not_a_collision(base_dir):
    chs = [{"id": 1, "name": "Same", "category": "web"}, {"id": 2, "name": "Same", "category": "pwn"}]
    store.assign_paths(chs, base_dir)
    assert chs[0]["path"].endswith("web/Same") and chs[1]["path"].endswith("pwn/Same")


# ----------------------------------------------------------------- <challenge>.txt naming
def test_desc_name_scheme():
    assert store._desc_name("Oceans-Eleven") == "Oceans-Eleven.txt"
    assert store._desc_name("Oceans-Eleven", 2) == "Oceans-Eleven-v2.txt"


def test_desc_file_new_folder_uses_new_scheme(base_dir):
    d = base_dir / "CHALLENGES" / "web" / "Chall-A"
    d.mkdir(parents=True)
    assert store.desc_file(d) == d / "Chall-A.txt"
    assert store.desc_file(d, 3) == d / "Chall-A-v3.txt"


def test_migrate_renames_legacy_names(base_dir):
    d = base_dir / "web" / "Chall-B"
    d.mkdir(parents=True)
    (d / "desc.txt").write_text("v1", encoding="utf-8")
    (d / "desc2.txt").write_text("v2", encoding="utf-8")
    (d / "desc10.txt").write_text("v10", encoding="utf-8")
    moved = store.migrate_desc_names(d)
    assert ("desc.txt", "Chall-B.txt") in moved
    assert (d / "Chall-B.txt").read_text(encoding="utf-8") == "v1"
    assert (d / "Chall-B-v2.txt").read_text(encoding="utf-8") == "v2"
    assert (d / "Chall-B-v10.txt").read_text(encoding="utf-8") == "v10"
    assert not (d / "desc.txt").exists()


def test_migrate_never_overwrites_existing_target(base_dir):
    d = base_dir / "Chall-C"
    d.mkdir()
    (d / "desc.txt").write_text("legacy", encoding="utf-8")
    (d / "Chall-C.txt").write_text("already-new", encoding="utf-8")
    assert store.migrate_desc_names(d) == []
    assert (d / "Chall-C.txt").read_text(encoding="utf-8") == "already-new"
    assert (d / "desc.txt").read_text(encoding="utf-8") == "legacy"


def test_migrate_ignores_unrelated_files(base_dir):
    d = base_dir / "Chall-D"
    d.mkdir()
    (d / "description.md").write_text("x", encoding="utf-8")
    (d / "desc_notes.txt").write_text("x", encoding="utf-8")
    assert store.migrate_desc_names(d) == []
    assert (d / "description.md").exists() and (d / "desc_notes.txt").exists()


def test_ensure_notes_creates_skeleton_once(base_dir):
    d = base_dir / "Motor-City-Search"
    d.mkdir()
    summary = {"name": "Motor City Search", "category": "web", "value": 100}
    notes = store.ensure_notes(d, summary)
    assert notes == d / "Motor-City-Search.md"
    text = notes.read_text(encoding="utf-8")
    assert text.startswith("# Motor City Search\n") and "**Points:** 100" in text
    notes.write_text("my own notes", encoding="utf-8")
    store.ensure_notes(d, summary)
    assert notes.read_text(encoding="utf-8") == "my own notes"


# ----------------------------------------------------------------- text helpers
def test_clean_desc_unescapes_and_normalises_newlines():
    assert store.clean_desc("a &amp; b\r\nc\rd  ") == "a & b\nc\nd"
    assert store.clean_desc(None) == ""


@pytest.mark.parametrize("url,kind", [
    ("https://drive.google.com/file/d/x", "gdrive"),
    ("https://docs.google.com/x", "gdrive"),
    ("https://mega.nz/file/abc", "mega"),
    ("https://www.dropbox.com/s/x?dl=0", "dropbox"),
    ("https://example.com/x.zip", "http"),
])
def test_classify_link(url, kind):
    assert store.classify_link(url) == kind


def test_extract_links_dedup_and_trailing_punctuation():
    text = "see https://a.example/x.zip, and (https://a.example/x.zip) plus https://b.example/y."
    assert store.extract_links(text) == ["https://a.example/x.zip", "https://b.example/y"]
    assert store.extract_links(None) == []


def test_dropbox_direct():
    assert store._dropbox_direct("https://d.com/s/x?dl=0") == "https://d.com/s/x?dl=1"
    assert store._dropbox_direct("https://d.com/s/x") == "https://d.com/s/x?dl=1"
    assert store._dropbox_direct("https://d.com/s/x?a=1") == "https://d.com/s/x?a=1&dl=1"
    assert store._dropbox_direct("https://d.com/s/x?dl=1") == "https://d.com/s/x?dl=1"


def test_prereq_ids_all_formats():
    assert store.prereq_ids({"requirements": {"prerequisites": [3, 4]}}) == [3, 4]
    assert store.prereq_ids({"requirements": [5]}) == [5]
    assert store.prereq_ids({"requirements": None}) == []
    assert store.prereq_ids({}) == []


def test_hint_state_and_events():
    old = store._hints_state({"hints": [{"id": 1, "cost": 0, "content": ""},
                                         {"id": 2, "cost": 50, "content": ""}]})
    new = store._hints_state({"hints": [{"id": 1, "cost": 0, "content": "text"},
                                         {"id": 2, "cost": 75, "content": ""},
                                         {"id": 3, "cost": 0}]})
    msgs = [e["msg"] for e in store._hint_events(old, new, "C")]
    assert "hint #1 unlocked" in msgs
    assert "hint #2: cost 50→75" in msgs
    assert "new hint #3 (free)" in msgs


def test_hints_state_sorts_and_handles_missing_ids():
    s = store._hints_state({"hints": [{"id": 9}, {"id": None}, {"id": 2}]})
    assert [h["id"] for h in s] == [2, 9, None]


def test_desc_text_contains_every_section():
    detail = {"name": "N", "category": "web", "value": 50, "solves": 2, "id": 9,
              "description": "Hello", "requirements": {"prerequisites": [1]},
              "hints": [{"id": 4, "cost": 0, "content": "h"}]}
    txt = store._desc_text(detail, [("a.zip", "http://u/a.zip")], ["https://x.example/y"], header="# H\n\n")
    assert txt.startswith("# H\n\nName       : N")
    for needle in ["Category   : web", "Points     : 50", "Prerequisites (ids): 1",
                   "- work/a.zip : http://u/a.zip", "[http] https://x.example/y",
                   '[4] (unlocked, free) "h"', "Description:\nHello"]:
        assert needle in txt


def test_desc_text_no_files_no_hints():
    txt = store._desc_text({"name": "N", "description": ""}, [], [])
    assert "Files (platform, -> work/): none" in txt
    assert "External links: none" in txt and "Hints      : none" in txt


# ----------------------------------------------------------------- state / cache / attempts
def test_state_roundtrip_and_corruption(base_dir):
    d = base_dir / "c"
    d.mkdir()
    assert store._load_state(d) == {}
    store._save_state(d, {"version": 2})
    assert store._load_state(d) == {"version": 2}
    (d / ".flagship.json").write_text("{not json", encoding="utf-8")
    assert store._load_state(d) == {}


def test_attempts_remember_wrong_flags_only(base_dir):
    chal = base_dir / "CHALLENGES" / "web" / "c"
    chal.mkdir(parents=True)
    store.record_attempt(base_dir, 7, " FLAG{wrong} ", False, str(chal))
    store.record_attempt(base_dir, 7, "FLAG{wrong}", False, str(chal))  # duplicate not stored twice
    store.record_attempt(base_dir, 7, "FLAG{right}", True, str(chal))   # correct: never indexed
    assert store.was_attempted(base_dir, 7, "FLAG{wrong}")
    assert not store.was_attempted(base_dir, 7, "FLAG{right}")
    assert store.load_attempts(base_dir) == {"7": ["FLAG{wrong}"]}
    log = (chal / "attempts.log").read_text(encoding="utf-8")
    # attempts.log is an append-only, human-readable journal: one line per submission
    assert log.count("NO  : FLAG{wrong}") == 2 and "OK  : FLAG{right}" in log


def test_attempts_log_never_created_in_missing_folder(base_dir):
    store.record_attempt(base_dir, 1, "x", False, str(base_dir / "nope"))
    assert not (base_dir / "nope").exists()


def test_write_flag_never_overwrites(base_dir):
    d = base_dir / "c"
    store.write_flag(d, "  FLAG{a}  ")
    store.write_flag(d, "FLAG{b}")
    assert store.read_flag(d) == "FLAG{a}"
    assert store.read_flag(None) is None
    assert store.read_flag(base_dir / "missing") is None


def test_json_cache_helpers(base_dir):
    store.save_json(base_dir, "x.json", {"a": 1})
    assert store.load_json(base_dir, "x.json") == {"a": 1}
    assert store.load_json(base_dir, "absent.json", "dflt") == "dflt"
    (base_dir / ".flagship" / "bad.json").write_text("{", encoding="utf-8")
    assert store.load_json(base_dir, "bad.json", 5) == 5


def test_load_cache_reanchors_paths_and_checks_disk(base_dir):
    other = Path("/somewhere/else/MyCTF")
    store.save_json(base_dir, "challenges_cache.json",
                    [{"id": 1, "name": "A", "category": "web", "path": str(other / "CHALLENGES/web/A")}])
    real = base_dir / "CHALLENGES" / "web" / "A"
    real.mkdir(parents=True)
    (real / "A.txt").write_text("x", encoding="utf-8")
    [ch] = store.load_cache(base_dir)
    assert ch["path"] == str(base_dir / "CHALLENGES" / "web" / "A")
    assert ch["downloaded"] is True


def test_last_sync_at(base_dir):
    assert store.last_sync_at(base_dir) is None
    store.save_cache(base_dir, [])
    assert store.last_sync_at(base_dir) is not None
    store.save_json(base_dir, "last_sync.json", {"at": "garbage"})
    assert store.last_sync_at(base_dir) is None


# ----------------------------------------------------------------- exports
def test_md_cell_escapes_pipes_and_newlines():
    assert store._md_cell("a|b\nc") == "a\\|b c"


def test_write_progress_table(base_dir):
    chs = [{"category": "web", "name": "A|x", "value": 100, "solves": 3, "solved": True, "downloaded": True},
           {"category": "pwn", "name": "B", "value": 50, "solves": 0, "solved": False, "downloaded": False}]
    out = store.write_progress(base_dir, chs, "MyCTF")
    text = out.read_text(encoding="utf-8")
    assert out.name == "PROGRESS_flagship.md"
    assert "1/2 solved · 1 downloaded" in text
    assert "| web | A\\|x | 100 | 3 | ✔ | ✓ |" in text


def test_write_progress_tolerates_missing_points(base_dir):
    """A challenge with value=None (hidden/dynamic) must not break the export."""
    chs = [{"category": "web", "name": "A", "value": None}, {"category": "web", "name": "B", "value": 100}]
    store.write_progress(base_dir, chs, "MyCTF")  # must not raise


def test_write_flags_lists_solved_with_flag_or_unknown(base_dir):
    d = base_dir / "CHALLENGES" / "web" / "A"
    d.mkdir(parents=True)
    store.write_flag(d, "FLAG{known}")
    chs = [{"category": "web", "name": "A", "value": 10, "solved": True, "path": str(d)},
           {"category": "web", "name": "B", "value": 20, "solved": True, "path": str(base_dir / "x")},
           {"category": "web", "name": "C", "value": 30, "solved": False, "path": str(base_dir / "y")}]
    out = store.write_flags(base_dir, chs, "MyCTF")
    text = out.read_text(encoding="utf-8")
    assert "2 solved · 1 flag(s) recorded" in text
    assert "`FLAG{known}`" in text and "(unknown)" in text
    assert "| web | C |" not in text


# ----------------------------------------------------------------- download helpers (local HTTP)
class _Srv:
    def __init__(self, routes):
        self.routes = routes  # path -> (status, body, headers)

        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                status, body, headers = outer.routes.get(self.path.split("?")[0], (404, b"", {}))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def local_http():
    holder = {}

    def make(routes):
        srv = _Srv(routes)
        holder.setdefault("servers", []).append(srv)
        return srv

    yield make
    for s in holder.get("servers", []):
        s.close()


def test_download_external_direct_file(local_http, tmp_path):
    srv = local_http({"/f/chall.zip": (200, b"PK..data", {"Content-Type": "application/zip"})})
    dest = tmp_path / "work"
    dest.mkdir()
    status, info = store.download_external(srv.base + "/f/chall.zip", dest)
    assert status == "ok"
    assert (dest / "chall.zip").read_bytes() == b"PK..data"


def test_download_external_skips_existing_file(local_http, tmp_path):
    srv = local_http({"/f/a.bin": (200, b"new", {"Content-Type": "application/octet-stream"})})
    dest = tmp_path / "work"
    dest.mkdir()
    (dest / "a.bin").write_bytes(b"original")
    status, _ = store.download_external(srv.base + "/f/a.bin", dest)
    assert status == "skip"
    assert (dest / "a.bin").read_bytes() == b"original"


def test_download_external_web_page_is_not_saved(local_http, tmp_path):
    srv = local_http({"/page": (200, b"<html>hi</html>", {"Content-Type": "text/html; charset=utf-8"})})
    dest = tmp_path / "work"
    dest.mkdir()
    status, _ = store.download_external(srv.base + "/page", dest)
    assert status == "page"
    assert list(dest.iterdir()) == []


def test_download_external_attachment_overrides_html_detection(local_http, tmp_path):
    srv = local_http({"/dl": (200, b"<html>looks like html</html>",
                              {"Content-Type": "text/html", "Content-Disposition": 'attachment; filename="real.html"'})})
    dest = tmp_path / "work"
    dest.mkdir()
    status, _ = store.download_external(srv.base + "/dl", dest)
    assert status == "ok" and (dest / "real.html").exists()


def test_download_external_error_status(local_http, tmp_path):
    srv = local_http({})
    dest = tmp_path / "w"
    dest.mkdir()
    status, _ = store.download_external(srv.base + "/missing", dest)
    assert status == "error"


def test_download_external_size_limit_marks_manual(local_http, tmp_path):
    srv = local_http({"/big": (200, b"x" * 100, {"Content-Type": "application/octet-stream"})})
    dest = tmp_path / "w"
    dest.mkdir()
    status, info = store.download_external(srv.base + "/big", dest, max_bytes=10)
    assert status == "manual"
    assert not (dest / "big").exists()  # a partial file must never be left behind


def test_download_external_mega_without_tool_is_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(store.shutil, "which", lambda name: None)
    status, info = store.download_external("https://mega.nz/file/x#y", tmp_path)
    assert status == "manual" and "megatools" in info


def test_download_external_gdrive_failure_is_manual(tmp_path, monkeypatch):
    import gdown
    monkeypatch.setattr(gdown, "download", lambda *a, **k: None)
    status, info = store.download_external("https://drive.google.com/file/d/abc/view", tmp_path)
    assert status == "manual"


def test_download_external_never_sends_ctfd_auth(local_http, tmp_path, monkeypatch):
    seen = {}
    real_get = requests.get

    def spy(url, **kw):
        seen["headers"] = kw.get("headers")
        return real_get(url, **kw)

    monkeypatch.setattr(store.requests, "get", spy)
    srv = local_http({"/f": (200, b"ok", {"Content-Type": "application/octet-stream"})})
    dest = tmp_path / "w"
    dest.mkdir()
    store.download_external(srv.base + "/f", dest)
    assert seen["headers"] is None  # no Authorization header leaks to third-party hosts


def test_do_downloads_ignores_traversal_names(fake, base_dir):
    """A file name like '..' from the API must never escape work/."""
    from flagship.ctfd import CTFd
    client = CTFd(fake.url, "test-token")
    d = base_dir / "CHALLENGES" / "web" / "T"
    d.mkdir(parents=True)
    fake.add_file("/files/1/..", b"should-not-be-written")
    store._do_downloads(client, d, {"files": ["/files/1/.."]}, [])
    # the name is sanitised to download.bin; the request itself fails (HTTP client normalises '..')
    report = (d / "downloads.txt").read_text(encoding="utf-8")
    assert "work/download.bin" in report
    assert not (d / "CHALLENGES" / "web" / "work").exists()
    assert {p.name for p in (base_dir / "CHALLENGES" / "web").iterdir()} == {"T"}


def test_download_one_file_writes_report(fake, base_dir):
    from flagship.ctfd import CTFd
    fake.add_file("/files/5/chall.zip?token=s", b"ZIPDATA", {"Content-Type": "application/zip"})
    client = CTFd(fake.url, "test-token")
    d = base_dir / "CHALLENGES" / "web" / "R"
    d.mkdir(parents=True)
    store._do_downloads(client, d, {"files": ["/files/5/chall.zip?token=s"]}, [])
    assert (d / "work" / "chall.zip").read_bytes() == b"ZIPDATA"
    assert "[ok] work/chall.zip" in (d / "downloads.txt").read_text(encoding="utf-8")


def test_settled_external_links_are_not_requested_again(local_http, tmp_path, monkeypatch):
    """A page or a fetched link needs no new request on the next full sync; a failed one is retried."""
    srv = local_http({"/page": (200, b"<html>writeup</html>", {"Content-Type": "text/html"})})
    page, broken = srv.base + "/page", srv.base + "/missing"
    d = tmp_path / "CHALLENGES" / "web" / "L"
    d.mkdir(parents=True)
    detail = {"files": [], "description": f"read {page} and {broken}"}
    calls = []
    real = store.download_external

    def spy(url, dest_dir, **kw):
        calls.append(url)
        return real(url, dest_dir, **kw)

    monkeypatch.setattr(store, "download_external", spy)
    store._do_downloads(None, d, detail, store.extract_links(detail["description"]))
    assert calls == [page, broken]
    calls.clear()
    store._do_downloads(None, d, detail, store.extract_links(detail["description"]))
    assert calls == [broken], "the page is settled, the failed link must be retried"
    report = (d / "downloads.txt").read_text(encoding="utf-8")
    assert f"[page] {page}" in report and f"[error] {broken}" in report


def test_write_text_atomic_replaces_whole_file_only(tmp_path):
    p = tmp_path / "state.json"
    store.write_text_atomic(p, "one")
    store.write_text_atomic(p, "two")
    assert p.read_text(encoding="utf-8") == "two"
    assert not (tmp_path / "state.json.tmp").exists()


def test_stopped_download_leaves_no_file_and_no_part(tmp_path):
    """A quit in the middle of a stream must not leave a truncated file a later run would skip."""
    from flagship import shutdown
    from flagship.ctfd import _stream_to

    class Stream:
        def close(self):
            pass

        def iter_content(self, n):
            for chunk_no in range(1000):
                if chunk_no == 3:
                    shutdown.request()  # the user presses q while the download is running
                yield b"x" * n

    dest = tmp_path / "big.zip"
    status, info = _stream_to(Stream(), dest, 2**40)
    assert status == "error" and "stopped" in info
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_completed_download_is_renamed_from_part(tmp_path):
    from flagship.ctfd import _stream_to

    class Two:
        def close(self):
            pass

        def iter_content(self, n):
            yield b"ab"
            yield b"cd"

    dest = tmp_path / "f.bin"
    assert _stream_to(Two(), dest, 2**40) == ("ok", "4 B")
    assert dest.read_bytes() == b"abcd"
    assert not dest.with_name(dest.name + ".part").exists()
