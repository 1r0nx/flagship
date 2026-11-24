"""Export of every written challenge note into one zip (store.export_notes) and its TUI key `N`."""

import asyncio
import zipfile
from pathlib import Path

import pytest

from flagship import store
from flagship import app as tui
from flagship.config import Config
from conftest import write_config


def make_challenge(base: Path, cat: str, name: str, note: str | None = None, solved: bool = False) -> Path:
    d = base / "CHALLENGES" / cat / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "work").mkdir(exist_ok=True)
    (d / "work" / "secret.bin").write_bytes(b"do not export")
    (d / f"{name}.txt").write_text("statement", encoding="utf-8")
    if note is not None:
        (d / f"{name}.md").write_text(note, encoding="utf-8")
    if solved:
        (d / "flag.txt").write_text("HLB{x}\n", encoding="utf-8")
    return d


SKELETON = "# Name\n**Category:** web | **Points:** 100\n\n## Notes\n\n"


@pytest.mark.parametrize("text,expected", [
    (SKELETON, True),
    ("# Name\n**Category:** web | **Points:** 100\n\n## Notes\n", True),
    (SKELETON + "found the bug in login\n", False),
    ("", True),
    ("random text\n", False),
])
def test_skeleton_detection(text, expected):
    assert store.is_skeleton_only(text) is expected


def test_only_written_notes_are_exported(tmp_path):
    base = tmp_path / "CTF"
    make_challenge(base, "web", "Written", note=SKELETON + "my analysis\n", solved=True)
    make_challenge(base, "web", "Skeleton", note=SKELETON)           # template only: excluded
    make_challenge(base, "pwn", "NoNote")                            # no notes file: excluded
    d = make_challenge(base, "crypto", "Misnamed")
    (d / "notes.md").write_text("my analysis\n", encoding="utf-8")   # not <name>.md: excluded
    out = store.export_notes(base, "MyCTF")
    assert out is not None and out.parent == base
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert names == {"CHALLENGES/web/Written/Written.md", "INDEX.md"}
        assert "my analysis" in z.read("CHALLENGES/web/Written/Written.md").decode()
        index = z.read("INDEX.md").decode()
    assert "| web | Written | ✔ |" in index and "Skeleton" not in index


def test_zip_keeps_category_hierarchy_and_never_contains_work_or_flags(tmp_path):
    base = tmp_path / "CTF"
    make_challenge(base, "crypto", "A", note=SKELETON + "a\n")
    make_challenge(base, "web", "B", note=SKELETON + "b\n", solved=True)
    out = store.export_notes(base, "MyCTF")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "CHALLENGES/crypto/A/A.md" in names and "CHALLENGES/web/B/B.md" in names
    assert not any(n.endswith(("secret.bin", "flag.txt", ".txt", "config.sh")) for n in names)


def test_nothing_to_export_creates_no_zip(tmp_path):
    base = tmp_path / "CTF"
    make_challenge(base, "web", "Only", note=SKELETON)
    assert store.export_notes(base) is None
    assert not list(base.glob("notes-export-*.zip"))


def test_export_never_overwrites_an_earlier_one(tmp_path, monkeypatch):
    base = tmp_path / "CTF"
    make_challenge(base, "web", "W", note=SKELETON + "x\n")
    first = store.export_notes(base)
    second = store.export_notes(base)
    assert first != second and first.exists() and second.exists()


def test_only_solved_option_exports_solved_challenges(tmp_path):
    base = tmp_path / "CTF"
    make_challenge(base, "web", "Solved", note=SKELETON + "a\n", solved=True)
    make_challenge(base, "web", "Open", note=SKELETON + "b\n")
    out = store.export_notes(base, "MyCTF", solved_only=True)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "CHALLENGES/web/Solved/Solved.md" in names
    assert not any("Open" in n for n in names)


def test_only_solved_with_no_solved_notes_creates_no_zip(tmp_path):
    base = tmp_path / "CTF"
    make_challenge(base, "web", "Open", note=SKELETON + "b\n")
    assert store.export_notes(base, solved_only=True) is None
    assert not list(base.glob("notes-export-*.zip"))


def _app_with(base_dir, tmp_path, fake):
    cfg = Config.load(write_config(tmp_path / "config.sh", fake.url, base_dir, POLL_INTERVAL="0"))
    return tui.Flagship(cfg, offline=True)


def test_export_key_opens_chooser_and_exports_all(fake, base_dir, tmp_path):
    make_challenge(base_dir, "web", "Keyed", note=SKELETON + "key test\n")
    make_challenge(base_dir, "pwn", "Other", note=SKELETON + "other\n", solved=True)

    async def scenario():
        app = _app_with(base_dir, tmp_path, fake)
        async with app.run_test(size=(170, 55)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("N")
            await pilot.pause(0.2)
            assert isinstance(app.screen, tui.ExportNotesScreen)
            await pilot.press("enter")          # first choice: all written notes
            await pilot.pause(0.3)
    asyncio.run(scenario())
    [zip_path] = list(base_dir.glob("notes-export-*.zip"))
    with zipfile.ZipFile(zip_path) as z:
        assert {"CHALLENGES/web/Keyed/Keyed.md", "CHALLENGES/pwn/Other/Other.md"} <= set(z.namelist())


def test_export_key_second_choice_exports_only_solved(fake, base_dir, tmp_path):
    make_challenge(base_dir, "web", "Keyed", note=SKELETON + "open\n")
    make_challenge(base_dir, "pwn", "Won", note=SKELETON + "won\n", solved=True)

    async def scenario():
        app = _app_with(base_dir, tmp_path, fake)
        async with app.run_test(size=(170, 55)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("N")
            await pilot.pause(0.2)
            await pilot.press("down", "enter")  # "Solved challenges only"
            await pilot.pause(0.3)
    asyncio.run(scenario())
    [zip_path] = list(base_dir.glob("notes-export-*.zip"))
    with zipfile.ZipFile(zip_path) as z:
        assert z.namelist().count("CHALLENGES/pwn/Won/Won.md") == 1
        assert not any("Keyed" in n for n in z.namelist())


def test_escape_cancels_export(fake, base_dir, tmp_path):
    make_challenge(base_dir, "web", "Keyed", note=SKELETON + "x\n")

    async def scenario():
        app = _app_with(base_dir, tmp_path, fake)
        async with app.run_test(size=(170, 55)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("N")
            await pilot.pause(0.2)
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, tui.ExportNotesScreen)
    asyncio.run(scenario())
    assert not list(base_dir.glob("notes-export-*.zip"))


def test_export_key_without_notes_warns_and_writes_nothing(fake, base_dir, tmp_path):
    async def scenario():
        app = _app_with(base_dir, tmp_path, fake)
        async with app.run_test(size=(170, 55)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("N")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, tui.ExportNotesScreen)  # no popup without notes
    asyncio.run(scenario())
    assert not list(base_dir.glob("notes-export-*.zip"))
