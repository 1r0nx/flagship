"""The documentation (EN/FR), the example config, the key bindings and the code must agree."""

import ast
import re
from pathlib import Path

import pytest

from flagship import app as tui
from flagship.config import Config

ROOT = Path(__file__).resolve().parent.parent
EN = (ROOT / "doc" / "EN.md").read_text(encoding="utf-8")
FR = (ROOT / "doc" / "FR.md").read_text(encoding="utf-8")
EXAMPLE = (ROOT / "config.sh.example").read_text(encoding="utf-8")


def section(text: str, heading_start: str) -> str:
    """Body of the '## ...' section whose title starts with heading_start (up to the next '## ')."""
    m = re.search(rf"^## {re.escape(heading_start)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"section {heading_start!r} not found"
    return m.group(1)


def doc_keys(body: str) -> set[str]:
    """Keys of the keyboard table: the first column, one key per backtick pair."""
    keys = set()
    for row in body.splitlines():
        if not row.startswith("|") or set(row) <= set("|-: "):
            continue
        first = row.split("|")[1]
        keys.update(k for k in re.findall(r"`([^`]+)`", first) if len(k) <= 2 or k in ("Esc", "Échap"))
    return keys


def binding_keys() -> set[str]:
    """Single-key bindings of the app, as the doc writes them (e.g. slash -> '/')."""
    names = {"slash": "/", "escape": "Esc"}
    out = set()
    for b in tui.Flagship.BINDINGS:
        key = b[0] if isinstance(b, tuple) else b.key
        out.add(names.get(key, key))
    return out


@pytest.mark.parametrize("text,title", [(EN, "Keyboard shortcuts"), (FR, "Raccourcis clavier")])
def test_every_binding_is_documented_and_vice_versa(text, title):
    documented = {"Esc" if k == "Échap" else k for k in doc_keys(section(text, title))}
    bound = binding_keys()
    # arrows, Enter and the pane splitter are gestures documented next to the bindings
    gestures = {"↑", "↓", "┃"}
    assert bound - documented == set(), f"bound but undocumented: {bound - documented}"
    assert documented - bound - gestures == set(), f"documented but not bound: {documented - bound - gestures}"


def config_keys(block: str) -> set[str]:
    return {ln.split("=", 1)[0].strip() for ln in block.splitlines()
            if "=" in ln and not ln.lstrip().startswith("#") and ln[:1].isalpha()}


@pytest.mark.parametrize("text,title", [(EN, "Configure"), (FR, "Configuration")])
def test_documented_config_keys_match_example(text, title):
    body = section(text, title)
    doc = config_keys(body) - {"URL", "CTFD_TOKEN"}
    example = config_keys(EXAMPLE) - {"URL", "CTFD_TOKEN"}
    assert doc == example, f"doc only: {doc - example} | example only: {example - doc}"


def test_every_example_key_is_read_by_the_loader():
    source = (ROOT / "flagship" / "config.py").read_text(encoding="utf-8")
    for key in config_keys(EXAMPLE):
        assert f'"{key}"' in source, f"{key} documented in the example but never read"


@pytest.mark.parametrize("text,title", [(EN, "Themes"), (FR, "Thèmes")])
def test_documented_themes_are_the_real_ones(text, title, tmp_path):
    body = section(text, title)
    documented = set(re.findall(r"`([a-z0-9-]+)`", body))
    cfg = Config(url="http://x", token="t", base_dir=tmp_path, ctf_name="c", poll_interval=0,
                 write_flag_on_solve=True, watch_changes=True, watch_interval=0,
                 auto_unlock_free_hints=False, download_workers=1, theme="textual-dark", editor="",
                 config_dir=tmp_path, auto_notes=False)
    real = set(tui.Flagship(cfg, offline=True).available_themes)
    assert documented == real, f"doc only: {documented - real} | app only: {real - documented}"


def test_en_and_fr_have_the_same_structure():
    heads_en = [h for h in re.findall(r"^(#{1,3}) ", EN, re.M)]
    heads_fr = [h for h in re.findall(r"^(#{1,3}) ", FR, re.M)]
    assert heads_en == heads_fr, "EN and FR documents must have the same heading structure"


def test_en_and_fr_have_the_same_file_tree_and_placeholders():
    assert EN.count("```") == FR.count("```")
    for text in (EN, FR):
        assert "nom-du-challenge.md" not in text.replace("<nom-du-challenge>.md", "")
        assert "desc2.txt" not in text and "desc.txt" not in text.replace("legacy", "")


@pytest.mark.parametrize("text", [EN, FR])
def test_no_trailing_whitespace_in_docs(text):
    assert all(line == line.rstrip() for line in text.splitlines())


def test_user_facing_strings_are_english():
    """The interface and generated text are English (see the docs): no French in string literals."""
    accents = re.compile(r"[éèàçêôîûùâëïüœÉÈÀÇ]")
    offenders = []
    for name in ("app.py", "store.py", "ctfd.py", "config.py"):
        tree = ast.parse((ROOT / "flagship" / name).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if accents.search(node.value):
                    offenders.append(f"{name}:{node.lineno}: {node.value[:60]!r}")
    assert offenders == [], "French text in user-facing strings:\n" + "\n".join(offenders)
