"""Process-wide "stop" flag, raised when the user quits the TUI.

Worker threads check it between two requests / two chunks, so a quit does not have to wait for the
whole batch (one slow request, or a multi-GB download, must never hold the terminal).
"""

from __future__ import annotations

import threading

_stop = threading.Event()


def request() -> None:
    """Ask every background job to stop as soon as it can."""
    _stop.set()


def requested() -> bool:
    return _stop.is_set()


def reset() -> None:
    """Clear the flag (tests only)."""
    _stop.clear()
