"""Shared fixtures: a fake CTFd server, a config pointing at it, and a clean base folder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # import the `flagship` package from the repo
sys.path.insert(0, str(ROOT / "tests"))  # import fake_ctfd

from fake_ctfd import TOKEN, FakeCTFd  # noqa: E402

import pytest as _pytest  # noqa: E402

from flagship import shutdown  # noqa: E402


@_pytest.fixture(autouse=True)
def _no_stale_quit_flag():
    """The quit flag is process-wide: a test that quits must not leave it raised for the next one."""
    shutdown.reset()
    yield
    shutdown.reset()


@pytest.fixture
def fake():
    server = FakeCTFd()
    server.url = server.start()
    yield server
    server.stop()


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    d = tmp_path / "MyCTF"
    d.mkdir()
    return d


def write_config(path: Path, url: str, base: Path, token: str = TOKEN, **extra: str) -> Path:
    lines = [f"URL={url}", f"CTFD_TOKEN={token}", f"BASE_DIR={base}", "CTF_NAME=MyCTF"]
    lines += [f"{k}={v}" for k, v in extra.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def cfg_file(tmp_path: Path, fake, base_dir) -> Path:
    return write_config(tmp_path / "config.sh", fake.url, base_dir,
                        POLL_INTERVAL="0", WATCH_CHANGES="true", WATCH_INTERVAL="0")
