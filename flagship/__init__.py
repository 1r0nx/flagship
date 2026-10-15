"""Flagship: CTFd TUI (sync + browsing + submission)."""
__version__ = "0.2.0"

# requests warns at import when the bundled urllib3/chardet versions differ from what it was
# tested against (an environment mismatch, harmless here). Silence it before any submodule
# imports requests, so it doesn't print over the TUI on startup.
import warnings as _warnings
_warnings.filterwarnings("ignore", message=r".*doesn't match a supported version.*")
