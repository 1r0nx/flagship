"""Quitting with `q` must not wait for requests still in flight on a slow platform.

Runs the real entry point in a pseudo-terminal (needs pexpect; skipped otherwise, and on Windows).
"""
import os
import sys
import time
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminal test (POSIX only)")

HARNESS = Path(__file__).resolve().parent / "quit_harness.py"
DELAY = 3.0          # every challenge request takes 3 s on the platform
MAX_QUIT = 1.5       # quitting must not wait for them (measured ~0.4 s incl. Textual's own teardown)


def test_q_does_not_wait_for_slow_requests_in_flight():
    child = pexpect.spawn(sys.executable, [str(HARNESS), str(DELAY)], timeout=60,
                          env={**os.environ, "TERM": "xterm-256color"}, dimensions=(50, 160))
    try:
        child.expect("READY", timeout=60)
        child.expect(pexpect.TIMEOUT, timeout=1.5)  # the watch pass is now waiting on slow requests
        started = time.time()
        child.send("q")
        child.expect(pexpect.EOF, timeout=30)
        elapsed = time.time() - started
    finally:
        child.close(force=True)
    assert elapsed < MAX_QUIT, f"quit took {elapsed:.2f}s with requests in flight"
    assert child.exitstatus == 0
