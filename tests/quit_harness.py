"""Runs the real Flagship entry point against a slow in-process platform (used by test_quit.py).

usage: quit_harness.py <platform_delay_seconds>
Prints READY once the platform is seeded and the config is written, then runs the TUI.
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from conftest import write_config  # noqa: E402
from fake_ctfd import FakeCTFd  # noqa: E402
from flagship import app as tui  # noqa: E402
from flagship import store  # noqa: E402
from flagship.ctfd import CTFd  # noqa: E402

delay = float(sys.argv[1])
fake = FakeCTFd()
for i in range(1, 41):
    fake.add_challenge(i, f"C{i}", category="web", value=100, description="d")
url = fake.start()
tmp = pathlib.Path(tempfile.mkdtemp())
base = tmp / "CTF"
base.mkdir()
store.sync(CTFd(url, "test-token"), base, True, False, 6)  # 40 challenges already downloaded
fake.delays["/api/v1/challenges/"] = delay                 # the platform now answers slowly
cfg = write_config(tmp / "config.sh", url, base, POLL_INTERVAL="0", WATCH_INTERVAL="0")
print("READY", flush=True)
sys.argv = ["flagship", str(cfg)]
tui.cli()
