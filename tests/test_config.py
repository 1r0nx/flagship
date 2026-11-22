"""config.sh parsing: keys, defaults, quoting, comments, BOM, and the example file."""

from pathlib import Path

import pytest

from flagship.config import Config, _as_bool, _as_int, parse_sh


def test_example_file_parses_every_documented_key(tmp_path):
    example = Path(__file__).resolve().parent.parent / "config.sh.example"
    text = example.read_text(encoding="utf-8")
    cfgfile = tmp_path / "config.sh"
    cfgfile.write_text(text.replace("https://ctf.example.com", "https://ctf.example.com")
                       .replace("ctfd_xxxxxxxxxxxxxxxxxxx", "tok"), encoding="utf-8")
    cfg = Config.load(cfgfile)
    assert cfg.url == "https://ctf.example.com"
    assert cfg.theme == "textual-dark"
    assert cfg.auto_notes is False and cfg.auto_unlock_free_hints is False
    assert cfg.download_workers == 6 and cfg.poll_interval == 60


def test_every_key_in_example_is_known_to_the_loader():
    """A key documented in config.sh.example must be read by Config.load (no silent typo)."""
    example = Path(__file__).resolve().parent.parent / "config.sh.example"
    keys = {ln.split("=", 1)[0].strip() for ln in example.read_text(encoding="utf-8").splitlines()
            if "=" in ln and not ln.lstrip().startswith("#") and ln[:1].isalpha()}
    source = (Path(__file__).resolve().parent.parent / "flagship" / "config.py").read_text(encoding="utf-8")
    unknown = [k for k in keys if k not in ("URL", "CTFD_TOKEN") and f'"{k}"' not in source]
    assert unknown == [], f"documented but never read: {unknown}"


def test_defaults_when_optional_keys_missing(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("URL=https://x.example/\nTOKEN=abc\n", encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.url == "https://x.example"          # trailing slash stripped
    assert cfg.token == "abc"                      # generic *TOKEN accepted
    assert cfg.ctf_name == "x.example"
    assert cfg.base_dir == (tmp_path / "x.example").resolve()
    assert cfg.write_flag_on_solve and cfg.watch_changes
    assert cfg.watch_interval == 300 and cfg.poll_interval == 60
    assert cfg.theme == "textual-dark" and cfg.editor == "" and cfg.auto_notes is False


def test_token_variable_with_prefix_is_found(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("export CTFD_URL='https://x.example'\nPWNY_CTFD_TOKEN=\"sek ret\"\n", encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.url == "https://x.example" and cfg.token == "sek ret"


def test_missing_url_or_token_is_an_error(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("URL=https://x.example\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(p)
    p.write_text("CTFD_TOKEN=abc\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Config.load(tmp_path / "nope.sh")


def test_bom_and_inline_comments(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("﻿URL=https://x.example   # the url\nCTFD_TOKEN=abc # secret comment\n", encoding="utf-8")
    d = parse_sh(p)
    assert d["URL"] == "https://x.example"
    assert d["CTFD_TOKEN"] == "abc"


def test_hash_inside_quotes_is_kept(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text('URL=https://x.example\nCTFD_TOKEN="ab#cd"\n', encoding="utf-8")
    assert parse_sh(p)["CTFD_TOKEN"] == "ab#cd"


@pytest.mark.parametrize("raw,expected", [("true", True), ("TRUE", True), ("1", True), ("oui", True),
                                          ("false", False), ("0", False), ("no", False), ("", False)])
def test_as_bool(raw, expected):
    assert _as_bool(raw, default=True if raw == "" else False) is expected


def test_as_bool_default_when_missing():
    assert _as_bool(None, default=True) is True
    assert _as_bool(None, default=False) is False


def test_as_int_falls_back_on_garbage():
    assert _as_int("60s", 60) == 60
    assert _as_int(None, 300) == 300
    assert _as_int(" 12 ", 1) == 12


def test_negative_and_zero_intervals_are_clamped(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("URL=https://x.example\nCTFD_TOKEN=a\nWATCH_INTERVAL=-5\nDOWNLOAD_WORKERS=0\n", encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.watch_interval == 0 and cfg.download_workers == 1


def test_relative_base_dir_resolved_against_config_folder(tmp_path):
    p = tmp_path / "sub" / "config.sh"
    p.parent.mkdir()
    p.write_text("URL=https://x.example\nCTFD_TOKEN=a\nBASE_DIR=./data\n", encoding="utf-8")
    assert Config.load(p).base_dir == (tmp_path / "sub" / "data").resolve()


def test_auto_notes_option(tmp_path):
    p = tmp_path / "config.sh"
    p.write_text("URL=https://x.example\nCTFD_TOKEN=a\nAUTO_NOTES=true\n", encoding="utf-8")
    assert Config.load(p).auto_notes is True
